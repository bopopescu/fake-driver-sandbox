#
# Copyright (c) 2015, Platform9 Systems
# All Rights Reserved
#

from nova.tests.unit.api.openstack import fakes

from nova import compute
from nova import network
from nova import test
from nova.api.openstack.compute import virtual_interfaces
from nova.api.openstack.compute import pf9_virtual_interfaces
from nova.objects import virtual_interface as vif_obj
from nova.tests.unit import policy_fixture

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
VIFS = [{'uuid': '00000000-0000-0000-0000-00000000000000000',
             'address': '00-00-00-00-00-00',
             'instance_uuid': '00-00-00-00-00-00',
             'network_id': '123'},
            {'uuid': '11111111-1111-1111-1111-11111111111111111',
             'address': '11-11-11-11-11-11',
             'instance_uuid': '11-11-11-11-11-11',
             'network_id': '456'}]


def compute_api_get(self, context, instance_id, expected_attrs=None,
                    want_objects=False):
    return dict(uuid=FAKE_UUID, id=instance_id, instance_type_id=1, host='bob')

def _generate_fake_vifs():
    global VIFS
    fake_vifs = []
    for i in range(0, len(VIFS)):
        vif = vif_obj.VirtualInterface()
        vif.uuid = VIFS[i]['uuid']
        vif.address = VIFS[i]['address']
        vif.network_id = VIFS[i]['network_id']
        fake_vifs.append(vif)
    return fake_vifs


def get_vifs_by_instance(self, context, instance_id):
    return _generate_fake_vifs()


def delete_vif(self, context, instance_uuid, vif_id):
    global VIFS

    for i in range(0, len(VIFS)):
        if VIFS[i]['uuid'] == vif_id:
            del VIFS[i]
            return

class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context.get_admin_context()}

class ServerVirtualInterfacePF9Test(test.NoDBTestCase):

    def setUp(self):
        super(ServerVirtualInterfacePF9Test, self).setUp()
        self.stubs.Set(compute.api.API, "get",
                       compute_api_get)
        self.stubs.Set(network.api.API, "get_vifs_by_instance",
                       get_vifs_by_instance)
        self.stubs.Set(network.api.API, "delete_vif_for_instance_pf9",
                       delete_vif)
        self.vif_controller = pf9_virtual_interfaces.VirtualInterfacePf9Controller()
        self.os_vif_controller = virtual_interfaces.ServerVirtualInterfaceController()
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())

    def test_virtual_interfaces_delete(self):
        url = '/v2/fake/servers/abcd/action'
        body = {'removeVif': '11111111-1111-1111-1111-11111111111111111'}
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.vif_controller._removeVif(req, FAKE_UUID, body)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/abcd/os-virtual-interfaces')
        resp = self.os_vif_controller.index(req, 'abcd')
        self.assertIsNotNone(resp, 'NULL response from os-virtual-interfaces')
        data = resp['virtual_interfaces']
        self.assertEqual(len(data), 1, 'Incorrect interfaces : %s' % data)

