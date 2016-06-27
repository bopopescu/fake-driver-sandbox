#
# Copyright (C) 2015. Platform9 Systems. All Rights Reserved.
#

__author__ = "Platform9"

"""
Tests for weights introduced by PF9
"""
import mock
from nova import context
from nova.scheduler import weights
from nova.scheduler.weights import vcpu_pf9
from nova import db
from nova import test
from nova.tests.unit.scheduler import fakes
import testtools


def fake_compute_node_get_all_networks_pf9(context, network_id):
    return []


class VcpuWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VcpuWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [vcpu_pf9.VcpuWeigher()]


    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]


    def _get_all_hosts(self):
        host_values = [
            # free_vcpus = 1, 2, 4, 8
            ('host1', 'node1', {'vcpus_total': 1, 'vcpus_used': 0}),
            ('host2', 'node2', {'vcpus_total': 3, 'vcpus_used': 1}),
            ('host3', 'node3', {'vcpus_total': 6, 'vcpus_used': 2}),
            ('host4', 'node4', {'vcpus_total': 8, 'vcpus_used': 0})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]


    def test_default_of_spreading_first(self):
        self.stubs.Set(db, 'compute_node_get_all_networks_pf9',
                       fake_compute_node_get_all_networks_pf9)
        hostinfo_list = self._get_all_hosts()

        # host1: free_vcpus=1
        # host2: free_vcpus=2
        # host3: free_vcpus=4
        # host4: free_vcpus=8

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 0.5)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_vcpu_weight_multiplier1(self):
        self.stubs.Set(db, 'compute_node_get_all_networks_pf9',
                       fake_compute_node_get_all_networks_pf9)
        self.flags(vcpu_weight_multiplier=0.0, group='PF9')
        hostinfo_list = self._get_all_hosts()

        # host1: free_vcpus=1
        # host2: free_vcpus=2
        # host3: free_vcpus=4
        # host4: free_vcpus=8

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 0.0)

    def test_vcpu_filter_multiplier2(self):
        self.stubs.Set(db, 'compute_node_get_all_networks_pf9',
                       fake_compute_node_get_all_networks_pf9)

        self.flags(vcpu_weight_multiplier=2.0, group='PF9')
        hostinfo_list = self._get_all_hosts()

        # host1: free_vcpus=1
        # host2: free_vcpus=2
        # host3: free_vcpus=4
        # host4: free_vcpus=8

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 1.0 * 2)
        self.assertEqual(weighed_host.obj.host, 'host4')
