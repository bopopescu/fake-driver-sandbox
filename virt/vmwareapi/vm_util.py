# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
The VMware API VM utility module to build SOAP object specs.
"""

import collections
import copy
import functools
# PF9 import
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import pbm
from oslo_vmware import vim_util as vutil
import six
# PF9 import
import host_statistics_pf9
from netaddr import IPAddress

from nova import exception
from nova.i18n import _, _LE, _LI, _LW
from nova.network import model as network_model
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import vim_util
# PF9 import
from nova.virt.vmwareapi import vm_queries_pf9
import datetime

LOG = logging.getLogger(__name__)

vmware_utils_opts = [
    cfg.IntOpt('console_delay_seconds',
               help='Set this value if affected by an increased network '
                    'latency causing repeated characters when typing in '
                    'a remote console.'),
    cfg.StrOpt('serial_port_service_uri',
               help='Identifies the remote system that serial port traffic '
                    'will be sent to. If this is not set, no serial ports '
                    'will be added to the created VMs.'),
    cfg.StrOpt('serial_port_proxy_uri',
               help='Identifies a proxy service that provides network access '
                    'to the serial_port_service_uri. This option is ignored '
                    'if serial_port_service_uri is not specified.'),
    ]

CONF = cfg.CONF
CONF.register_opts(vmware_utils_opts, 'vmware')

ALL_SUPPORTED_NETWORK_DEVICES = ['VirtualE1000', 'VirtualE1000e',
                                 'VirtualPCNet32', 'VirtualSriovEthernetCard',
                                 'VirtualVmxnet', 'VirtualVmxnet3']

# A cache for VM references. The key will be the VM name
# and the value is the VM reference. The VM name is unique. This
# is either the UUID of the instance or UUID-rescue in the case
# that this is a rescue VM. This is in order to prevent
# unnecessary communication with the backend.
_VM_REFS_CACHE = {}
last_refresh = None
refresh_interval = 5
chunk_size = 100
EXTENSION_REGISTERED = False


class Limits(object):

    def __init__(self, limit=None, reservation=None,
                 shares_level=None, shares_share=None):
        """imits object holds instance limits for convenience."""
        self.limit = limit
        self.reservation = reservation
        self.shares_level = shares_level
        self.shares_share = shares_share

    def validate(self):
        if self.shares_level in ('high', 'normal', 'low'):
            if self.shares_share:
                reason = _("Share level '%s' cannot have share "
                           "configured") % self.shares_level
                raise exception.InvalidInput(reason=reason)
            return
        if self.shares_level == 'custom':
            return
        if self.shares_level:
            reason = _("Share '%s' is not supported") % self.shares_level
            raise exception.InvalidInput(reason=reason)

    def has_limits(self):
        return bool(self.limit or
                    self.reservation or
                    self.shares_level)


class ExtraSpecs(object):

    def __init__(self, cpu_limits=None, hw_version=None,
                 storage_policy=None, cores_per_socket=None,
                 memory_limits=None, disk_io_limits=None):
        """ExtraSpecs object holds extra_specs for the instance."""
        if cpu_limits is None:
            cpu_limits = Limits()
        self.cpu_limits = cpu_limits
        if memory_limits is None:
            memory_limits = Limits()
        self.memory_limits = memory_limits
        if disk_io_limits is None:
            disk_io_limits = Limits()
        self.disk_io_limits = disk_io_limits
        self.hw_version = hw_version
        self.storage_policy = storage_policy
        self.cores_per_socket = cores_per_socket


def vm_refs_cache_reset():
    global _VM_REFS_CACHE
    _VM_REFS_CACHE = {}


def vm_ref_cache_delete(id):
    _VM_REFS_CACHE.pop(id, None)


def vm_ref_cache_update(id, vm_ref):
    _VM_REFS_CACHE[id] = vm_ref


def vm_ref_cache_get(id):
    return _VM_REFS_CACHE.get(id)


def _vm_ref_cache(id, func, session, data):
    vm_ref = vm_ref_cache_get(id)
    if vm_ref and 'vmref' in vm_ref:
        return vm_ref['vmref']
    else:
        vm_ref = func(session, data)
        if vm_ref:
            add_vm_to_cache(session, id, {'vmref': vm_ref, "template": "false"})
            return vm_ref


def vm_ref_cache_from_instance(func):
    @functools.wraps(func)
    def wrapper(session, instance):
        # PF9 change to handle get_vm_ref being called with {"uuid": <uuid>}
        # from PF9 functions that work on just UUIDs
        if isinstance(instance, dict):
            id = instance['uuid']
        else:
            id = instance.uuid
        return _vm_ref_cache(id, func, session, instance)
    return wrapper


def vm_ref_cache_from_name(func):
    @functools.wraps(func)
    def wrapper(session, name):
        id = name
        return _vm_ref_cache(id, func, session, name)
    return wrapper

# the config key which stores the VNC port
VNC_CONFIG_KEY = 'config.extraConfig["RemoteDisplay.vnc.port"]'

VmdkInfo = collections.namedtuple('VmdkInfo', ['path', 'adapter_type',
                                               'disk_type',
                                               'capacity_in_bytes',
                                               'device'])


def _iface_id_option_value(client_factory, iface_id, port_index):
    opt = client_factory.create('ns0:OptionValue')
    # PF9: handle port_index being None
    if port_index is not None:
        opt.key = "nvp.iface-id.%d" % port_index
    else:
        opt.key = "nvp.iface-id"
    opt.value = iface_id
    return opt


def _get_allocation_info(client_factory, limits, allocation_type):
    allocation = client_factory.create(allocation_type)
    if limits.limit:
        allocation.limit = limits.limit
    else:
        # Set as 'umlimited'
        allocation.limit = -1
    if limits.reservation:
        allocation.reservation = limits.reservation
    else:
        allocation.reservation = 0
    shares = client_factory.create('ns0:SharesInfo')
    if limits.shares_level:
        shares.level = limits.shares_level
        if (shares.level == 'custom' and
            limits.shares_share):
            shares.shares = limits.shares_share
        else:
            shares.shares = 0
    else:
        shares.level = 'normal'
        shares.shares = 0
    allocation.shares = shares
    return allocation


def get_vm_create_spec(client_factory, instance, data_store_name,
                       vif_infos, extra_specs,
                       os_type=constants.DEFAULT_OS_TYPE,
                       profile_spec=None, metadata=None):
    """Builds the VM Create spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    # PF9: Change the name of VM
    vm_name = instance.get('hostname', None)
    if vm_name:
        # In case of snapshotting to template id is not present. Also we do not
        # want to name the snapshot template any different from the name
        # provided by the user.
        uid = "-%s" % instance.get('id') if instance.get('id') else ''
        vm_name = '{name}{uid}'.format(name=vm_name, uid=uid)
    else:
        vm_name = instance.uuid
    config_spec.name = vm_name
    # PF9: End
    config_spec.guestId = os_type
    # The name is the unique identifier for the VM.
    config_spec.instanceUuid = instance.uuid
    if metadata:
        config_spec.annotation = metadata
    # set the Hardware version
    config_spec.version = extra_specs.hw_version

    # Allow nested hypervisor instances to host 64 bit VMs.
    if os_type in ("vmkernel5Guest", "vmkernel6Guest", "windowsHyperVGuest"):
        config_spec.nestedHVEnabled = "True"

    # Append the profile spec
    if profile_spec:
        config_spec.vmProfile = [profile_spec]

    vm_file_info = client_factory.create('ns0:VirtualMachineFileInfo')
    vm_file_info.vmPathName = "[" + data_store_name + "]"
    config_spec.files = vm_file_info

    tools_info = client_factory.create('ns0:ToolsConfigInfo')
    tools_info.afterPowerOn = True
    tools_info.afterResume = True
    tools_info.beforeGuestStandby = True
    tools_info.beforeGuestShutdown = True
    tools_info.beforeGuestReboot = True

    config_spec.tools = tools_info
    config_spec.numCPUs = int(instance.vcpus)
    if extra_specs.cores_per_socket:
        config_spec.numCoresPerSocket = int(extra_specs.cores_per_socket)
    config_spec.memoryMB = int(instance.memory_mb)

    # Configure cpu information
    if extra_specs.cpu_limits.has_limits():
        config_spec.cpuAllocation = _get_allocation_info(
            client_factory, extra_specs.cpu_limits,
            'ns0:ResourceAllocationInfo')

    # Configure memory information
    if extra_specs.memory_limits.has_limits():
        config_spec.memoryAllocation = _get_allocation_info(
            client_factory, extra_specs.memory_limits,
            'ns0:ResourceAllocationInfo')

    devices = []
    for vif_info in vif_infos:
        vif_spec = _create_vif_spec(client_factory, vif_info)
        devices.append(vif_spec)

    serial_port_spec = create_serial_port_spec(client_factory)
    if serial_port_spec:
        devices.append(serial_port_spec)

    config_spec.deviceChange = devices

    # add vm-uuid and iface-id.x values for Neutron
    extra_config = []
    opt = client_factory.create('ns0:OptionValue')
    opt.key = "nvp.vm-uuid"
    opt.value = instance.uuid
    extra_config.append(opt)

    port_index = 0
    for vif_info in vif_infos:
        if vif_info['iface_id']:
            extra_config.append(_iface_id_option_value(client_factory,
                                                       vif_info['iface_id'],
                                                       port_index))
            port_index += 1

    if (CONF.vmware.console_delay_seconds and
        CONF.vmware.console_delay_seconds > 0):
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'keyboard.typematicMinDelay'
        opt.value = CONF.vmware.console_delay_seconds * 1000000
        extra_config.append(opt)

    config_spec.extraConfig = extra_config

    # Set the VM to be 'managed' by 'OpenStack'
    # PF9: check if extension was registered
    if EXTENSION_REGISTERED:
        managed_by = client_factory.create('ns0:ManagedByInfo')
        managed_by.extensionKey = constants.PF9_EXTENSION_KEY
        managed_by.type = constants.EXTENSION_TYPE_INSTANCE
        config_spec.managedBy = managed_by

    return config_spec


def create_serial_port_spec(client_factory):
    """Creates config spec for serial port."""
    if not CONF.vmware.serial_port_service_uri:
        return

    backing = client_factory.create('ns0:VirtualSerialPortURIBackingInfo')
    backing.direction = "server"
    backing.serviceURI = CONF.vmware.serial_port_service_uri
    backing.proxyURI = CONF.vmware.serial_port_proxy_uri

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = True
    connectable_spec.connected = True

    serial_port = client_factory.create('ns0:VirtualSerialPort')
    serial_port.connectable = connectable_spec
    serial_port.backing = backing
    # we are using unique negative integers as temporary keys
    serial_port.key = -2
    serial_port.yieldOnPoll = True
    dev_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    dev_spec.operation = "add"
    dev_spec.device = serial_port
    return dev_spec


def get_vm_boot_spec(client_factory, device):
    """Returns updated boot settings for the instance.

    The boot order for the instance will be changed to have the
    input device as the boot disk.
    """
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    boot_disk = client_factory.create(
        'ns0:VirtualMachineBootOptionsBootableDiskDevice')
    boot_disk.deviceKey = device.key
    boot_options = client_factory.create('ns0:VirtualMachineBootOptions')
    boot_options.bootOrder = [boot_disk]
    config_spec.bootOptions = boot_options
    return config_spec


def get_vm_resize_spec(client_factory, vcpus, memory_mb, extra_specs,
                       metadata=None):
    """Provides updates for a VM spec."""
    resize_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    resize_spec.numCPUs = vcpus
    resize_spec.memoryMB = memory_mb
    resize_spec.cpuAllocation = _get_allocation_info(
        client_factory, extra_specs.cpu_limits,
        'ns0:ResourceAllocationInfo')
    if metadata:
        resize_spec.annotation = metadata
    return resize_spec


def create_controller_spec(client_factory, key,
                           adapter_type=constants.DEFAULT_ADAPTER_TYPE):
    """Builds a Config Spec for the LSI or Bus Logic Controller's addition
    which acts as the controller for the virtual hard disk to be attached
    to the VM.
    """
    # Create a controller for the Virtual Hard Disk
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if adapter_type == constants.ADAPTER_TYPE_BUSLOGIC:
        virtual_controller = client_factory.create(
                                'ns0:VirtualBusLogicController')
    elif adapter_type == constants.ADAPTER_TYPE_LSILOGICSAS:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicSASController')
    elif adapter_type == constants.ADAPTER_TYPE_PARAVIRTUAL:
        virtual_controller = client_factory.create(
                                'ns0:ParaVirtualSCSIController')
    else:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicController')
    virtual_controller.key = key
    virtual_controller.busNumber = 0
    virtual_controller.sharedBus = "noSharing"
    virtual_device_config.device = virtual_controller
    return virtual_device_config


def convert_vif_model(name):
    """Converts standard VIF_MODEL types to the internal VMware ones."""
    if name == network_model.VIF_MODEL_E1000:
        return 'VirtualE1000'
    if name == network_model.VIF_MODEL_E1000E:
        return 'VirtualE1000e'
    if name == network_model.VIF_MODEL_PCNET:
        return 'VirtualPCNet32'
    if name == network_model.VIF_MODEL_SRIOV:
        return 'VirtualSriovEthernetCard'
    if name == network_model.VIF_MODEL_VMXNET:
        return 'VirtualVmxnet'
    if name == network_model.VIF_MODEL_VMXNET3:
        return 'VirtualVmxnet3'
    if name not in ALL_SUPPORTED_NETWORK_DEVICES:
        msg = _('%s is not supported.') % name
        raise exception.Invalid(msg)
    return name


def _create_vif_spec(client_factory, vif_info):
    """Builds a config spec for the addition of a new network
    adapter to the VM.
    """
    network_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    network_spec.operation = "add"

    # Keep compatible with other Hyper vif model parameter.
    vif_info['vif_model'] = convert_vif_model(vif_info['vif_model'])

    vif = 'ns0:' + vif_info['vif_model']
    net_device = client_factory.create(vif)

    # NOTE(asomya): Only works on ESXi if the portgroup binding is set to
    # ephemeral. Invalid configuration if set to static and the NIC does
    # not come up on boot if set to dynamic.
    network_ref = vif_info['network_ref']
    network_name = vif_info['network_name']
    mac_address = vif_info['mac_address']
    backing = None
    if network_ref and network_ref['type'] == 'OpaqueNetwork':
        backing = client_factory.create(
                'ns0:VirtualEthernetCardOpaqueNetworkBackingInfo')
        backing.opaqueNetworkId = network_ref['network-id']
        backing.opaqueNetworkType = network_ref['network-type']
    elif (network_ref and
            network_ref['type'] == "DistributedVirtualPortgroup"):
        backing = client_factory.create(
                'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
        portgroup = client_factory.create(
                    'ns0:DistributedVirtualSwitchPortConnection')
        portgroup.switchUuid = network_ref['dvsw']
        portgroup.portgroupKey = network_ref['dvpg']
        backing.port = portgroup
    else:
        backing = client_factory.create(
                  'ns0:VirtualEthernetCardNetworkBackingInfo')
        backing.deviceName = network_name

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = True
    connectable_spec.connected = True

    net_device.connectable = connectable_spec
    net_device.backing = backing

    # The Server assigns a Key to the device. Here we pass a -ve temporary key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    net_device.key = -47
    net_device.addressType = "manual"
    net_device.macAddress = mac_address
    net_device.wakeOnLanEnabled = True

    network_spec.device = net_device
    return network_spec


def get_network_attach_config_spec(client_factory, vif_info, index):
    """Builds the vif attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    vif_spec = _create_vif_spec(client_factory, vif_info)
    config_spec.deviceChange = [vif_spec]
    if vif_info['iface_id'] is not None:
        config_spec.extraConfig = [_iface_id_option_value(client_factory,
                                                          vif_info['iface_id'],
                                                          index)]
    return config_spec


def get_network_detach_config_spec(client_factory, device, port_index):
    """Builds the vif detach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "remove"
    virtual_device_config.device = device
    config_spec.deviceChange = [virtual_device_config]
    # If a key is already present then it cannot be deleted, only updated.
    # This enables us to reuse this key if there is an additional
    # attachment. The keys need to be preserved. This is due to the fact
    # that there is logic on the ESX that does the network wiring
    # according to these values. If they are changed then this will
    # break networking to and from the interface.
    config_spec.extraConfig = [_iface_id_option_value(client_factory,
                                                      'free',
                                                      port_index)]
    return config_spec


def get_storage_profile_spec(session, storage_policy):
    """Gets the vm profile spec configured for storage policy."""
    profile_id = pbm.get_profile_id_by_name(session, storage_policy)
    if profile_id:
        client_factory = session.vim.client.factory
        storage_profile_spec = client_factory.create(
            'ns0:VirtualMachineDefinedProfileSpec')
        storage_profile_spec.profileId = profile_id.uniqueId
        return storage_profile_spec


def get_vmdk_attach_config_spec(client_factory,
                                disk_type=constants.DEFAULT_DISK_TYPE,
                                file_path=None,
                                disk_size=None,
                                linked_clone=False,
                                controller_key=None,
                                unit_number=None,
                                device_name=None,
                                disk_io_limits=None):
    """Builds the vmdk attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    # PF9 change - need to explicitly set disk_size to long, else value can't
    # be parsed by vim
    if disk_size:
        disk_size = long(disk_size)
    # Pf9: End
    virtual_device_config_spec = _create_virtual_disk_spec(client_factory,
                                controller_key, disk_type, file_path,
                                disk_size, linked_clone,
                                unit_number, device_name, disk_io_limits)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_cdrom_attach_config_spec(client_factory,
                                 datastore,
                                 file_path,
                                 controller_key,
                                 cdrom_unit_number):
    """Builds and returns the cdrom attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = create_virtual_cdrom_spec(client_factory,
                                                           datastore,
                                                           controller_key,
                                                           file_path,
                                                           cdrom_unit_number)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vmdk_detach_config_spec(client_factory, device,
                                destroy_disk=False):
    """Builds the vmdk detach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = detach_virtual_disk_spec(client_factory,
                                                          device,
                                                          destroy_disk)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vm_extra_config_spec(client_factory, extra_opts):
    """Builds extra spec fields from a dictionary."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    # add the key value pairs
    extra_config = []
    for key, value in six.iteritems(extra_opts):
        opt = client_factory.create('ns0:OptionValue')
        opt.key = key
        opt.value = value
        extra_config.append(opt)
        config_spec.extraConfig = extra_config
    return config_spec


def _get_device_capacity(device):
    # Devices pre-vSphere-5.5 only reports capacityInKB, which has
    # rounding inaccuracies. Use that only if the more accurate
    # attribute is absent.
    if hasattr(device, 'capacityInBytes'):
        return device.capacityInBytes
    else:
        return device.capacityInKB * units.Ki


def _get_device_disk_type(device):
    if getattr(device.backing, 'thinProvisioned', False):
        return constants.DISK_TYPE_THIN
    else:
        if getattr(device.backing, 'eagerlyScrub', False):
            return constants.DISK_TYPE_EAGER_ZEROED_THICK
        else:
            return constants.DEFAULT_DISK_TYPE


def get_vmdk_info(session, vm_ref, uuid=None):
    """Returns information for the primary VMDK attached to the given VM."""
    hardware_devices = session._call_method(vutil,
                                            "get_object_property",
                                            vm_ref,
                                            "config.hardware.device")
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice
    vmdk_file_path = None
    vmdk_controller_key = None
    disk_type = None
    capacity_in_bytes = 0

    # Determine if we need to get the details of the root disk
    root_disk = None
    root_device = None
    if uuid:
        root_disk = '%s.vmdk' % uuid
    vmdk_device = None

    adapter_type_dict = {}
    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if device.backing.__class__.__name__ == \
                    "VirtualDiskFlatVer2BackingInfo":
                path = ds_obj.DatastorePath.parse(device.backing.fileName)
                if root_disk and path.basename == root_disk:
                    root_device = device
                vmdk_device = device
        elif device.__class__.__name__ == "VirtualLsiLogicController":
            adapter_type_dict[device.key] = constants.DEFAULT_ADAPTER_TYPE
        elif device.__class__.__name__ == "VirtualBusLogicController":
            adapter_type_dict[device.key] = constants.ADAPTER_TYPE_BUSLOGIC
        elif device.__class__.__name__ == "VirtualIDEController":
            adapter_type_dict[device.key] = constants.ADAPTER_TYPE_IDE
        elif device.__class__.__name__ == "VirtualLsiLogicSASController":
            adapter_type_dict[device.key] = constants.ADAPTER_TYPE_LSILOGICSAS
        elif device.__class__.__name__ == "ParaVirtualSCSIController":
            adapter_type_dict[device.key] = constants.ADAPTER_TYPE_PARAVIRTUAL

    if root_disk:
        vmdk_device = root_device

    if vmdk_device:
        vmdk_file_path = vmdk_device.backing.fileName
        capacity_in_bytes = _get_device_capacity(vmdk_device)
        vmdk_controller_key = vmdk_device.controllerKey
        disk_type = _get_device_disk_type(vmdk_device)

    adapter_type = adapter_type_dict.get(vmdk_controller_key)
    return VmdkInfo(vmdk_file_path, adapter_type, disk_type,
                    capacity_in_bytes, vmdk_device)


scsi_controller_classes = {
    'ParaVirtualSCSIController': constants.ADAPTER_TYPE_PARAVIRTUAL,
    'VirtualLsiLogicController': constants.DEFAULT_ADAPTER_TYPE,
    'VirtualLsiLogicSASController': constants.ADAPTER_TYPE_LSILOGICSAS,
    'VirtualBusLogicController': constants.ADAPTER_TYPE_PARAVIRTUAL,
}


def get_scsi_adapter_type(hardware_devices):
    """Selects a proper iscsi adapter type from the existing
       hardware devices
    """
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if device.__class__.__name__ in scsi_controller_classes:
            # find the controllers which still have available slots
            if len(device.device) < constants.SCSI_MAX_CONNECT_NUMBER:
                # return the first match one
                return scsi_controller_classes[device.__class__.__name__]
    raise exception.StorageError(
        reason=_("Unable to find iSCSI Target"))


def _find_controller_slot(controller_keys, taken, max_unit_number):
    for controller_key in controller_keys:
        for unit_number in range(max_unit_number):
            if unit_number not in taken.get(controller_key, []):
                return controller_key, unit_number


def _is_ide_controller(device):
    return device.__class__.__name__ == 'VirtualIDEController'


def _is_scsi_controller(device):
    return device.__class__.__name__ in ['VirtualLsiLogicController',
                                         'VirtualLsiLogicSASController',
                                         'VirtualBusLogicController',
                                         'ParaVirtualSCSIController']


def _find_allocated_slots(devices):
    """Return dictionary which maps controller_key to list of allocated unit
    numbers for that controller_key.
    """
    taken = {}
    for device in devices:
        if hasattr(device, 'controllerKey') and hasattr(device, 'unitNumber'):
            unit_numbers = taken.setdefault(device.controllerKey, [])
            unit_numbers.append(device.unitNumber)
        if _is_scsi_controller(device):
            # the SCSI controller sits on its own bus
            unit_numbers = taken.setdefault(device.key, [])
            unit_numbers.append(device.scsiCtlrUnitNumber)
    return taken


def allocate_controller_key_and_unit_number(client_factory, devices,
                                            adapter_type):
    """This function inspects the current set of hardware devices and returns
    controller_key and unit_number that can be used for attaching a new virtual
    disk to adapter with the given adapter_type.
    """
    if devices.__class__.__name__ == "ArrayOfVirtualDevice":
        devices = devices.VirtualDevice

    taken = _find_allocated_slots(devices)

    ret = None
    if adapter_type == constants.ADAPTER_TYPE_IDE:
        ide_keys = [dev.key for dev in devices if _is_ide_controller(dev)]
        ret = _find_controller_slot(ide_keys, taken, 2)
    elif adapter_type in [constants.DEFAULT_ADAPTER_TYPE,
                          constants.ADAPTER_TYPE_LSILOGICSAS,
                          constants.ADAPTER_TYPE_BUSLOGIC,
                          constants.ADAPTER_TYPE_PARAVIRTUAL]:
        scsi_keys = [dev.key for dev in devices if _is_scsi_controller(dev)]
        ret = _find_controller_slot(scsi_keys, taken, 16)
    if ret:
        return ret[0], ret[1], None

    # create new controller with the specified type and return its spec
    controller_key = -101
    controller_spec = create_controller_spec(client_factory, controller_key,
                                             adapter_type)
    return controller_key, 0, controller_spec


def get_rdm_disk(hardware_devices, uuid):
    """Gets the RDM disk key."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
            device.backing.__class__.__name__ ==
                "VirtualDiskRawDiskMappingVer1BackingInfo" and
                device.backing.lunUuid == uuid):
            return device


def get_vmdk_create_spec(client_factory, size_in_kb,
                         adapter_type=constants.DEFAULT_ADAPTER_TYPE,
                         disk_type=constants.DEFAULT_DISK_TYPE):
    """Builds the virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:FileBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = get_vmdk_adapter_type(adapter_type)
    create_vmdk_spec.diskType = disk_type
    # Pf9 change - need to explicitly set to long, else value can't be parsed by vim
    create_vmdk_spec.capacityKb = long(size_in_kb)
    return create_vmdk_spec


def create_virtual_cdrom_spec(client_factory,
                              datastore,
                              controller_key,
                              file_path,
                              cdrom_unit_number):
    """Builds spec for the creation of a new Virtual CDROM to the VM."""
    config_spec = client_factory.create(
        'ns0:VirtualDeviceConfigSpec')
    config_spec.operation = "add"

    cdrom = client_factory.create('ns0:VirtualCdrom')

    cdrom_device_backing = client_factory.create(
        'ns0:VirtualCdromIsoBackingInfo')
    cdrom_device_backing.datastore = datastore
    cdrom_device_backing.fileName = file_path

    cdrom.backing = cdrom_device_backing
    cdrom.controllerKey = controller_key
    cdrom.unitNumber = cdrom_unit_number
    cdrom.key = -1

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = True

    cdrom.connectable = connectable_spec

    config_spec.device = cdrom
    return config_spec


def _create_virtual_disk_spec(client_factory, controller_key,
                              disk_type=constants.DEFAULT_DISK_TYPE,
                              file_path=None,
                              disk_size=None,
                              linked_clone=False,
                              unit_number=None,
                              device_name=None,
                              disk_io_limits=None):
    """Builds spec for the creation of a new/ attaching of an already existing
    Virtual Disk to the VM.
    """
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if (file_path is None) or linked_clone:
        virtual_device_config.fileOperation = "create"

    virtual_disk = client_factory.create('ns0:VirtualDisk')

    if disk_type == "rdm" or disk_type == "rdmp":
        disk_file_backing = client_factory.create(
                            'ns0:VirtualDiskRawDiskMappingVer1BackingInfo')
        disk_file_backing.compatibilityMode = "virtualMode" \
            if disk_type == "rdm" else "physicalMode"
        disk_file_backing.diskMode = "independent_persistent"
        disk_file_backing.deviceName = device_name or ""
    else:
        disk_file_backing = client_factory.create(
                            'ns0:VirtualDiskFlatVer2BackingInfo')
        disk_file_backing.diskMode = "persistent"
        if disk_type == constants.DISK_TYPE_THIN:
            disk_file_backing.thinProvisioned = True
        else:
            if disk_type == constants.DISK_TYPE_EAGER_ZEROED_THICK:
                disk_file_backing.eagerlyScrub = True
    disk_file_backing.fileName = file_path or ""

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = True

    if not linked_clone:
        virtual_disk.backing = disk_file_backing
    else:
        virtual_disk.backing = copy.copy(disk_file_backing)
        virtual_disk.backing.fileName = ""
        virtual_disk.backing.parent = disk_file_backing
    virtual_disk.connectable = connectable_spec

    # The Server assigns a Key to the device. Here we pass a -ve random key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    virtual_disk.key = -100
    virtual_disk.controllerKey = controller_key
    virtual_disk.unitNumber = unit_number or 0
    virtual_disk.capacityInKB = disk_size or 0

    if disk_io_limits and disk_io_limits.has_limits():
        virtual_disk.storageIOAllocation = _get_allocation_info(
            client_factory, disk_io_limits,
            'ns0:StorageIOAllocationInfo')

    virtual_device_config.device = virtual_disk

    return virtual_device_config


def detach_virtual_disk_spec(client_factory, device, destroy_disk=False):
    """Builds spec for the detach of an already existing Virtual Disk from VM.
    """
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "remove"
    if destroy_disk:
        virtual_device_config.fileOperation = "destroy"
    virtual_device_config.device = device

    return virtual_device_config


def clone_vm_spec(client_factory, location,
                  power_on=False, snapshot=None, template=False, config=None):
    """Builds the VM clone spec."""
    clone_spec = client_factory.create('ns0:VirtualMachineCloneSpec')
    clone_spec.location = location
    clone_spec.powerOn = power_on
    if snapshot:
        clone_spec.snapshot = snapshot
    if config is not None:
        clone_spec.config = config
    clone_spec.template = template
    return clone_spec


# PF9 Change add pool=None to the args for template support
def relocate_vm_spec(client_factory, datastore=None, host=None,
                     disk_move_type="moveAllDiskBackingsAndAllowSharing",
                     pool=None):
    """Builds the VM relocation spec."""
    rel_spec = client_factory.create('ns0:VirtualMachineRelocateSpec')
    rel_spec.datastore = datastore
    rel_spec.diskMoveType = disk_move_type
    if host:
        rel_spec.host = host
    # Set resource pools to support template cloning
    if pool:
        rel_spec.pool = pool
    return rel_spec


def get_machine_id_change_spec(client_factory, machine_id_str):
    """Builds the machine id change config spec."""
    virtual_machine_config_spec = client_factory.create(
                                  'ns0:VirtualMachineConfigSpec')

    opt = client_factory.create('ns0:OptionValue')
    opt.key = "machine.id"
    opt.value = machine_id_str
    virtual_machine_config_spec.extraConfig = [opt]
    return virtual_machine_config_spec


def get_add_vswitch_port_group_spec(client_factory, vswitch_name,
                                    port_group_name, vlan_id):
    """Builds the virtual switch port group add spec."""
    vswitch_port_group_spec = client_factory.create('ns0:HostPortGroupSpec')
    vswitch_port_group_spec.name = port_group_name
    vswitch_port_group_spec.vswitchName = vswitch_name

    # VLAN ID of 0 means that VLAN tagging is not to be done for the network.
    vswitch_port_group_spec.vlanId = int(vlan_id)

    policy = client_factory.create('ns0:HostNetworkPolicy')
    nicteaming = client_factory.create('ns0:HostNicTeamingPolicy')
    nicteaming.notifySwitches = True
    policy.nicTeaming = nicteaming

    vswitch_port_group_spec.policy = policy
    return vswitch_port_group_spec


def get_vnc_config_spec(client_factory, port):
    """Builds the vnc config spec."""
    virtual_machine_config_spec = client_factory.create(
                                    'ns0:VirtualMachineConfigSpec')

    opt_enabled = client_factory.create('ns0:OptionValue')
    opt_enabled.key = "RemoteDisplay.vnc.enabled"
    opt_enabled.value = "true"
    opt_port = client_factory.create('ns0:OptionValue')
    opt_port.key = "RemoteDisplay.vnc.port"
    opt_port.value = port
    opt_keymap = client_factory.create('ns0:OptionValue')
    opt_keymap.key = "RemoteDisplay.vnc.keyMap"
    opt_keymap.value = CONF.vnc.keymap

    extras = [opt_enabled, opt_port, opt_keymap]

    virtual_machine_config_spec.extraConfig = extras
    return virtual_machine_config_spec


def get_vnc_port(session):
    """Return VNC port for an VM or None if there is no available port."""
    min_port = CONF.vmware.vnc_port
    port_total = CONF.vmware.vnc_port_total
    allocated_ports = _get_allocated_vnc_ports(session)
    max_port = min_port + port_total
    for port in range(min_port, max_port):
        if port not in allocated_ports:
            return port
    raise exception.ConsolePortRangeExhausted(min_port=min_port,
                                              max_port=max_port)


def _get_allocated_vnc_ports(session):
    """Return an integer set of all allocated VNC ports."""
    # TODO(rgerganov): bug #1256944
    # The VNC port should be unique per host, not per vCenter
    vnc_ports = set()
    result = session._call_method(vim_util, "get_objects",
                                  "VirtualMachine", [VNC_CONFIG_KEY])
    while result:
        for obj in result.objects:
            if not hasattr(obj, 'propSet'):
                continue
            dynamic_prop = obj.propSet[0]
            option_value = dynamic_prop.val
            vnc_port = option_value.value
            vnc_ports.add(int(vnc_port))
        result = session._call_method(vutil, 'continue_retrieval',
                                      result)
    return vnc_ports


def _get_object_for_value(results, value):
    for object in results.objects:
        if object.propSet[0].val == value:
            return object.obj


def _get_object_for_optionvalue(results, value):
    for object in results.objects:
        if hasattr(object, "propSet") and object.propSet:
            # PF9 change - checking if propVal has 'value'
            propVal = object.propSet[0].val
            if hasattr(propVal, 'value'):
                if object.propSet[0].val.value == value:
                    return object.obj


def _get_object_from_results(session, results, value, func):
    while results:
        object = func(results, value)
        if object:
            session._call_method(vutil, 'cancel_retrieval',
                                 results)
            return object
        results = session._call_method(vutil, 'continue_retrieval',
                                       results)


def _get_vm_ref_from_name(session, vm_name):
    """Get reference to the VM with the name specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    return _get_object_from_results(session, vms, vm_name,
                                    _get_object_for_value)


@vm_ref_cache_from_name
def get_vm_ref_from_name(session, vm_name):
    return (_get_vm_ref_from_vm_uuid(session, vm_name) or
            _get_vm_ref_from_name(session, vm_name))


def _get_vm_ref_from_uuid(session, instance_uuid):
    """Get reference to the VM with the uuid specified.

    This method reads all of the names of the VM's that are running
    on the backend, then it filters locally the matching
    instance_uuid. It is far more optimal to use
    _get_vm_ref_from_vm_uuid.
    """
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    return _get_object_from_results(session, vms, instance_uuid,
                                    _get_object_for_value)


def _get_vm_ref_from_vm_uuid(session, instance_uuid):
    """Get reference to the VM.

    The method will make use of FindAllByUuid to get the VM reference.
    This method finds all VM's on the backend that match the
    instance_uuid, more specifically all VM's on the backend that have
    'config_spec.instanceUuid' set to 'instance_uuid'.
    """
    # PF9 change: New VM cache
    if session.__class__.__name__ == 'fake_driver':
        session = session._session
    # PF9: end
    vm_refs = session._call_method(
        session.vim,
        "FindAllByUuid",
        session.vim.service_content.searchIndex,
        uuid=instance_uuid,
        vmSearch=True,
        instanceUuid=True)
    if vm_refs:
        return vm_refs[0]


def _get_vm_ref_from_extraconfig(session, instance_uuid):
    """Get reference to the VM with the uuid specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ['config.extraConfig["nvp.vm-uuid"]'])
    return _get_object_from_results(session, vms, instance_uuid,
                                     _get_object_for_optionvalue)


@vm_ref_cache_from_instance
def get_vm_ref(session, instance):
    """Get reference to the VM through uuid or vm name."""
    # PF9: Some of the functions work purely on the UUID and will pass in a
    # dict like {"uuid": <uuid>} in place of instance object.
    # Handle those conditions here.
    if isinstance(instance, dict):
        uuid = instance['uuid']
    else:
        uuid = instance.uuid
    # Pf9 Change - not using "_get_vm_ref_from_name" IAAS-4149
    vm_ref = search_vm_ref_by_identifier(session, uuid)
    if vm_ref is None:
        raise exception.InstanceNotFound(instance_id=uuid)
    return vm_ref


def search_vm_ref_by_identifier(session, identifier):
    """Searches VM reference using the identifier.

    This method is primarily meant to separate out part of the logic for
    vm_ref search that could be use directly in the special case of
    migrating the instance. For querying VM linked to an instance always
    use get_vm_ref instead.
    """
    # Pf9 change - not using "_get_vm_ref_from_uuid" which gets all
    # VMs from vCenter
    vm_ref = (_get_vm_ref_from_vm_uuid(session, identifier) or
              _get_vm_ref_from_extraconfig(session, identifier))
    return vm_ref


def get_host_ref_for_vm(session, instance):
    """Get a MoRef to the ESXi host currently running an instance."""

    vm_ref = get_vm_ref(session, instance)
    return session._call_method(vutil, "get_object_property",
                                vm_ref, "runtime.host")


def get_host_name_for_vm(session, instance):
    """Get the hostname of the ESXi host currently running an instance."""

    host_ref = get_host_ref_for_vm(session, instance)
    return session._call_method(vutil, "get_object_property",
                                host_ref, "name")


def get_vm_state(session, instance):
    vm_ref = get_vm_ref(session, instance)
    vm_state = session._call_method(vutil, "get_object_property",
                                    vm_ref, "runtime.powerState")
    return vm_state


def get_stats_from_cluster(session, cluster):
    """Get the aggregate resource stats of a cluster."""
    vcpus = 0
    mem_info = {'total': 0, 'free': 0}
    # Get the Host and Resource Pool Managed Object Refs
    prop_dict = session._call_method(vutil,
                                     "get_object_properties_dict",
                                     cluster,
                                     ["host", "resourcePool"])
    if prop_dict:
        host_ret = prop_dict.get('host')
        if host_ret:
            host_mors = host_ret.ManagedObjectReference
            result = session._call_method(vim_util,
                         "get_properties_for_a_collection_of_objects",
                         "HostSystem", host_mors,
                         ["summary.hardware", "summary.runtime"])
            for obj in result.objects:
                hardware_summary = obj.propSet[0].val
                runtime_summary = obj.propSet[1].val
                if (runtime_summary.inMaintenanceMode is False and
                    runtime_summary.connectionState == "connected"):
                    # Total vcpus is the sum of all pCPUs of individual hosts
                    # The overcommitment ratio is factored in by the scheduler
                    vcpus += hardware_summary.numCpuThreads

        res_mor = prop_dict.get('resourcePool')
        if res_mor:
            res_usage = session._call_method(vutil, "get_object_property",
                                             res_mor, "summary.runtime.memory")
            if res_usage:
                # maxUsage is the memory limit of the cluster available to VM's
                mem_info['total'] = int(res_usage.maxUsage / units.Mi)
                # overallUsage is the hypervisor's view of memory usage by VM's
                consumed = int(res_usage.overallUsage / units.Mi)
                mem_info['free'] = mem_info['total'] - consumed
    stats = {'vcpus': vcpus, 'mem': mem_info}
    return stats

# PF9: start
def get_stats_from_cluster_pf9(session, cluster):
    """Get the aggregate resource stats of a cluster. This function is a
    modified version of function above i.e. get_stats_from_cluster.
    """
    # Return the cpu_info as it was being done in Juno
    cpu_info = {'vcpus': 0, 'cores': 0, 'sockets': 0, 'vendor': [], 'model': []}
    mem_info = {'total': 0, 'free': 0}
    # Get the Host and Resource Pool Managed Object Refs
    prop_dict = session._call_method(vutil,
                                     "get_object_properties_dict",
                                     cluster,
                                     ["host", "resourcePool"])
    if prop_dict:
        host_ret = prop_dict.get('host')
        if host_ret:
            host_mors = host_ret.ManagedObjectReference
            result = session._call_method(vim_util,
                         "get_properties_for_a_collection_of_objects",
                         "HostSystem", host_mors,
                         ["summary.hardware", "summary.runtime"])
            for obj in result.objects:
                hardware_summary = obj.propSet[0].val
                runtime_summary = obj.propSet[1].val
                if (runtime_summary.inMaintenanceMode is False and
                    runtime_summary.connectionState == "connected"):
                    # Total vcpus is the sum of all pCPUs of individual hosts
                    # The overcommitment ratio is factored in by the scheduler
                    cpu_info['vcpus'] += hardware_summary.numCpuThreads
                    cpu_info['cores'] += hardware_summary.numCpuCores
                    cpu_info['sockets'] += hardware_summary.numCpuPkgs
                    cpu_info['vendor'].append(hardware_summary.vendor)
                    cpu_info['model'].append(hardware_summary.cpuModel)

        # PF9: To match the stats that are displayed in cluster view on vCenter
        #      we collect data from clusters and not resource pools as nova was
        #      doing.

    cluster_stats = host_statistics_pf9.get_cluster_usage_and_percentage(session, cluster)
    avg_mhz = cluster_stats['total_cpu'] / (max(cpu_info['cores'], 1) * max(cpu_info['sockets'], 1))
    cpu_info['clock_rate'] = [{'cores': cpu_info['cores'],
                                   'mhz': avg_mhz}]
    mem_info['total'] = cluster_stats['total_memory']
    mem_info['free'] = cluster_stats['total_memory'] - cluster_stats['used_memory']
    stats = {'cpu': cpu_info, 'mem': mem_info}
    return stats
# PF9: end


def get_host_ref(session, cluster=None):
    """Get reference to a host within the cluster specified."""
    if cluster is None:
        results = session._call_method(vim_util, "get_objects",
                                       "HostSystem")
        session._call_method(vutil, 'cancel_retrieval',
                             results)
        host_mor = results.objects[0].obj
    else:
        host_ret = session._call_method(vutil, "get_object_property",
                                        cluster, "host")
        if not host_ret or not host_ret.ManagedObjectReference:
            msg = _('No host available on cluster')
            raise exception.NoValidHost(reason=msg)
        host_mor = host_ret.ManagedObjectReference[0]

    return host_mor


def propset_dict(propset):
    """Turn a propset list into a dictionary

    PropSet is an optional attribute on ObjectContent objects
    that are returned by the VMware API.

    You can read more about these at:
    | http://pubs.vmware.com/vsphere-51/index.jsp
    |    #com.vmware.wssdk.apiref.doc/
    |        vmodl.query.PropertyCollector.ObjectContent.html

    :param propset: a property "set" from ObjectContent
    :return: dictionary representing property set
    """
    if propset is None:
        return {}

    return {prop.name: prop.val for prop in propset}


def get_vmdk_backed_disk_device(hardware_devices, uuid):
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                "VirtualDiskFlatVer2BackingInfo" and
                device.backing.uuid == uuid):
            return device


def get_vmdk_volume_disk(hardware_devices, path=None):
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk"):
            if not path or path == device.backing.fileName:
                return device


def get_res_pool_ref(session, cluster):
    """Get the resource pool."""
    # Get the root resource pool of the cluster
    res_pool_ref = session._call_method(vutil,
                                        "get_object_property",
                                        cluster,
                                        "resourcePool")
    return res_pool_ref


def get_all_cluster_mors(session):
    """Get all the clusters in the vCenter."""
    try:
        results = session._call_method(vim_util, "get_objects",
                                        "ClusterComputeResource", ["name"])
        session._call_method(vutil, 'cancel_retrieval',
                             results)
        return results.objects

    except Exception as excep:
        LOG.warning(_LW("Failed to get cluster references %s"), excep)


def get_cluster_ref_by_name(session, cluster_name):
    """Get reference to the vCenter cluster with the specified name."""
    all_clusters = get_all_cluster_mors(session)
    for cluster in all_clusters:
        if (hasattr(cluster, 'propSet') and
                    cluster.propSet[0].val == cluster_name):
            return cluster.obj


def get_vmdk_adapter_type(adapter_type):
    """Return the adapter type to be used in vmdk descriptor.

    Adapter type in vmdk descriptor is same for LSI-SAS, LSILogic & ParaVirtual
    because Virtual Disk Manager API does not recognize the newer controller
    types.
    """
    if adapter_type in [constants.ADAPTER_TYPE_LSILOGICSAS,
                        constants.ADAPTER_TYPE_PARAVIRTUAL]:
        vmdk_adapter_type = constants.DEFAULT_ADAPTER_TYPE
    else:
        vmdk_adapter_type = adapter_type
    return vmdk_adapter_type


def create_vm(session, instance, vm_folder, config_spec, res_pool_ref):
    """Create VM on ESX host."""
    LOG.debug("Creating VM on the ESX host", instance=instance)
    vm_create_task = session._call_method(
        session.vim,
        "CreateVM_Task", vm_folder,
        config=config_spec, pool=res_pool_ref)
    try:
        task_info = session._wait_for_task(vm_create_task)
    except vexc.VMwareDriverException:
        # An invalid guestId will result in an error with no specific fault
        # type and the generic error 'A specified parameter was not correct'.
        # As guestId is user-editable, we try to help the user out with some
        # additional information if we notice that guestId isn't in our list of
        # known-good values.
        # We don't check this in advance or do anything more than warn because
        # we can't guarantee that our list of known-good guestIds is complete.
        # Consequently, a value which we don't recognise may in fact be valid.
        with excutils.save_and_reraise_exception():
            if config_spec.guestId not in constants.VALID_OS_TYPES:
                LOG.warning(_LW('vmware_ostype from image is not recognised: '
                                '\'%(ostype)s\'. An invalid os type may be '
                                'one cause of this instance creation failure'),
                         {'ostype': config_spec.guestId})
    LOG.debug("Created VM on the ESX host", instance=instance)
    return task_info.result


def destroy_vm(session, instance, vm_ref=None):
    """Destroy a VM instance. Assumes VM is powered off."""
    try:
        if not vm_ref:
            vm_ref = get_vm_ref(session, instance)
        LOG.debug("Destroying the VM", instance=instance)
        destroy_task = session._call_method(session.vim, "Destroy_Task",
                                            vm_ref)
        session._wait_for_task(destroy_task)
        LOG.info(_LI("Destroyed the VM"), instance=instance)
    except Exception:
        LOG.exception(_LE('Destroy VM failed'), instance=instance)


def create_virtual_disk(session, dc_ref, adapter_type, disk_type,
                        virtual_disk_path, size_in_kb):
    # Create a Virtual Disk of the size of the flat vmdk file. This is
    # done just to generate the meta-data file whose specifics
    # depend on the size of the disk, thin/thick provisioning and the
    # storage adapter type.
    LOG.debug("Creating Virtual Disk of size  "
              "%(vmdk_file_size_in_kb)s KB and adapter type "
              "%(adapter_type)s on the data store",
              {"vmdk_file_size_in_kb": size_in_kb,
               "adapter_type": adapter_type})

    vmdk_create_spec = get_vmdk_create_spec(
            session.vim.client.factory,
            size_in_kb,
            adapter_type,
            disk_type)

    vmdk_create_task = session._call_method(
            session.vim,
            "CreateVirtualDisk_Task",
            session.vim.service_content.virtualDiskManager,
            name=virtual_disk_path,
            datacenter=dc_ref,
            spec=vmdk_create_spec)

    session._wait_for_task(vmdk_create_task)
    LOG.debug("Created Virtual Disk of size %(vmdk_file_size_in_kb)s"
              " KB and type %(disk_type)s",
              {"vmdk_file_size_in_kb": size_in_kb,
               "disk_type": disk_type})


def copy_virtual_disk(session, dc_ref, source, dest):
    """Copy a sparse virtual disk to a thin virtual disk.

    This is also done to generate the meta-data file whose specifics
    depend on the size of the disk, thin/thick provisioning and the
    storage adapter type.

    :param session: - session for connection
    :param dc_ref: - data center reference object
    :param source: - source datastore path
    :param dest: - destination datastore path
    :returns: None
    """
    LOG.debug("Copying Virtual Disk %(source)s to %(dest)s",
              {'source': source, 'dest': dest})
    vim = session.vim
    vmdk_copy_task = session._call_method(
            vim,
            "CopyVirtualDisk_Task",
            vim.service_content.virtualDiskManager,
            sourceName=source,
            sourceDatacenter=dc_ref,
            destName=dest)
    session._wait_for_task(vmdk_copy_task)
    LOG.debug("Copied Virtual Disk %(source)s to %(dest)s",
              {'source': source, 'dest': dest})


def reconfigure_vm(session, vm_ref, config_spec):
    """Reconfigure a VM according to the config spec."""
    reconfig_task = session._call_method(session.vim,
                                         "ReconfigVM_Task", vm_ref,
                                         spec=config_spec)
    session._wait_for_task(reconfig_task)


def power_on_instance(session, instance, vm_ref=None):
    """Power on the specified instance."""

    if vm_ref is None:
        vm_ref = get_vm_ref(session, instance)

    LOG.debug("Powering on the VM", instance=instance)
    try:
        poweron_task = session._call_method(
                                    session.vim,
                                    "PowerOnVM_Task", vm_ref)
        session._wait_for_task(poweron_task)
        LOG.debug("Powered on the VM", instance=instance)
    except vexc.InvalidPowerStateException:
        LOG.debug("VM already powered on", instance=instance)


def _get_vm_port_indices(session, vm_ref):
    extra_config = session._call_method(vutil,
                                        'get_object_property',
                                        vm_ref,
                                        'config.extraConfig')
    ports = []
    if extra_config is not None:
        options = extra_config.OptionValue
        for option in options:
            if (option.key.startswith('nvp.iface-id.') and
                    option.value != 'free'):
                ports.append(int(option.key.split('.')[2]))
    return ports


def get_attach_port_index(session, vm_ref):
    """Get the first free port index."""
    ports = _get_vm_port_indices(session, vm_ref)
    # No ports are configured on the VM
    if not ports:
        return 0
    ports.sort()
    configured_ports_len = len(ports)
    # Find the first free port index
    for port_index in range(configured_ports_len):
        if port_index != ports[port_index]:
            return port_index
    return configured_ports_len


def get_vm_detach_port_index(session, vm_ref, iface_id):
    extra_config = session._call_method(vutil,
                                        'get_object_property',
                                        vm_ref,
                                        'config.extraConfig')
    if extra_config is not None:
        options = extra_config.OptionValue
        for option in options:
            if (option.key.startswith('nvp.iface-id.') and
                option.value == iface_id):
                return int(option.key.split('.')[2])


def power_off_instance(session, instance, vm_ref=None):
    """Power off the specified instance."""

    if vm_ref is None:
        vm_ref = get_vm_ref(session, instance)

    LOG.debug("Powering off the VM", instance=instance)
    try:
        poweroff_task = session._call_method(session.vim,
                                         "PowerOffVM_Task", vm_ref)
        session._wait_for_task(poweroff_task)
        LOG.debug("Powered off the VM", instance=instance)
    except vexc.InvalidPowerStateException:
        LOG.debug("VM already powered off", instance=instance)


def find_rescue_device(hardware_devices, instance):
    """Returns the rescue device.

    The method will raise an exception if the rescue device does not
    exist. The resuce device has suffix '-rescue.vmdk'.
    :param hardware_devices: the hardware devices for the instance
    :param instance: nova.objects.instance.Instance object
    :return: the rescue disk device object
    """
    for device in hardware_devices.VirtualDevice:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                'VirtualDiskFlatVer2BackingInfo' and
                device.backing.fileName.endswith('-rescue.vmdk')):
            return device

    msg = _('Rescue device does not exist for instance %s') % instance.uuid
    raise exception.NotFound(msg)


def get_ephemeral_name(id):
    return 'ephemeral_%d.vmdk' % id


def _detach_and_delete_devices_config_spec(client_factory, devices):
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    device_config_spec = []
    for device in devices:
        virtual_device_config = client_factory.create(
                                'ns0:VirtualDeviceConfigSpec')
        virtual_device_config.operation = "remove"
        virtual_device_config.device = device
        virtual_device_config.fileOperation = "destroy"
        device_config_spec.append(virtual_device_config)
    config_spec.deviceChange = device_config_spec
    return config_spec


def detach_devices_from_vm(session, vm_ref, devices):
    """Detach specified devices from VM."""
    client_factory = session.vim.client.factory
    config_spec = _detach_and_delete_devices_config_spec(
        client_factory, devices)
    reconfigure_vm(session, vm_ref, config_spec)


def get_ephemerals(session, vm_ref):
    devices = []
    hardware_devices = session._call_method(vutil,
                                            "get_object_property",
                                            vm_ref,
                                            "config.hardware.device")

    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if (device.backing.__class__.__name__ ==
                    "VirtualDiskFlatVer2BackingInfo"):
                if 'ephemeral' in device.backing.fileName:
                    devices.append(device)
    return devices


def get_swap(session, vm_ref):
    hardware_devices = session._call_method(vutil, "get_object_property",
                                            vm_ref, "config.hardware.device")

    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                    "VirtualDiskFlatVer2BackingInfo" and
                'swap' in device.backing.fileName):
            return device


# PF9 Addition
# Block : Start
def get_cdrom_detach_config_spec_if_needed(client_factory, device):
    """
    Builds the cd rom detach config spec only for detaching the
    ISO cd roms
    """
    if device.backing.__class__.__name__ == \
            'VirtualCdromIsoBackingInfo':
        if not hasattr(device.backing, 'deviceName') or not device.backing.deviceName:
            # Create a new virtual device object with same unit number as the
            # one to delete
            virtual_device = client_factory.create('ns0:VirtualDevice')
            virtual_device.unitNumber = device.unitNumber
            virtual_device.key = device.key
        else:
            virtual_device = device
    else:
        # Not an ISO so no need to remove this device. 
        # TODO : We should not try to remove devices that we did not attach.
        # This logic needs to be refined further so that only the config drive
        # CD ROMs are detached
        LOG.info(_('Not detaching CD ROM - [{dev_id}]'.format(dev_id=device.key)))
        return None
    # set the virtual device to be not connected so that we can remove it
    virtual_device.connectable.connected = False
    virtual_device.connectable.startConnected = False
    virtual_device.connectable.allowGuestControl = False
    virtual_device_config = client_factory.create('ns0:VirtualDeviceConfigSpec')
    virtual_device_config.device = virtual_device
    virtual_device_config.operation = "remove"
    return [virtual_device_config]


def clone_vm_pf9(session, instance, client_factory, datastore, dc_info,
                 res_pool_ref, template_ref, config_spec):
    """PF9 function - create a VM by cloning a template"""
    rel_spec = relocate_vm_spec(client_factory,
                                datastore.ref,
                                pool=res_pool_ref)

    if config_spec:
        hardware_devices = session._call_method(
                vutil, 'get_object_property', template_ref,
                'config.hardware.device')
        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice
        for device in hardware_devices:
            if device.__class__.__name__ in ALL_SUPPORTED_NETWORK_DEVICES and hasattr(device, 'macAddress'):
                try:
                    # Workaround for a vCenter 5.1 problem:
                    # http://kb.vmware.com/selfservice/microsites/search.do?language=en_US&cmd=displayKC&externalId=2064681
                    del device.backing.port.portgroupKey
                    del device.backing.port.connectionCookie
                except AttributeError:
                    LOG.debug("Attributes portgroupKey, connectionCookie not found, nothing to remove")
                detach_config_spec = get_network_detach_config_spec(client_factory, device, None)
                config_spec.deviceChange.append(detach_config_spec.deviceChange)

    clone_spec = clone_vm_spec(client_factory,
                                           location=rel_spec,
                                           config=config_spec)
    vm_clone_task = session._call_method(
                            session.vim,
                            "CloneVM_Task", template_ref,
                            folder=dc_info.vmFolder,
                            name=instance.uuid,
                            spec=clone_spec)
    task_info = session._wait_for_task(vm_clone_task)
    return task_info.result


def get_template_ref(driver, template_name):
    all_vms = vm_queries_pf9._get_all_vms(driver)

    for vm in all_vms:
        for prop in vm.propSet:
            if prop.name == "name" and (prop.val == template_name):
                return vm.obj
    raise exception.InstanceNotFound(instance_id=template_name)


def get_instance_info(driver, instance):
    return get_vm_info(driver, instance)


def remove_uuid_from_cache(instance):
    vm_ref_cache_delete(instance)


def list_vm_names_on_vcenter(driver):
    return list_vm_names(driver)


def list_vm_names(driver):
    vm_names = []
    populate_cache_if_needed(driver)
    cache_uuids = _VM_REFS_CACHE.keys()
    for uuid in cache_uuids:
        info = _VM_REFS_CACHE.get(uuid, None)
        if info is None:
            LOG.debug("Instance in cache does not have info associated")
        else:
            vm_names.append(info['name'])
    return vm_names


def get_vm_info(driver, instance_uuid, force=False):
    global _VM_REFS_CACHE
    populate_cache_if_needed(driver, force)
    info = _VM_REFS_CACHE.get(instance_uuid, None)
    if info is not None:
        return info
    else:
        raise exception.InstanceNotFound(instance_id=instance_uuid)


def list_instance_uuids_on_vcenter(driver, node=None, template_uuids=None, force=False):
    return list_instance_uuids(driver, node, template_uuids, force=force)


def list_instance_uuids(driver, node=None, template_uuids=None,
                                                        force=False):
    global _VM_REFS_CACHE
    if node:
        res_pools_to_look_for = [x.value for x in
                                 vm_queries_pf9._get_res_pool_obj_list(driver, node)]
    instance_uuids = []
    populate_cache_if_needed(driver, force=force)

    cache_uuids = _VM_REFS_CACHE.keys()
    for uuid in cache_uuids:
        info = _VM_REFS_CACHE.get(uuid, None)
        if info is None:
            LOG.debug("Instance in cache does not have info associated")
        else:
            if 'template' in info.keys():
                if template_uuids is not None:
                    template_uuids.append(uuid)
            else:
                if node is None:
                    instance_uuids.append(uuid)
                elif info['resourcePool'].value in res_pools_to_look_for:
                    instance_uuids.append(uuid)
    return instance_uuids


def populate_cache_if_needed(driver, force=False):
    global refresh_interval
    global last_refresh
    curr_time = datetime.datetime.now()
    if force or last_refresh is None or \
        (datetime.timedelta(minutes=refresh_interval) \
                            < curr_time-last_refresh) or driver.__class__.__name__ == 'fake_driver':
        populate_cache(driver)


def populate_cache(driver):
    global chunk_size
    global last_refresh
    global _VM_REFS_CACHE
    instance_uuids = vm_queries_pf9.list_instance_uuids_on_vcenter(driver)

    # resetting cache
    vm_refs_cache_reset()

    if instance_uuids and len(instance_uuids) > 0:
        chunked_uuids = [instance_uuids.keys()[i:i+chunk_size] \
                            for i in range(0, len(instance_uuids), chunk_size)]
        for chunk in chunked_uuids:
            uuid_map = {}
            for uuid in chunk:
                uuid_map[uuid] = instance_uuids[uuid]
            instance_infos = vm_queries_pf9.get_instance_info_for_vms(\
                                        driver, uuid_map)
            for uuid in instance_infos:
                instance_info = instance_infos[uuid]
                instance_info['vmref'] = instance_uuids[uuid]['vmref']
                _VM_REFS_CACHE[uuid] = instance_info
    last_refresh = datetime.datetime.now()


def add_vm_to_cache(driver, uuid, instance, is_new=False):
    global _VM_REFS_CACHE

    if is_new:
        _VM_REFS_CACHE[uuid] = {'name': instance['name'], 'vmref': instance['vmref']}
        LOG.info(_VM_REFS_CACHE)
    else:
        try:
            info = vm_queries_pf9.get_instance_info_for_vms(driver, {uuid: instance})
            instance_info = info[uuid]
            instance_info['vmref'] = instance['vmref']
            _VM_REFS_CACHE[uuid] = instance_info
        except:
            LOG.info("Complete instance info not yet found. Not adding instance into VMs cache")


def get_network_information_from_vcenter(driver, needed_uuids):
    global _VM_REFS_CACHE
    all_vm_refs = {}
    if needed_uuids is not None:
        for uuid in needed_uuids:
            try:
                vm_ref = get_vm_ref(driver._session, {'uuid': uuid})
                all_vm_refs[uuid] = vm_ref
            except exception.InstanceNotFound:
                LOG.debug("Instance not found with uuid %s. continuing IP sync" % uuid)
    else:
        all_vm_refs = list_vm_refs_on_vcenter(driver)
    vm_network_info = dict()
    for uuid, vm_ref in all_vm_refs.items():
        info = _VM_REFS_CACHE.get(uuid, None)
        if info is not None:
            vm_network_info[uuid] = []
            get_call = False
            if 'template' not in info:
                if 'networks' in info and len(info['networks']) > 0:
                    for network in info['networks']:
                        if network['ip_address'] is None:
                            get_call = True
                            break
                        else:
                            vm_network_info[uuid].append({'ip_address': network['ip_address'],
                                                          'mac_address': network['mac_address'],
                                                          'bridge': network['bridge']})
                else:
                    get_call = True

                if get_call:
                    try:
                        vm_network_info[uuid] = _get_network_info_for_vm(driver, vm_ref, uuid)
                        if uuid in vm_network_info and len(vm_network_info[uuid]) > 0:
                            _VM_REFS_CACHE[uuid]['networks'] = vm_network_info[uuid]
                    except Exception as ex:
                        # TODO: Move to a stricter exception when we know the
                        #       exact exceptions to catch here.
                        LOG.warn('Could not get the IP address information '
                                 'for [{inst}]. The exception was '
                                 '[{ex}]'.format(inst=uuid, ex=str(ex)))
    return vm_network_info


def list_vm_refs_on_vcenter(driver, force=False):
    global _VM_REFS_CACHE
    vmrefs = {}
    populate_cache_if_needed(driver, force)
    cache_uuids = _VM_REFS_CACHE.keys()
    for uuid in cache_uuids:
        info = _VM_REFS_CACHE.get(uuid, None)
        if info is None:
            LOG.debug("Instance in cache does not have info associated")
        else:
            if 'vmref' not in info:
                vmrefs[uuid] = get_vm_ref(driver._session, {'uuid': uuid})
            else:
                vmrefs[uuid] = info['vmref']
    return vmrefs


def _get_network_info_for_vm(driver, vm_ref, uuid):
    vm_network_info = []
    guest_nics_info = driver._session._call_method(vutil,
                                                   "get_object_property",
                                                   vm_ref,
                                                   "guest.net")
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
            vm_network_info.append({'ip_address': ip_address,
                                          'mac_address': mac_address,
                                          'bridge': network_name})
    else:
        vm_network_info = []
    return vm_network_info


def clone_to_template_pf9(session, client_factory, vm_ref, datastore_ref,
                          folder_ref, respool, config_spec, image_id):
    """
    PF9 function - create a template from a VM
    """
    rel_spec = relocate_vm_spec(client_factory, datastore_ref)
    rel_spec.pool = respool

    cdrom_devices = ['VirtualCdrom']
    if config_spec:
        hardware_devices = session._call_method(vutil,
                                                'get_object_property', vm_ref,
                                                'config.hardware.device')
        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice
        for device in hardware_devices:
            if device.__class__.__name__ in cdrom_devices:
                # Remove the cd roms to avoid piling up multiple cd rom devices
                # over subsequent snapshot creations
                detach_config_spec = get_cdrom_detach_config_spec_if_needed(
                        client_factory, device)
                if detach_config_spec:
                    config_spec.deviceChange.append(detach_config_spec)

    # It is not possible to make changes to devices when cloning to template
    # hence first try to clone as VM and convert to template
    clone_spec = clone_vm_spec(client_factory, location=rel_spec,
                               config=config_spec, template=False)

    try:
        vm_clone_task = session._call_method(session.vim, 'CloneVM_Task',
                                             vm_ref, name=image_id,
                                             spec=clone_spec,
                                             folder=folder_ref)
        task_info = session._wait_for_task(vm_clone_task)
        template_ref = task_info.result
        # Mark the cloned VM as template to complete the snapshot to template
        session._call_method(session.vim, 'MarkAsTemplate', template_ref)
    except vexc.VMwareDriverException as e:
        # If the exception was "Invalid configuration/operation for device xx"
        # while removing the cd roms attached to the VM during cloning, it
        # might have been caused by cd rom attached to original VM from which
        # VM being cloned was cloned initally and that cd rom was later removed.
        # TODO: Remove just the device that is causing issue instead of all
        # devices.
        if not re.search('Invalid .* for device .*', e.message):
            raise e
        # Since we could not change the devices anyway in first attempy,
        # clone to template directly in second attempt
        LOG.warn(_('Cloning to template without removing CD-ROMs'))
        clone_spec.template = True
        clone_spec.config.deviceChange = []
        vm_clone_task2 = session._call_method(session.vim,
                                              'CloneVM_Task', vm_ref,
                                              name=image_id,
                                              spec=clone_spec,
                                              folder=folder_ref)
        task_info = session._wait_for_task(vm_clone_task2)
        template_ref = task_info.result
    return template_ref

# PF9 Addition
# Block End
