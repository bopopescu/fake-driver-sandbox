
# Copyright (c) 2014 Platform9 Systems. All rights reserved
#
__author__ = 'Platform9'

from random import randint
from uuid import uuid4

from nova.tests.unit import policy_fixture
from nova.tests.unit.api.openstack import fakes
from webob import exc

from nova import context
from nova import exception
from nova import test
from nova.api.openstack.compute import networks as os_networks
from nova.api.openstack.compute import pf9_network_access as net_access
from nova.network import api


def generate_network(network_id, owner_project='service'):
    return {
        'id': randint(0, 5000),
        'injected': 0,
        'cidr': '192.168.100.0/24',
        'netmask': '255.255.255.0',
        'bridge': 'virbr0',
        'gateway': '192.168.1.1',
        'broadcast': '255.255.255.255',
        'dns1': 'gw.pf9.net',
        'vlan': '',
        'vpn_public_address': None,
        'vpn_public_port': None,
        'vpn_private_address': None,
        'dhcp_start': None,
        'project_id': owner_project,
        'host': None,
        'cidr_v6': None,
        'gateway_v6': None,
        'label': None,
        'netmask_v6': None,
        'bridge_interface': None,
        'multi_host': None,
        'dns2': None,
        'uuid': network_id,
        'priority': None,
        'rxtx_base': None,
        'deleted': None,
        'description': None,
        'range_start':'192.168.1.2',
        'range_end': '192.168.1.100'
    }

NET_UUIDS = [str(uuid4()) for i in range(0, 5)]
NETWORKS = dict((net_id, generate_network(net_id)) for net_id in NET_UUIDS)

ACCESS_LIST = [
    {'network_id': NET_UUIDS[2], 'project_id': 'proj2'},
    {'network_id': NET_UUIDS[2], 'project_id': 'proj3'},
    {'network_id': NET_UUIDS[3], 'project_id': 'proj3'}
]


class FakeRequest(object):
    environ = {'nova.context': context.get_admin_context()}

    def get_db_item(self, name, network_id):
        return NETWORKS[network_id]


def fake_get_access_pf9(obj, context, network_id):

    if network_id not in NET_UUIDS:
        raise exception.NetworkNotFound(network_id=network_id)

    res = []

    for access in ACCESS_LIST:
        if access['network_id'] == network_id:
            res.append(access)
    return res


def fake_remove_access_pf9(obj, context, network_id, project_id):

    global ACCESS_LIST

    if network_id not in NET_UUIDS:
        raise exception.NetworkNotFound(network_id=network_id)

    existing_projects = filter(lambda  x: x['network_id'] == network_id,
                               ACCESS_LIST)
    existing_projects = [x['project_id'] for x in existing_projects]

    if project_id not in existing_projects:
        raise exception.NetworkAccessNotFound(network_id=network_id,
                                              project_id=project_id)
    ACCESS_LIST.remove({'network_id': network_id,
                        'project_id': project_id})
    return fake_get_access_pf9(obj, context, network_id)


class NetworkAccessTest(test.NoDBTestCase):
    def setUp(self):
        super(NetworkAccessTest, self).setUp()
        self.access_controller = net_access.NetworkAccessController()
        self.os_controller = os_networks.NetworkController()
        self.req = FakeRequest()
        self.context = self.req.environ['nova.context']
        self.stubs.Set(api.API, 'get_access_pf9', fake_get_access_pf9)
        self.stubs.Set(api.API, 'remove_access_pf9', fake_remove_access_pf9)
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())


    def test_add_access(self):
        g_network_id = NET_UUIDS[1]
        new_access_list = filter(lambda x: x['network_id'] == g_network_id,
                                 ACCESS_LIST)
        g_project_id = 'fjghdkjghdk'

        new_access_list.append({'network_id': g_network_id,
                                'project_id': g_project_id})

        def fake_add_access_pf9(obj, context, network_id, project_id):
            self.assertEqual(g_network_id, network_id)
            self.assertEqual(g_project_id, project_id)

        def fake_get_access_pf9_2(obj, context, network_id):
            return new_access_list

        self.stubs.Set(api.API, 'add_access_pf9', fake_add_access_pf9)
        self.stubs.Set(api.API, 'get_access_pf9', fake_get_access_pf9_2)

        body = {'addProject': {'project_id': g_project_id}}
        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action' %
                                      g_network_id, use_admin_context=True)
        resp = self.access_controller._addProject(req, g_network_id, body)

    def test_remove_access(self):
        g_network_id = NET_UUIDS[2]
        g_project_id = 'proj3'
        all_assigned_projects = filter(lambda x: x['network_id'] ==\
                                                 g_network_id, ACCESS_LIST)

        projects_after_remove = filter(lambda x: x['project_id'] != g_project_id,
                                       all_assigned_projects)

        expected = {'network_access': projects_after_remove}

        def fake_remove_access_pf9(obj, context, network_id, project_id):
            self.assertEqual(g_network_id, network_id)
            self.assertEqual(g_project_id, project_id)

        def fake_get_access_pf9_2(obj, context, network_id):
            return projects_after_remove

        self.stubs.Set(api.API, 'remove_access_pf9', fake_remove_access_pf9)
        self.stubs.Set(api.API, 'get_access_pf9', fake_get_access_pf9_2)

        body = {'removeProject': {'project_id': g_project_id}}
        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action'
                                      % g_network_id, use_admin_context=True)
        self.access_controller._removeProject(req, g_network_id,
                                                           body)

    def test_add_access_invalid_body(self):
        body = {}
        network_id = NET_UUIDS[2]
        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action'
                                      % network_id, use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.access_controller._addProject,
                          req, network_id, body)

    def test_remove_access_invalid_body(self):
        body = {}
        network_id = NET_UUIDS[2]

        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action'
                                      % network_id, use_admin_context=True)
        self.assertRaises(exc.HTTPBadRequest,
                          self.access_controller._removeProject,
                          req, network_id, body)

    def test_add_existing_access(self):
        network_id = NET_UUIDS[2]

        def fake_add_access_pf9(obj, context, network_id, project_id):
            raise exception.NetworkAccessExists(network_id=network_id,
                                                project_id=project_id)

        self.stubs.Set(api.API, 'add_access_pf9', fake_add_access_pf9)
        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action'
                                       % network_id, use_admin_context=True)
        body = {'addProject': {'project_id': 'proj_3'}}
        self.assertRaises(exc.HTTPConflict,
                          self.access_controller._addProject,
                          req, network_id, body)

    def test_remove_non_existing_access(self):
        network_id = NET_UUIDS[2]

        def fake_remove_access_pf9(obj, context, network_id, project_id):
            raise exception.NetworkAccessNotFound(network_id=network_id,
                                                  project_id=project_id)

        self.stubs.Set(api.API, 'remove_access_pf9', fake_remove_access_pf9)
        req = fakes.HTTPRequest.blank('/v2/fake/os-networks/%s/action'
                                       % network_id, use_admin_context=True)
        body = {'removeProject': {'project_id': 'proj_3'}}
        self.assertRaises(exc.HTTPNotFound,
                          self.access_controller._removeProject,
                          req, network_id, body)
