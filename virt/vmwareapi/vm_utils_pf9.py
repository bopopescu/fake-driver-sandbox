# vim: tabstop=6 shiftwidth=4 softtabstop=4
# Copyright (c) 2014 Platform9 Systems Inc.

"""
Implements get_instance_info and related functions which are used in
instance discovery for vmware ESX/vCenter
"""
from datetime import timedelta, datetime
from oslo_vmware import exceptions as vexc
from oslo_config import cfg
from netaddr import IPAddress
from nova import exception
from oslo_log import log as logging
from oslo_vmware import vim_util as oslo_vutil
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.compute import power_state
from nova.virt import resource_types
from nova.virt.vmwareapi import vm_queries_pf9

import nova.virt
import vmops
import host_statistics_pf9

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

# local cache of uuid->vm_ref
# Reason for keeping this cache in this file and not in driver is to make this
# cache accessible to calls from vmops.py
_vm_cache = dict()
_cache_refresh_interval = timedelta(minutes=10)
_last_cache_clear_time = None

# partial discovery IAAS-3987:
# for get_network_information_from_vcenter. This is cached as the function
# may be called as often as once per minute, straining vCenter.
_network_vm_cache = None

change_units = {
    # CPU and memory usage percentages are already in correct format
    resource_types.CPU: lambda val: val,
    resource_types.MEMORY: lambda val: val,

    # Total packets send in 1000s of packets
    resource_types.NETWORK_SENT_PKTS: lambda val: val / 1000.0,
    resource_types.NETWORK_RECV_PKTS: lambda val: val / 1000.0,

    # network rates reported as KBPS, converting to MBPS
    resource_types.NETWORK_SEND_RATE: lambda val: val / 1000.0,
    resource_types.NETWORK_RECV_RATE: lambda val: val / 1000.0,

    # Disk capacity reported in bytes, converting to GB
    resource_types.DISK_USED: lambda val: 1.0 * val / 1024 ** 3,
    resource_types.DISK_TOTAL: lambda val: 1.0 * val / 1024 ** 3
}

vmware_to_resource_type = {
    'mem.usage.average': resource_types.MEMORY,
    'cpu.usage.average': resource_types.CPU,
    'net.received.average': resource_types.NETWORK_RECV_RATE,
    'net.transmitted.average': resource_types.NETWORK_SEND_RATE,
    'net.packetsRx.summation': resource_types.NETWORK_RECV_PKTS,
    'net.packetsTx.summation': resource_types.NETWORK_SENT_PKTS,
    'disk.usage': resource_types.DISK_USED,
    'disk.capacity': resource_types.DISK_TOTAL
}

resource_type_to_vmware = {
    resource_types.MEMORY: 'mem.usage.average',
    resource_types.CPU: 'cpu.usage.average',
    resource_types.NETWORK_RECV_RATE: 'net.received.average',
    resource_types.NETWORK_SEND_RATE: 'net.transmitted.average',
    resource_types.NETWORK_RECV_PKTS: 'net.packetsRx.summation',
    resource_types.NETWORK_SENT_PKTS: 'net.packetsTx.summation',
    resource_types.DISK_USED: 'disk.usage',
    resource_types.DISK_TOTAL: 'disk.capacity'
}

resources_available_at_respool = [
    resource_types.CPU,
    resource_types.MEMORY
]


def get_hostname(driver):
    host_objs = driver._session._call_method(vim_util, "get_objects",
                                             "HostSystem", ["name"])
    host = None
    if host_objs:
        for host_obj in host_objs.objects:
            host = host_obj.obj
            break

    return driver._session._call_method(oslo_vutil, "get_object_property",
                                        host, "name")


def get_all_ip_addr(driver):
    return [{'interface_name': "vCenter IP",
            'ip': driver._host_ip}]


def get_host_stats_esx(driver, res_types):
    """
    Return currently known physical resource consumption
    :param res_types: An array of resources to be queried
    """
    res_to_be_queried = [resource_type_to_vmware[x] for x in res_types]

    host_objs = driver._session._call_method(vim_util, "get_objects",
                                             "HostSystem", ["name"])
    # ESX will have only 1 host
    host = host_objs.objects[0].obj

    # Get information from all performance counters
    reqd_counter_information = driver._session._call_method(
        vim_util, "get_esx_properties_pf9", host, res_to_be_queried, None)
    return _get_stats_from_vmw_stats(reqd_counter_information)


def get_host_stats_vc(driver, res_types, node_name):
    """
    Return aggregated stats for the given node (cluster)
    """
    cluster_mor = driver._cluster_ref
    data_store_refs = _get_datastores_for_cluster(driver, cluster_mor, driver._datastore_regex)

    # Commenting the code so as to make sure we remove get_vc_properties_pf9
    # from vim_util when cleaning up this file as a part of IAAS-1778
    # get hosts under the VC
    #hosts = []
    #host_objs = driver._session._call_method(vim_util, "get_objects",
    #                                         "HostSystem", ["name"])
    #for host_obj in host_objs.objects:
    #    hosts.append(host_obj.obj)

    #vc_stats = driver._session._call_method(
    #    vim_util, "get_vc_properties_pf9", res_pools, data_store_refs, hosts, res_types, None)

    vc_stats = {}
    # Net stats are not being used currently, also we are currently avoiding
    # the use of performance manager to get network stats since it is quite
    # resource and time consuming.
    # TODO: Revisit the performance manager logic to fetch network statistics
    # FIXME: IAAS-1875
    vc_stats['net.transmitted.average'] = 0
    vc_stats['net.received.average'] = 0
    vc_stats['net.packetsRx.summation'] = 0
    vc_stats['net.packetsTx.summation'] = 0
    datastore_stats = host_statistics_pf9.get_datastore_usage_stats(
        driver._session, data_store_refs)
    cluster_stats = host_statistics_pf9.get_cluster_usage_and_percentage(
        driver._session, cluster_mor)
    vc_stats['cpu.usage.average'] = 0 if cluster_stats['total_cpu'] == 0 else \
            cluster_stats['used_cpu'] * 100.0 / cluster_stats['total_cpu']
    vc_stats['mem.usage.average'] = 0 if cluster_stats['total_memory'] == 0 else \
            cluster_stats['used_memory'] * 100.0 / cluster_stats['total_memory']
    vc_stats['disk.capacity'] = datastore_stats['total_capacity']
    vc_stats['disk.usage'] = datastore_stats['total_used']

    return _get_stats_from_vmw_stats(vc_stats)


def _get_stats_from_vmw_stats(stats):
    keys = stats.keys()
    return_stats = dict()
    for key in keys:
        val = stats.get(key)
        return_stats[vmware_to_resource_type[key]] = \
            _get_avg(vmware_to_resource_type[key], val)
    return return_stats


def _get_avg(key, values):
    if not isinstance(values, list):
        values = [values]
    total = sum(values)
    total = 1.0 * total / len(values)
    return change_units[key](total)


def get_all_networks(driver):
    """
    Gets a mapping of IP addresses, MAC addresses and networks connected
    """
    network_list = []
    datacenter_refs = []
    all_networks = []
    datacenters = driver._session._call_method(
        vim_util, "get_objects", "Datacenter", ["name"])
    for datacenter in datacenters.objects:
        datacenter_refs.append(datacenter.obj)

    for datacenter_ref in datacenter_refs:
        all_networks.append(driver._session._call_method(
            oslo_vutil, "get_object_property",
            datacenter_ref, "network"))

    for dc_specific_network in all_networks:
        # In cases where the datacenter has no networks, the previous driver call returns
        # an empty array element. Wrap in try-catch to allow for such cases, and continue
        try:
            for network in dc_specific_network[0]:
                if network['_type'] == "Network":
                    network_name = driver._session._call_method(
                        oslo_vutil, "get_object_property",
                        network, "name")
                    #TODO: network uuid needs to maintained along with names to
                    #      differentiate between them
                    if {'bridge': network_name} not in network_list:
                        network_list.append({'bridge': network_name})
                else:
                    LOG.info("Ignoring network having [%s] type" %
                             network['_type'])
        except IndexError:
            LOG.info("Encountered a datacenter with no associated network, ignoring")

    return network_list


def get_all_cluster_networks(driver, node=None):
    """
    Gets a list of all networks connected to the authorized clusters
    """
    network_moids = set()
    network_list = []

    assert isinstance(driver, nova.virt.vmwareapi.VMwareVCDriver)

    cluster_mors = [driver._cluster_ref]
    for cluster_mor in cluster_mors:
        network_mors = driver._session._call_method(oslo_vutil,
                                                    "get_object_property",
                                                    cluster_mor, "network")
        if not network_mors:
            LOG.warn("No networks detected under {cls_mor} cluster".format(
                cls_mor=str(cluster_mor)))
            return network_list
        for network_mor in network_mors.ManagedObjectReference:
            if not network_mor.value in network_moids:
                network_moids.add(network_mor.value)
                network_name = driver._session._call_method(
                    oslo_vutil, "get_object_property",
                    network_mor, "name")
                network_list.append({'bridge': network_name})

    return network_list


# NOT USED
def get_all_ip_mappings(driver):
    vm_network_info = dict()
    all_vms = _get_vms_and_uuids(driver)
    vm_id_ref = dict()

    for vm in all_vms.objects:
        for prop in vm.propSet:
            if prop.name == "summary.config.instanceUuid":
                vm_id_ref[prop.val] = vm.obj

    for (uuid, vm_ref) in vm_id_ref.items():
        # TODO: IAAS-763
        guest_nics_info = driver._session._call_method(
            oslo_vutil, "get_object_property", vm_ref, "guest.net")
        if guest_nics_info:
            for nic_info in guest_nics_info.GuestNicInfo:
                ip_addresses = nic_info['ipAddress'] \
                    if hasattr(nic_info, 'ipAddress') else None
                mac_address = nic_info['macAddress'] \
                    if hasattr(nic_info, 'macAddress')else None
                network_name = nic_info['network'] \
                    if hasattr(nic_info, 'network') else None
                if not vm_network_info.get(uuid):
                    vm_network_info[uuid] = []
                # select ipv4 if available, otherwise select first ip present
                ip_address = None
                if ip_addresses is not None:
                    for ip in ip_addresses:
                        if ip.find(":") == -1:
                            ip_address = ip
                            break
                    if ip_address is None:
                        ip_address = ip_addresses[0]

                vm_network_info[uuid].append({'ip_address': ip_address,
                                       'mac_address': mac_address,
                                       'bridge': network_name})
        else:
            vm_network_info[uuid] = []
    return vm_network_info


def get_vms_on_vcenter(driver, node=None):
    """
    Generator for getting all VMs that are of interest to the driver.
    The VMs returned by this method are already filtered based on datastore and
        cluster they belong to.
    The VM object returned contains the vm ref alongwith following properties -
        1. name
        2. runtime.connectionState
        3. summary.config.vmPathName
        4. summary.config.instanceUuid
        5. resourcePool
        6. parent
    How to use this function for getting other properties -
        for vm in get_all_vms_on_vcenter(driver):
            vm_ref = vm.obj
            # Use vm_ref to call get_dynamic_properties and
            # get other properties as needed
    Note:
    1. This method will return templates as well
    2. to get properties listed above you need to iterate over vm.propSet
    3. This method will return **NOT** any VM that are under the folders
       specified in ignore_folders in nova.conf
    """
    global _vm_cache
    folder_ref_name = dict()
    res_pools_to_look_for = [x.value for x in vm_queries_pf9._get_res_pool_obj_list(driver, node)]
    folders_to_ignore = [x.strip() for x in CONF.PF9.ignore_folders.split(',')]
    for vm in vm_queries_pf9._get_all_vms(driver):
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
            _vm_cache[uuid] = vm.obj
            yield vm
        else:
            if resource_pool and resource_pool in res_pools_to_look_for:
                _vm_cache[uuid] = vm.obj
                yield vm


def list_instance_uuids_on_vcenter(driver, node=None, template_uuids=None):
    """
    All list functions need to call the vsphere APIs since the information
    returned by list functions should always be in sync with hypervisor.
    local cache will be refreshed in this call.
    Note: Parameter template_uuids if not None, will be populated with the
    template UUIDs returned by vcenter. If None, templates will be skipped.
    """
    global _vm_cache
    global _last_cache_clear_time
    global _cache_refresh_interval
    current_time = datetime.now()
    if _last_cache_clear_time is None \
            or current_time - _last_cache_clear_time >= _cache_refresh_interval:
        # to prevent subsequent calls for VMs on multiple nodes from
        # clearing the cache
        _vm_cache.clear()
        _last_cache_clear_time = datetime.now()
    uuid_list = []
    for vm in get_vms_on_vcenter(driver, node):
        uuid = None
        path = None
        for prop in vm.propSet:
            if prop.name == "summary.config.instanceUuid":
                uuid = prop.val
            elif prop.name == "summary.config.vmPathName":
                path = prop.val
            if uuid and path:
                break
        if path[-4:] == 'vmtx':
            if template_uuids is not None:
                template_uuids.append(uuid)
        else:
            uuid_list.append(uuid)
    return uuid_list


def _get_res_pools_for_cluster(driver, cluster_name):
    """
    Gets all the resource pools belonging to the given cluster
    """
    res_pools = []
    res_pool_objects = driver._session._call_method(vim_util, "get_objects",
                                                    "ResourcePool", ['owner'])

    for res_pool_obj in res_pool_objects.objects:
        for prop in res_pool_obj.propSet:
            if prop.name == 'owner' and prop.val.value in cluster_name:
                res_pools.append(res_pool_obj.obj)

    return res_pools


def _get_datastores_for_cluster(driver, cluster_mor, datastore_regex):
    """
    Gets all the datastores associated with the given custer that match
    the datastore regex
    """
    datastore_ret = driver._session._call_method(
            oslo_vutil, "get_object_property", cluster_mor, "datastore")
    if not datastore_ret:
        return []
    data_stores = driver._session._call_method(
            vim_util, "get_properties_for_a_collection_of_objects",
            "Datastore", datastore_ret.ManagedObjectReference,
            ["summary.name"])

    data_store_refs = []
    for obj_content in data_stores.objects:
        propdict = vm_util.propset_dict(obj_content.propSet)
        if datastore_regex is None or \
                datastore_regex.match(propdict['summary.name']):
            data_store_refs.append(obj_content.obj)

    return data_store_refs


def _get_vms_and_uuids(driver):
    """
    Get the VM object reference along with name and UUID for all the VMs
    associated with given connection object(driver)
    """
    return driver._session._call_method(
            vim_util, "get_objects", "VirtualMachine",
            ["name", "summary.config.instanceUuid"])
