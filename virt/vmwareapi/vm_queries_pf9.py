# vim: tabstop=6 shiftwidth=4 softtabstop=4
# Copyright (c) 2014 Platform9 Systems Inc.

from oslo_config import cfg
from oslo_log import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import constants
from oslo_vmware import exceptions as vexc
from oslo_vmware import vim_util as oslo_vutil
from nova.compute import power_state
from nova import exception
import nova.virt
from netaddr import IPAddress


pf9_opts_group = cfg.OptGroup(name='PF9')
pf9_opts = [
    cfg.StrOpt(name='ignore_folders', default='pf9_cinder_volumes',
               help='All VMs under the specified folders will only be logged '
                    'and not reported. Comma separated value.')
]

CONF = cfg.CONF
CONF.register_group(pf9_opts_group)
CONF.register_opts(pf9_opts, group=pf9_opts_group)

LOG = logging.getLogger(__name__)


def _get_moid_from_node(node):
    return node.split('(')[0]


def list_instance_uuids_on_vcenter(driver, node=None):
    uuids = dict()
    for vm in get_vms_on_authed_clusters(driver, node):
        uuid = None
        path = None
        vmref = vm.obj
        for prop in vm.propSet:
            if prop.name == "summary.config.instanceUuid":
                uuid = prop.val
            elif prop.name == "summary.config.vmPathName":
                path = prop.val
            if uuid and path:
                break
        if path[-4:] == 'vmtx':
            uuids[uuid] = {'vmref': vmref, 'template': True}
        else:
            uuids[uuid] = {'vmref': vmref, 'template': False}
    return uuids


def _get_res_pool_obj_list(driver, node=None):
    """
    Gets all the resource pools belonging to a cluster
    """
    res_pools = []
    res_pool_objects = driver._session._call_method(vim_util, "get_objects",
                                                    "ResourcePool", ['owner'])
    cluster_moids = [driver._cluster_ref.value]
    if res_pool_objects:
        for res_pool_obj in res_pool_objects.objects:
            for prop in res_pool_obj.propSet:
                if prop.name == 'owner' and prop.val.value in cluster_moids:
                    res_pools.append(res_pool_obj.obj)
    return res_pools


def _continue_get_objects(driver, result):
    return driver._session._call_method(oslo_vutil,
                                        "continue_retrieval", result)


def _get_all_vms(driver):
    """
    Generator for getting all VMs.
    Required for backward compatibility with ESX driver and for unit tests
    related to same
    No method other than get_vm_ref and get_template_ref should use this method
    These methods are allowed to make calls to this function as they are used
    with ESX drivers as well.
    """
    return_list = []
    vms = _get_vms_on_vcenter(driver)
    while vms:
        for vm in vms.objects:
            return_list.append(vm)
        vms = _continue_get_objects(driver, result=vms)
    return return_list


def _get_vms_on_vcenter(driver):
    vms = driver._session._call_method(vim_util, "get_objects",
                                       "VirtualMachine",
                                       [
                                           "name",
                                           "runtime.connectionState",
                                           "summary.config.vmPathName",
                                           "summary.config.instanceUuid",
                                           "resourcePool",
                                           "parent"
                                       ])
    return vms


def get_vms_on_authed_clusters(driver, node=None):
    folder_ref_name = dict()
    res_pools_to_look_for = [x.value for x in _get_res_pool_obj_list(driver, node)]
    folders_to_ignore = [x.strip() for x in CONF.PF9.ignore_folders.split(',')]
    vms = []
    for vm in _get_all_vms(driver):
        uuid = None
        conn_state = None
        datastore = None
        vm_path = None
        resource_pool = None
        folder_ref = None
        vm_name = None
        for prop in vm.propSet:
            if prop.name == "runtime.connectionState":
                conn_state = prop.val
            elif prop.name == 'summary.config.vmPathName':
                vm_path = prop.val
                datastore = vm_path[vm_path.find('[')+1:vm_path.find(']')]
            elif prop.name == "resourcePool":
                resource_pool = prop.val.value
            elif prop.name == 'summary.config.instanceUuid':
                uuid = prop.val
            elif prop.name == 'parent':
                folder_ref = prop.val
            elif prop.name == 'name':
                vm_name = prop.val

        if folder_ref not in folder_ref_name:
            folder_ref_name[folder_ref] = driver._session._call_method(
                oslo_vutil, "get_object_property", folder_ref, "name")

        folder_name = folder_ref_name[folder_ref]

        # Ignoring the orphaned or inaccessible VMs
        # Ignoring templates
        # Ignoring VMs from other datastores
        if conn_state in ['orphaned', 'inaccessible']:
            LOG.warn('Ignoring VM [{0}] with connection state '
                     '[{1}]'.format(uuid, conn_state))
            continue
        if driver._datastore_regex and \
                not driver._datastore_regex.match(datastore):
            continue

        if folder_name in folders_to_ignore:
            # Ignore VMs in folders that are specified "ignore_folders"
            # in nova.conf
            LOG.info('Ignoring VM {name} as per config'.format(name=vm_name))
            continue
        if vm_path[-4:] == 'vmtx':
            vms.append(vm)
        else:
            if resource_pool and resource_pool in res_pools_to_look_for:
                vms.append(vm)
    return vms


def get_instance_info_for_vms(driver, instance_uuids):
    if isinstance(driver, nova.virt.vmwareapi.VMwareVCDriver) or \
            isinstance(driver, nova.virt.vmwareapi.vmops.VMwareVMOps) or driver.__class__.__name__ == 'fake_driver':
        driver = driver._session
    vm_infos = dict()
    vmware_name_to_ostack_name = {
        'summary.guest.ipAddress': 'access_ip_v{version}',
        'summary.config.name': 'name',
        'summary.config.numCpu': 'vcpus',
        'summary.config.memorySizeMB': 'memory_mb',
        'runtime.powerState': 'power_state',
        'summary.config.instanceUuid': 'instance_uuid',
        'resourcePool': 'resourcePool'
    }

    vmware_powerstate_to_ostack_powerstate = {
        'poweredOn': power_state.RUNNING,
        'poweredOff': power_state.SHUTDOWN,
        'suspended': power_state.SUSPENDED,
    }
    try:
        vmrefs = []
        for uuid in instance_uuids.keys():
            vmrefs.append(instance_uuids[uuid]['vmref'])
    except exception as excep:
        LOG.warn("Could not find VM with %s uuid" % uuid)
    try:
        objects = driver._call_method(
            vim_util, "get_properties_for_objects_pf9", None, vmrefs,
            "VirtualMachine", ["summary.guest.ipAddress",
                               "summary.config.name",
                               "summary.config.numCpu",
                               "summary.config.memorySizeMB",
                               "runtime.powerState",
                               "summary.config.vmPathName",
                               "summary.config.guestId",
                               "summary.config.instanceUuid",
                               "config.hardware.device",
                               "guest.net",
                               "resourcePool"])
    except (vexc.VimFaultException, vexc.VMwareDriverException) as e:
        LOG.error('Could not get information regarding VMs with [{uuid}] UUIDs.'
                 'Ignoring. Error was {error_msg}'.format(uuid=instance_uuids,
                                                          error_msg=e.message))
        return {}

    os_type = constants.DEFAULT_OS_TYPE

    for obj in objects.objects:
        template = False
        return_list = {}
        for prop in obj.propSet:
            if prop.name == "summary.config.vmPathName":
                # Check if detected VM is a template
                vm_path = prop.val
                return_list['datastore'] = vm_path[vm_path.find("[")+1:vm_path.find("]")]
                if prop.val[-4:] == "vmtx":
                    return_list["template"] = dict()
                    return_list['template']['path'] = prop.val
                    return_list['template']['hypervisor_type'] = "vmware"
                    return_list['template']['disk_format'] = 'vmdk'
                    return_list['template']['type'] = 'vmdk'
                    # disk_type is needed for glance only. This
                    # property is not used in provisioning of VM, hence
                    # defaulting to preallocated
                    return_list['template']['vmware_disktype'] = 'preallocated'
                    return_list['moref'] = obj.obj.value
                    template = True
            elif prop.name == "summary.config.guestId":
                os_type = prop.val
            elif prop.name == "summary.guest.ipAddress":
                ip_ver = IPAddress(prop.val).version
                key = vmware_name_to_ostack_name[prop.name].format(version=ip_ver)
                return_list[key] = prop.val
            elif prop.name in vmware_name_to_ostack_name.keys():
                if prop.name == "runtime.powerState":
                    pstate = vmware_powerstate_to_ostack_powerstate.get(prop.val)
                    if pstate:
                        return_list[vmware_name_to_ostack_name[prop.name]] = \
                            int(pstate)
                    else:
                        return_list[vmware_name_to_ostack_name[prop.name]] = \
                        int(power_state.NOSTATE)
                else:
                    return_list[vmware_name_to_ostack_name[prop.name]] = prop.val
            elif prop.name == "config.hardware.device":
                devices = prop.val
            elif prop.name == "guest.net":
                guest_nics_info = prop.val
                networks = []
                if guest_nics_info:
                    for nic_info in guest_nics_info.GuestNicInfo:
                        ip_addresses = nic_info['ipAddress'] \
                                        if hasattr(nic_info, 'ipAddress') else None
                        mac_address = nic_info['macAddress'] \
                                        if hasattr(nic_info, 'macAddress')else None
                        network_name = nic_info['network'] \
                                        if hasattr(nic_info, 'network') else None
                        # select ipv4 if available, otherwise select first ip present
                        ip_address = None
                        if ip_addresses is not None:
                            for ip in ip_addresses:
                                if IPAddress(ip).version == 4:
                                    ip_address = ip
                                    break
                            if ip_address is None:
                                ip_address = ip_addresses[0]

                        networks.append({'ip_address': ip_address,
                                       'mac_address': mac_address,
                                       'bridge': network_name})
                return_list['networks'] = networks
        try:
            devices = _get_disk_and_mac_info(devices, template=template)
            if template:
                return_list['template']['vmware_adaptertype'] = devices['template'].get(
                                                        'vmware_adaptertype', 'lsiLogic')
                return_list['template']['size'] = devices['template'].get('size', 0)
                return_list['template']['virtual_size'] = devices['template'].get(
                                                                    'virtual_size', 0)
                return_list['template']['vmware_ostype'] = os_type
            else:
                return_list['block_device_mapping_v2'] = devices.get('bdm')
            return_list['virtual_interfaces'] = devices.get('vif')
        except:
            LOG.error("Devices information not available")
        # add info to vm_infos only if return_list has key instance_uuid
        uuid = return_list.get('instance_uuid', None)
        if uuid:
            vm_infos[return_list['instance_uuid']] = return_list
    return vm_infos


def _get_disk_and_mac_info(devices, template=False):
    """
    Get information related to hard disks and mac addresses of the given VM
    Information is returned in the format consistent with format required by
    get_instance_info()
    """
    key_to_device = dict()
    return_info = dict()
    return_info['bdm'] = []
    return_info['vif'] = []

    for device_info in devices.VirtualDevice:
        try:
            key_to_device[device_info.key] = device_info.__class__.__name__
            if 'VirtualDisk' == device_info.__class__.__name__:
                if template:
                    adaptertype = key_to_device.get(
                                    device_info['controllerKey'], None)
                    return_info['template'] = dict()
                    # Defaulting to "lsiLogic" as it is most common adapter type
                    if not adaptertype or "lsilogic" in adaptertype.lower():
                        return_info['template']['vmware_adaptertype'] = 'lsiLogic'
                    elif "buslogic" in adaptertype.lower():
                        return_info['template']['vmware_adaptertype'] = 'busLogic'
                    elif "ide" in adaptertype.lower():
                        return_info['template']['vmware_adaptertype'] = 'ide'
                    return_info['template']['size'] = device_info.capacityInKB * 1024
                    return_info['template']['virtual_size'] = device_info.capacityInKB * 1024
                    # No need to process further in case of templates
                    return return_info
                disk_info = dict()
                try:
                    disk_info['device_name'] = \
                                device_info.deviceInfo.label.replace(' ', '_')
                    disk_info['boot_index'] = device_info.unitNumber
                    # compute api expects disk size in bytes
                    disk_info['virtual_size'] = device_info.capacityInKB * 1024
                except AttributeError as excep:
                    disk_info['device_name'] = ''
                    disk_info['boot_index'] = -1
                    disk_info['virtual_size'] = 0
                disk_info['delete_on_termination'] = False
                disk_info['guest_format'] = 'volume'
                disk_info['source_type'] = 'blank'
                # TODO: destination type has 2 valid values - local and volume.
                #       Since we do not have cinder discovery defaulting to
                #       local.
                disk_info['destination_type'] = 'local'
                # These new values have been made non-lazy loadable in liberty
                # and hence need to set explicitly
                disk_info['snapshot_id'] = None
                disk_info['volume_id'] = None
                disk_info['volume_size'] = None
                disk_info['image_id'] = None
                return_info['bdm'].append(disk_info)
            elif device_info.__class__.__name__.lower().find("net") != -1 \
                            or "Network" in device_info.deviceInfo.label:
                # This condition is not same above as there are 3
                # different types of net-
                # 1. VMXNET2
                # 2. VMXNET3
                # 3. VMPCNET32
                # The 'or' part of condition is present in case I have
                # missed any other type of network
                # In second condition we are checking if the device
                # label contains 'Network'. Default value is
                # 'Network Adapter'.
                virtual_interface = dict()
                virtual_interface['mac_address'] = \
                            device_info.macAddress
                virtual_interface['port_group_label'] = \
                                device_info.deviceInfo.label
                virtual_interface['bridge'] = ''
                return_info['vif'].append(virtual_interface)
        except AttributeError as excep:
            LOG.error("Attribute error while getting disk and mac info %s" % excep)
            return {}
    return return_info
