# Copyright (c) 2015 Platform9 Systems
# All Rights Reserved.

import testtools
from nova import exception
from nova import test
from nova.tests.unit.virt.vmwareapi import fake
from nova.virt.vmwareapi import vm_utils_pf9
from nova.virt.vmwareapi import vim_util
from nova.virt import resource_types
from nova.virt.vmwareapi import vm_util

class fake_session(object):
    """Fake session class to mock retrieval of objects and their properties"""
    def __init__(self, fake_resource_pools=None, fake_host_system=None, fake_datastore=None,
                 fake_virtual_machines=None, fake_network=None, fake_datacenter=None,
                 fake_cluster=None, fake_vm_folder=None, ret=None):
        self.resource_pools = fake_resource_pools
        self.host_system = fake_host_system
        self.datastore = fake_datastore
        self.virtual_machines = fake_virtual_machines
        self.network = fake_network
        self.datacenter = fake_datacenter
        self.cluster = fake_cluster
        self.vm_folder = fake_vm_folder
        self.ret = ret
        self.vim = fake.FakeVim()

    def return_objects_of_type(self, obj_type):
        if obj_type == "HostSystem":
            return self.host_system
        elif obj_type == "ResourcePool":
            return self.resource_pools
        elif obj_type == "Datastore":
            return self.datastore
        elif obj_type == "VirtualMachine":
            return self.virtual_machines
        elif obj_type == "Network":
            return self.network
        elif obj_type == "Datacenter":
            return self.datacenter
        elif obj_type == "Pf9Datacenter":
            return self.datacenter
        elif obj_type == "ClusterComputeResource":
            return self.cluster
        elif obj_type == 'Folder':
            return self.vm_folder
        else:
            return self.ret

    def _call_method(self, *args, **kwargs):
        if args[1] == "get_dynamic_property":
            fake_objects = self.return_objects_of_type(args[3])
            objectRef = args[2]
            objectProperty = args[4]
            for object in fake_objects.objects:
                if object.obj == objectRef:
                    for p in object.propSet:
                        if p.name == objectProperty:
                            return p.val
        elif args[1] == 'get_dynamic_properties':
            return_dict = dict()
            fake_objects = self.return_objects_of_type(args[3])
            objectRef = args[2]
            objectProperties = args[4]
            for object in fake_objects.objects:
                if object.obj == objectRef:
                    for p in object.propSet:
                        if p.name in objectProperties:
                            return_dict[p.name] = p.val
            return return_dict
        elif args[1] == "get_vc_properties_pf9":
            fake_vim = fake.FakeVim()
            fake_vim._login()
            return vim_util.get_vc_properties_pf9(fake_vim, args[2], args[3], args[4], args[5], None)

        elif args[1] == "get_object_properties":
            obj_ref = args[3]
            obj_type = args[4]
            prop_list = args[5]
            lst_return_objects = fake.FakeRetrieveResult()
            prop_vals = fake.ManagedObject()
            for prop in prop_list:
                prop_val = self._call_method(None, "get_dynamic_property", obj_ref, obj_type, prop)
                elem = fake.Prop()
                elem.name = prop
                elem.val = prop_val
                prop_vals.propSet.append(elem)

            lst_return_objects.add_object(prop_vals)
            return lst_return_objects

        elif args[1] == "get_object_properties_dict":
            obj_ref = args[2]
            obj_type = args[2].type
            prop_list = args[3]
            prop_dict = {}
            for prop in prop_list:
                prop_val = self._call_method(None, "get_dynamic_property", obj_ref, obj_type, prop)
                prop_dict[prop] = prop_val

            return prop_dict

        elif args[1] == "get_object_property":
            obj_ref = args[2]
            obj_type = args[2].type
            property = args[3]
            return_object = fake.FakeRetrieveResult()
            prop_val = self._call_method(None, "get_dynamic_property", obj_ref, obj_type, property)
            return prop_val

        elif args[1] == "get_properties_for_objects_pf9":
            obj_refs = args[3]
            obj_type = args[4]
            prop_list = args[5]
            lst_return_objects = fake.FakeRetrieveResult()
            for obj_ref in obj_refs:
                prop_vals = fake.ManagedObject()
                for prop in prop_list:
                    prop_val = self._call_method(None, "get_dynamic_property", obj_ref, obj_type, prop)
                    elem = fake.Prop()
                    elem.name = prop
                    elem.val = prop_val
                    prop_vals.propSet.append(elem)
                    lst_return_objects.add_object(prop_vals)
            return lst_return_objects

        elif args[1] == "FindAllByUuid":
            return self._get_vim()._find_all_by_uuid(self, args, kwargs)
        else:
            return self.return_objects_of_type(args[2])

    def _get_vim(self):
        return self.vim


class fake_driver(object):
    """Fake driver to mock driver calls from vm_utils_pf9. Uses fake_session"""
    def __init__(self, ret=None, cluster_ref=None):
        self._session = ret
        self._datastore_regex = None
        if cluster_ref:
            self._cluster_ref = cluster_ref


class VMwareVMUtilPf9TestCase(test.NoDBTestCase):
    """Class containing test cases for Pf9 VMware additions"""
    def setUp(self):
        super(VMwareVMUtilPf9TestCase, self).setUp()
        fake.reset()

    def tearDown(self):
        super(VMwareVMUtilPf9TestCase, self).tearDown()
        fake.reset()

    def test_get_hostname(self):
        """Check retrieval of host name from HostSystem"""
        fake_host_name = "test-host"
        fake_host_sys = fake.HostSystem(fake_host_name)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake_host_sys)
        new_session = fake_session(fake_host_system=fake_objects)
        driver = fake_driver(new_session)

        result = vm_utils_pf9.get_hostname(driver)
        self.assertEquals("test-host", result)

    def test_get_host_stats_vc(self):
        """Check retrieval of host stats from VC"""
        res_types = [resource_types.MEMORY,
                     resource_types.CPU,
                     resource_types.DISK_USED,
                     resource_types.DISK_TOTAL]

        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        datastore = fake.Datastore("ds-1", 1024, 500)
        fake._create_object('Datastore', datastore)
        host = fake.HostSystem()
        fake._create_object('HostSystem', host)
        cluster = fake.ClusterComputeResource()
        fake._create_object('ClusterComputeResource', cluster)
        cluster._add_host(host.obj)
        cluster._add_datastore(datastore.obj)

        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)
        fake_hosts = fake.FakeRetrieveResult()
        fake_hosts.add_object(host)
        fake_ds = fake.FakeRetrieveResult()
        fake_ds.add_object(datastore)
        fake_cluster = fake.FakeRetrieveResult()
        fake_cluster.add_object(cluster)

        session = fake_session(fake_resource_pools=fake_pools,
                               fake_host_system=fake_hosts,
                               fake_datastore=fake_ds,
                               fake_cluster=fake_cluster)
        driver = fake_driver(session, cluster_ref=cluster.obj)
        pf9_stats = vm_utils_pf9.get_host_stats_vc(driver, res_types, 'test_cluster')
        self.assertEquals(10.0, pf9_stats['cpu_util_percent'])
        self.assertEquals(48.828125, pf9_stats['mem_util_percent'])
        self.assertEquals(1024.0, pf9_stats['disk_total_gb'])
        self.assertEquals(524.0, pf9_stats['disk_used_gb'])

    def test_get_vm_ref(self):
        """Check retrieval of vm reference using uuid or name"""
        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        cluster = fake.ClusterComputeResource()
        cluster._add_root_resource_pool(respool.obj)
        fake._create_object('ClusterComputeResource', cluster)
        vm_folder = fake.Folder(name='fake-folder')
        fake_folders = fake.FakeRetrieveResult()
        fake_folders.add_object(vm_folder)
        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)
        fake_clusters = fake.FakeRetrieveResult()
        fake_clusters.add_object(cluster)
        optionVal = fake.OptionValue(key="nvp.vm-uuid", value="test-uuid-1")
        virtualMachine1 = fake.VirtualMachine(name="VM-1",
                                              instanceUuid="test-uuid-1",
                                              resourcePool=respool.obj,
                                              extra_config=[optionVal])
        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine1)
        session = fake_session(fake_virtual_machines=fake_vms,
                               fake_resource_pools=fake_pools,
                               fake_cluster=fake_clusters,
                               fake_vm_folder=fake_folders)
        driver = fake_driver(session, cluster_ref=cluster.obj)

        instance = {}
        vm_util.add_vm_to_cache(driver, 'test-uuid-1', {'vmref': virtualMachine1.obj, "template": "false"})
        # Verify retrieval based on uuid
        instance['uuid'] = 'test-uuid-1'
        returned_vm_ref = vm_util.get_vm_ref(driver._session, instance)
        returned_vm_name = driver._session._call_method(None, "get_dynamic_property", returned_vm_ref, "VirtualMachine", "name")
        self.assertEquals(virtualMachine1.obj, returned_vm_ref)
        self.assertEquals("VM-1", returned_vm_name)

        # Verify exception for wrong uuid
        instance['uuid'] = 'non-existent-uuid'
        self.assertRaises(exception.InstanceNotFound, vm_util.get_vm_ref, driver._session, instance)

    def test_get_instance_info(self):
        """Check retrieval of instance info from VM instance in the system"""
        host = fake.HostSystem()
        device = fake.VirtualDisk(unitNumber=0)
        network = fake.Network()
        vm_folder = fake.Folder(name='fake-folder')
        fake._create_object('Folder', vm_folder)
        fake_folders = fake.FakeRetrieveResult()
        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        cluster = fake.ClusterComputeResource()
        cluster._add_root_resource_pool(respool.obj)
        fake._create_object('ClusterComputeResource', cluster)


        virtualMachine = fake.VirtualMachine(name="VM-1",
                                             instanceUuid="fake-uuid",
                                             runtime_host=host.obj,
                                             virtual_device=[device, network],
                                             parent=vm_folder.obj,
                                             resourcePool=respool.obj)

        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine)
        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)
        fake_clusters = fake.FakeRetrieveResult()
        fake_clusters.add_object(cluster)
        session = fake_session(fake_virtual_machines=fake_vms,
                               fake_vm_folder=fake_folders,
                               fake_resource_pools=fake_pools)
        driver = fake_driver(session, cluster_ref=cluster.obj)

        vm_util.add_vm_to_cache(driver, 'fake-uuid', {'vmref': virtualMachine.obj, "template": "false"})
        instance_info = vm_util.get_instance_info(driver, 'fake-uuid')

        virtual_interfaces = instance_info['virtual_interfaces'][0]
        block_device_mapping = instance_info['block_device_mapping_v2'][0]

        self.assertEquals("123.123.123.123", instance_info['access_ip_v4'])
        self.assertEquals("fake-uuid", instance_info['instance_uuid'])
        self.assertEquals(1, instance_info['memory_mb'])
        self.assertEquals("VM-1", instance_info['name'])
        self.assertEquals(1, instance_info['power_state'])
        self.assertEquals(1, instance_info['vcpus'])
        self.assertEquals("test-mac-address", virtual_interfaces['mac_address'])
        self.assertEquals("Test-Network", virtual_interfaces['port_group_label'])
        self.assertEquals(0, block_device_mapping['boot_index'])
        self.assertEquals(False, block_device_mapping['delete_on_termination'])
        self.assertEquals("Test-Virtual-Disk", block_device_mapping['device_name'])
        self.assertEquals("volume", block_device_mapping['guest_format'])
        self.assertEquals("blank", block_device_mapping['source_type'])
        self.assertEquals(1048576, block_device_mapping['virtual_size'])

    def test_get_instance_info_ipv6(self):
        """Check retrieval of instance info from VM instance in the system"""
        host = fake.HostSystem()
        device = fake.VirtualDisk(unitNumber=0)
        network = fake.Network()
        vm_folder = fake.Folder(name='fake-folder')
        fake._create_object('Folder', vm_folder)
        fake_folders = fake.FakeRetrieveResult()
        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        cluster = fake.ClusterComputeResource()
        cluster._add_root_resource_pool(respool.obj)
        fake._create_object('ClusterComputeResource', cluster)

        virtualMachine = fake.VirtualMachine(name="VM-1",
                                             instanceUuid="fake-uuid",
                                             runtime_host=host.obj,
                                             virtual_device=[device, network],
                                             ip_address="aaaa::123:aaaa:aaaa:aaaa",
                                             parent=vm_folder.obj,
                                             resourcePool=respool.obj)

        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine)
        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)
        fake_clusters = fake.FakeRetrieveResult()
        fake_clusters.add_object(cluster)
        session = fake_session(fake_virtual_machines=fake_vms,
                               fake_vm_folder=fake_folders,
                               fake_resource_pools=fake_pools)
        driver = fake_driver(session, cluster_ref=cluster.obj)

        vm_util.add_vm_to_cache(driver, 'fake-uuid', {'vmref': virtualMachine.obj, "template": "false"})

        instance_info = vm_util.get_instance_info(driver, 'fake-uuid')

        self.assertIn('access_ip_v6', instance_info.keys())
        self.assertEquals("aaaa::123:aaaa:aaaa:aaaa", instance_info['access_ip_v6'])


    def test_list_instance_uuids(self):
        """Check list of VM instance uuids"""
        host = fake.HostSystem()
        vm_folder = fake.Folder(name='fake-folder')
        fake._create_object('Folder', vm_folder)
        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        cluster = fake.ClusterComputeResource()
        cluster._add_root_resource_pool(respool.obj)
        fake._create_object('ClusterComputeResource', cluster)

        virtualMachine1 = fake.VirtualMachine(name="VM-1",
                                              instanceUuid="test-uuid-1",
                                              runtime_host=host.obj,
                                              parent=vm_folder.obj,
                                              resourcePool=respool.obj)
        virtualMachine2 = fake.VirtualMachine(name="VM-2",
                                              instanceUuid="test-uuid-2",
                                              runtime_host=host.obj,
                                              parent=vm_folder.obj,
                                              resourcePool=respool.obj)

        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine1)
        fake_vms.add_object(virtualMachine2)
        fake_folders = fake.FakeRetrieveResult()
        fake_folders.add_object(vm_folder)
        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)

        session = fake_session(fake_virtual_machines=fake_vms,
                               fake_vm_folder=fake_folders,
                               fake_resource_pools=fake_pools)
        driver = fake_driver(session, cluster_ref=cluster.obj)
        instance_uuids = vm_util.list_instance_uuids(driver)
        self.assertIn("test-uuid-1", instance_uuids)
        self.assertIn("test-uuid-2", instance_uuids)
        self.assertEquals(2, len(instance_uuids))

    def test_list_instance_uuids_hide_vms(self):
        """
        Check list of VM instance UUIDs and make sure VMs under
        pf9_cinder_volumes are not listed
        """
        host = fake.HostSystem()
        vm_folder = fake.Folder(name='fake-folder')
        fake._create_object('Folder', vm_folder)
        ignore_folder = fake.Folder(name='pf9_cinder_volumes')
        fake._create_object('Folder', ignore_folder)
        respool = fake.ResourcePool()
        fake._create_object('ResourcePool', respool)
        cluster = fake.ClusterComputeResource()
        cluster._add_root_resource_pool(respool.obj)
        fake._create_object('ClusterComputeResource', cluster)

        virtualMachine1 = fake.VirtualMachine(name="VM-1",
                                              instanceUuid="test-uuid-1",
                                              runtime_host=host.obj,
                                              parent=vm_folder.obj,
                                              resourcePool=respool.obj)
        virtualMachine2 = fake.VirtualMachine(name="VM-2",
                                              instanceUuid="test-uuid-2",
                                              runtime_host=host.obj,
                                              parent=ignore_folder.obj,
                                              resourcePool=respool.obj)

        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine1)
        fake_vms.add_object(virtualMachine2)
        fake_folders = fake.FakeRetrieveResult()
        fake_folders.add_object(vm_folder)
        fake_folders.add_object(ignore_folder)
        fake_pools = fake.FakeRetrieveResult()
        fake_pools.add_object(respool)

        session = fake_session(fake_virtual_machines=fake_vms,
                               fake_vm_folder=fake_folders,
                               fake_resource_pools=fake_pools)
        driver = fake_driver(session, cluster_ref=cluster.obj)

        instance_uuids = vm_util.list_instance_uuids(driver)
        self.assertIn("test-uuid-1", instance_uuids)
        self.assertNotIn("test-uuid-2", instance_uuids)
        self.assertEquals(1, len(instance_uuids))

    def test_get_all_networks(self):
        """Check retrieval of networks from a datacenter"""
        network = fake.Network()
        fake_networks = fake.FakeRetrieveResult()
        fake_networks.add_object(network)
        datacenter = fake.Pf9Datacenter(name="test-datacenter", network=[[network.obj]])
        fake_dc = fake.FakeRetrieveResult()
        fake_dc.add_object(datacenter)

        session = fake_session(fake_datacenter=fake_dc, fake_network=fake_networks)
        driver = fake_driver(session)
        networks = vm_utils_pf9.get_all_networks(driver)

        self.assertEquals("vmnet0", networks[0]['bridge'])

    def test_get_all_ip_mappings(self):
        """Check retrieval of IP mappings from guest NIC on a VM"""

        fake_guest_nic = fake.GuestNic()
        virtualMachine = fake.VirtualMachine(name="Test-VM", instanceUuid="test-uuid", guest_nic=fake_guest_nic)
        fake_vms = fake.FakeRetrieveResult()
        fake_vms.add_object(virtualMachine)

        session = fake_session(fake_virtual_machines=fake_vms)
        driver = fake_driver(session)
        ip_mappings = vm_utils_pf9.get_all_ip_mappings(driver)

        nic_details = ip_mappings['test-uuid'][0]
        self.assertEquals("111.222.333.444", nic_details['ip_address'])
        self.assertEquals("de:ad:be:ef:be:ef", nic_details['mac_address'])
        self.assertEquals("Test-Network", nic_details['bridge'])
