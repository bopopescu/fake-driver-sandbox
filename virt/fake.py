# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
A fake (in-memory) hypervisor+api.

Allows nova testing w/o a hypervisor.  This module also documents the
semantics of real hypervisor connections.

"""

import collections
import contextlib

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova.console import type as ctype
from nova import db
from nova import exception
from nova.i18n import _LW
from nova import utils
from nova.virt import diagnostics
from nova.virt import driver
from nova.virt import hardware
from nova.virt import virtapi
# PF9 change
import ConfigParser

from os.path import exists, isfile
from os import remove, makedirs, listdir
import json
import random

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')

LOG = logging.getLogger(__name__)


hostname = CONF.host.split(':', 1)[1]
my_digit = hostname[-1:]
cluster_name = 'domain-c{digit}({hn})'.format(digit=my_digit,hn=hostname)
data_dir = '/tmp/vms/' + hostname

def randomMAC():
    mac = [ 0x00, 0x16, 0x3e,
            random.randint(0x00, 0x7f),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff) ]
    return ':'.join(map(lambda x: "%02x" % x, mac))

if not exists(data_dir):
    makedirs(data_dir)

_FAKE_NODES = None


def set_nodes(nodes):
    """Sets FakeDriver's node.list.

    It has effect on the following methods:
        get_available_nodes()
        get_available_resource

    To restore the change, call restore_nodes()
    """
    global _FAKE_NODES
    _FAKE_NODES = nodes


def restore_nodes():
    """Resets FakeDriver's node list modified by set_nodes().

    Usually called from tearDown().
    """
    global _FAKE_NODES
    _FAKE_NODES = [hostname]


class FakeInstance(object):

    def __init__(self, name, state, uuid, vcpus, memory_mb, root_gb):
        self.name = name
        self.state = state
        self.uuid = uuid
        self.vcpus = vcpus
        self.memory_mb = memory_mb
        self.local_gb = root_gb

    def __getitem__(self, key):
        return getattr(self, key)

    def write(self):
        ip_addr = '.'.join('%s'%random.randint(0, 255) for i in range(4))
        mac = randomMAC()
        fileobj = open('/'.join([data_dir, self.uuid]), 'w')
        fileobj.write(jsonutils.dumps({'name': self.name,
                                       'power_state': self.state,
                                       'vcpus': self.vcpus,
                                       'memory_mb': self.memory_mb,
                                       'instance_uuid': self.uuid,
                                       'node': cluster_name,
                                       'access_ip_v4': ip_addr,
                                       'block_device_mapping_v2': [{
                                           'guest_format': 'volume',
                                           'boot_index': 0,
                                           'volume_id': None,
                                           'volume_size': None,
                                           'image_id': None,
                                           'snapshot_id': None,
                                           'device_name': 'Hard_disk_1',
                                           'source_type': 'blank',
                                           'destination_type': 'local',
                                           'virtual_size': self.local_gb,
                                           'delete_on_termination': False}],
                                       'datastore': 'esx-{digit}'.format(digit=my_digit),
                                       'networks': [{
                                           'bridge': 'vibr0',
                                           'ip_address': ip_addr,
                                           'mac_address': mac}],
                                       'virtual_interfaces': [{
                                           'bridge': '',
                                           'port_group_label': 'Network adapter 1',
                                           'mac_address': mac}]}))
        fileobj.close()

    @staticmethod
    def delete(uuid):
        try:
            remove('/'.join([data_dir, uuid]))
        except:
            pass

    @staticmethod
    def from_file(uuid):
        fileobj = open('/'.join([data_dir, uuid]))
        vm = json.load(fileobj)
        return FakeInstance(vm['name'], vm['state'], uuid, vm['vcpus'], vm['memory_mb'], vm['block_device_mapping_v2'][0]['virtual_size'])


class Resources(object):
    vcpus = 0
    memory_mb = 0
    local_gb = 0
    vcpus_used = 0
    memory_mb_used = 0
    local_gb_used = 0

    def __init__(self, vcpus=8, memory_mb=8000, local_gb=500):
        self.vcpus = vcpus
        self.memory_mb = memory_mb
        self.local_gb = local_gb

    def claim(self, vcpus=0, mem=0, disk=0):
        self.vcpus_used += vcpus
        self.memory_mb_used += mem
        self.local_gb_used += disk

    def release(self, vcpus=0, mem=0, disk=0):
        self.vcpus_used -= vcpus
        self.memory_mb_used -= mem
        self.local_gb_used -= disk

    def dump(self):
        return {
            'vcpus': self.vcpus,
            'memory_mb': self.memory_mb,
            'local_gb': self.local_gb,
            'vcpus_used': self.vcpus_used,
            'memory_mb_used': self.memory_mb_used,
            'local_gb_used': self.local_gb_used
        }


class FakeDriver(driver.ComputeDriver):
    capabilities = {
        "has_imagecache": True,
        "supports_recreate": True,
        "supports_migrate_to_same_host": True
        }

    # Since we don't have a real hypervisor, pretend we have lots of
    # disk and ram so this driver can be used to test large instances.
    vcpus = 1000
    memory_mb = 800000
    local_gb = 6000000

    """Fake hypervisor driver."""

    def __init__(self, virtapi, read_only=False):
        super(FakeDriver, self).__init__(virtapi)
        self.instances = {}
        self.resources = Resources(
            vcpus=self.vcpus,
            memory_mb=self.memory_mb,
            local_gb=self.local_gb)
        self.host_status_base = {
          'hypervisor_type': 'VMware vCenter Server',
          'hypervisor_version': 6000000,
          'hypervisor_hostname': cluster_name,
          'cpu_info': jsonutils.dumps({"clock_rate": [{"cores": 24, "mhz": 1149}], "model": ["AMD Opteron(tm) Processor 6176 SE"], "topology": {"cores": 24, "sockets": 2, "threads": 24}, "vendor": ["HP"]}),
          'disk_available_least': 0,
          'supported_instances': jsonutils.dumps([(arch.X86_64,
                                                   hv_type.VMWARE,
                                                   vm_mode.HVM),
                                                   (arch.I686,
                                                    hv_type.VMWARE,
                                                    vm_mode.HVM)]),
          'numa_topology': None,
          }
        self._mounts = {}
        self._interfaces = {}
        if not _FAKE_NODES:
            set_nodes([hostname])
        self._pf9_hostid = '85eba12f-5873-4059-b8e3-57e27594f8bc'

    def init_host(self, host):
        return

    def list_instances(self):
        uuids = listdir(data_dir)
        result = []
        for uuid in uuids:
            handle = open('/'.join([data_dir, uuid]))
            obj = json.load(handle)
            if 'template' not in obj:
                result.append(obj['name'])
        return result


    def list_instance_uuids(self, node=None, template_uuids=None, force=False):
        uuids = listdir(data_dir)
        result = []
        for uuid in uuids:
            handle = open('/'.join([data_dir, uuid]))
            obj = json.load(handle)
            if 'template' in obj:
                template_uuids.append(uuid)
            else:
                result.append(uuid)
        return result

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        pass

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        pass

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        uuid = instance.uuid
        state = power_state.RUNNING
        flavor = instance.flavor
        disk_size = flavor.root_gb
        self.resources.claim(
            vcpus=flavor.vcpus,
            mem=flavor.memory_mb,
            disk=disk_size)
        fake_instance = FakeInstance(instance.name, state, uuid, flavor.vcpus, flavor.memory_mb, disk_size)
        self.instances[uuid] = fake_instance
        fake_instance.write()

    def snapshot(self, context, instance, image_id, update_task_state):
        if instance.uuid not in self.instances:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)
        update_task_state(task_state=task_states.IMAGE_UPLOADING)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        pass

    def get_host_ip_addr(self):
        return '192.168.0.1'

    def set_admin_password(self, instance, new_pass):
        pass

    def inject_file(self, instance, b64_path, b64_contents):
        pass

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        pass

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        pass

    def unrescue(self, instance, network_info):
        pass

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        pass

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        pass

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        pass

    def power_off(self, instance, timeout=0, retry_interval=0):
        pass

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        pass

    def inject_nmi(self, instance):
        pass

    def soft_delete(self, instance):
        pass

    def restore(self, instance):
        pass

    def pause(self, instance):
        pass

    def unpause(self, instance):
        pass

    def suspend(self, context, instance):
        pass

    def resume(self, context, instance, network_info, block_device_info=None):
        pass

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        key = instance.uuid
        FakeInstance.delete(key)
        if key in self.instances:
            flavor = instance.flavor
            self.resources.release(
                vcpus=flavor.vcpus,
                mem=flavor.memory_mb,
                disk=flavor.root_gb)
            del self.instances[key]
        else:
            LOG.warning(_LW("Key '%(key)s' not in instances '%(inst)s'"),
                        {'key': key,
                         'inst': self.instances}, instance=instance)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        pass

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info."""
        instance_name = instance.name
        if instance_name not in self._mounts:
            self._mounts[instance_name] = {}
        self._mounts[instance_name][mountpoint] = connection_info

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
        try:
            del self._mounts[instance.name][mountpoint]
        except KeyError:
            pass

    def swap_volume(self, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Replace the disk attached to the instance."""
        instance_name = instance.name
        if instance_name not in self._mounts:
            self._mounts[instance_name] = {}
        self._mounts[instance_name][mountpoint] = new_connection_info

    def attach_interface(self, instance, image_meta, vif):
        if vif['id'] in self._interfaces:
            raise exception.InterfaceAttachFailed(
                    instance_uuid=instance.uuid)
        self._interfaces[vif['id']] = vif

    def detach_interface(self, instance, vif):
        try:
            del self._interfaces[vif['id']]
        except KeyError:
            raise exception.InterfaceDetachFailed(
                    instance_uuid=instance.uuid)

    def get_info(self, instance):
        if instance.uuid not in self.instances:
            raise exception.InstanceNotFound(instance_id=instance.uuid)
        i = self.instances[instance.uuid]
        power_state = i.state
        if isfile('/'.join([data_dir, instance.uuid])):
            with open('/'.join([data_dir, instance.uuid])) as handle:
                obj = json.load(handle)
                power_state = obj['power_state']
        return hardware.InstanceInfo(state=power_state,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=2,
                                     cpu_time_ns=0)

    def get_diagnostics(self, instance):
        return {'cpu0_time': 17300000000,
                'memory': 524288,
                'vda_errors': -1,
                'vda_read': 262144,
                'vda_read_req': 112,
                'vda_write': 5778432,
                'vda_write_req': 488,
                'vnet1_rx': 2070139,
                'vnet1_rx_drop': 0,
                'vnet1_rx_errors': 0,
                'vnet1_rx_packets': 26701,
                'vnet1_tx': 140208,
                'vnet1_tx_drop': 0,
                'vnet1_tx_errors': 0,
                'vnet1_tx_packets': 662,
        }

    def get_instance_diagnostics(self, instance):
        diags = diagnostics.Diagnostics(state='running', driver='fake',
                hypervisor_os='fake-os', uptime=46664, config_drive=True)
        diags.add_cpu(time=17300000000)
        diags.add_nic(mac_address='01:23:45:67:89:ab',
                      rx_packets=26701,
                      rx_octets=2070139,
                      tx_octets=140208,
                      tx_packets = 662)
        diags.add_disk(id='fake-disk-id',
                       read_bytes=262144,
                       read_requests=112,
                       write_bytes=5778432,
                       write_requests=488)
        diags.memory_details.maximum = 524288
        return diags

    def get_all_bw_counters(self, instances):
        """Return bandwidth usage counters for each interface on each
           running VM.
        """
        bw = []
        return bw

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.
        """
        volusage = []
        return volusage

    def get_host_cpu_stats(self):
        stats = {'kernel': 5664160000000,
                'idle': 1592705190000000,
                'user': 26728850000000,
                'iowait': 6121490000000}
        stats['frequency'] = 800
        return stats

    def block_stats(self, instance, disk_id):
        return [0, 0, 0, 0, None]

    def get_console_output(self, context, instance):
        return 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE'

    def get_vnc_console(self, context, instance):
        return ctype.ConsoleVNC(internal_access_path='FAKE',
                                host='fakevncconsole.com',
                                port=6969)

    def get_spice_console(self, context, instance):
        return ctype.ConsoleSpice(internal_access_path='FAKE',
                                  host='fakespiceconsole.com',
                                  port=6969,
                                  tlsPort=6970)

    def get_rdp_console(self, context, instance):
        return ctype.ConsoleRDP(internal_access_path='FAKE',
                                host='fakerdpconsole.com',
                                port=6969)

    def get_serial_console(self, context, instance):
        return ctype.ConsoleSerial(internal_access_path='FAKE',
                                   host='fakerdpconsole.com',
                                   port=6969)

    def get_mks_console(self, context, instance):
        return ctype.ConsoleMKS(internal_access_path='FAKE',
                                host='fakemksconsole.com',
                                port=6969)

    def get_console_pool_info(self, console_type):
        return {'address': '127.0.0.1',
                'username': 'fakeuser',
                'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        return True

    def refresh_security_group_members(self, security_group_id):
        return True

    def refresh_instance_security_rules(self, instance):
        return True

    def refresh_provider_fw_rules(self):
        pass

    def get_available_resource(self, nodename):
        """Updates compute manager resource info on ComputeNode table.

           Since we don't have a real hypervisor, pretend we have lots of
           disk and ram.
        """
        cpu_info = collections.OrderedDict([
            ('arch', 'x86_64'),
            ('model', 'Nehalem'),
            ('vendor', 'Intel'),
            ('features', ['pge', 'clflush']),
            ('topology', {
                'cores': 1,
                'threads': 1,
                'sockets': 4,
                }),
            ])
        if nodename not in _FAKE_NODES:
            return {}

        host_status = self.host_status_base.copy()
        host_status.update(self.resources.dump())
        host_status['hypervisor_hostname'] = cluster_name
        host_status['host_hostname'] = nodename
        host_status['host_name_label'] = nodename
        #host_status['cpu_info'] = jsonutils.dumps(cpu_info)
        return host_status

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        return

    def get_instance_disk_info(self, instance, block_device_info=None):
        return

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        post_method(context, instance, dest, block_migration,
                            migrate_data)
        return

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        return

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        return {}

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        return

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        return

    def confirm_migration(self, migration, instance, network_info):
        return

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        return

    def unfilter_instance(self, instance, network_info):
        return

    def _test_remove_vm(self, instance_uuid):
        """Removes the named VM, as if it crashed. For testing."""
        self.instances.pop(instance_uuid)

    def host_power_action(self, action):
        """Reboots, shuts down or powers up the host."""
        return action

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        if not mode:
            return 'off_maintenance'
        return 'on_maintenance'

    def set_host_enabled(self, enabled):
        """Sets the specified host's ability to accept new instances."""
        if enabled:
            return 'enabled'
        return 'disabled'

    def get_volume_connector(self, instance):
        return {'ip': CONF.my_block_storage_ip,
                'initiator': 'fake',
                'host': 'fakehost'}

    def get_available_nodes(self, refresh=False):
        return _FAKE_NODES

    def instance_on_disk(self, instance):
        return False

    def quiesce(self, context, instance, image_meta):
        pass

    def unquiesce(self, context, instance, image_meta):
        pass

    def get_pf9_hostid(self):
        """
        Platform9 deployments use different host identifier than host name.
        This is because hostnames can be duplicated and not all evironments
        may use proper DNS resolution
        """
        if self._pf9_hostid:
            return self._pf9_hostid

        try:
            #Use hostagent identifier, default to nova
            host_agent_data_file = '/var/opt/pf9/hostagent/data.conf'
            pf9_cfg = ConfigParser.ConfigParser()
            pf9_cfg.read(host_agent_data_file)
            self._pf9_hostid = pf9_cfg.get('DEFAULT', 'host_id')
            return self._pf9_hostid
        except ConfigParser.Error as e:
            LOG.error('Cannot read host agent data, error: %s' % e)
            return '75582213-0814-4a4b-8152-e362001c44b2'

    def get_host_stats_pf9(self, res_types, refresh=False, nodename=None):
        data = dict()
        res = self.resources.dump()
        for res_type in res_types:
            if 'cpu_util_percent' == res_type:
                data[res_type] = res['vcpus_used'] / res['vcpus'] * 100.0
            elif 'mem_util_percent' == res_type:
                data[res_type] = res['memory_mb_used'] / res['memory_mb'] * 100.0
            elif 'disk_total_gb' == res_type:
                data[res_type] = res['local_gb']
            elif 'disk_used_gb' == res_type:
                data[res_type] = res['local_gb_used']
            else:
                data[res_type] = 10.0
        return data

    def get_all_networks_pf9(self, node=None):
        # Pf9 change - added a node parameter. This is only needed by the VMwareVCDriver, others ignore it
        return [{'bridge': 'vibr0'}]

    def get_instance_info(self, uuid):
        try:
            handle = open('/'.join([data_dir, uuid]))
            obj = json.load(handle)
            uuid = obj['instance_uuid']
            if uuid not in self.instances and 'template' not in obj:
                self.instances[uuid] = FakeInstance(obj['name'], obj['power_state'], uuid, obj['vcpus'], obj['memory_mb'], obj['block_device_mapping_v2'][0]['virtual_size'])
            return obj
        except:
            return {}

    def get_all_ip_mapping_pf9(self, needed_uuids=None):
        network_info = {}
        if needed_uuids is not None:
            uuids = needed_uuids
        else:
            uuids = listdir(data_dir)

        for uuid in uuids:
            handle = open('/'.join([data_dir, uuid]))
            obj = json.load(handle)
            handle.close()
            if 'template' in obj:
                continue
            if 'networks' not in obj:
                continue
            network_info[uuid] = []
            for network in obj['networks']:
                network_info[uuid].append({'ip_address': network['ip_address'],
                                           'mac_address': network['mac_address'],
                                           'bridge': network['bridge']})
        return network_info

    def _get_instinace_files_pf9(self, instance):
        return []


class FakeVirtAPI(virtapi.VirtAPI):
    def provider_fw_rule_get_all(self, context):
        return db.provider_fw_rule_get_all(context)

    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        # NOTE(danms): Don't actually wait for any events, just
        # fall through
        yield


class SmallFakeDriver(FakeDriver):
    # The api samples expect specific cpu memory and disk sizes. In order to
    # allow the FakeVirt driver to be used outside of the unit tests, provide
    # a separate class that has the values expected by the api samples. So
    # instead of requiring new samples every time those
    # values are adjusted allow them to be overwritten here.

    vcpus = 1
    memory_mb = 8192
    local_gb = 1028
