#
# Copyright (c) 2015, Platform9 Systems
# All Rights Reserved
#

import testtools
import webob
from webob import Response

from nova import compute
from nova import context as context_maker
from nova import exception
from nova import test
from nova.api.openstack.compute.legacy_v2.contrib import discovery_task_pf9


def stub_discovery_task_state_pf9(self, context, host_name):
    if host_name == "notimplemented":
        raise NotImplementedError()
    elif host_name == "dummydest":
        # Test for non-existent host
        raise exception.ComputeHostNotFound(host=host_name)
    return {"running": True}

def stub_trigger_discovery_task_pf9(self, context, host_name):
    if host_name == "notimplemented":
        raise NotImplementedError()
    elif host_name == "dummydest":
        # Test for non-existent host
        raise exception.ComputeHostNotFound(host=host_name)
    return Response(status_int=202)

class FakeRequestWithNovaService(object):
    environ = {"nova.context": context_maker.get_admin_context()}
    GET = {"service": "compute"}

class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class DiscoveryTaskPf9Test(test.NoDBTestCase):

    def setUp(self):
        super(DiscoveryTaskPf9Test, self).setUp()
        self.stubs.Set(compute.api.HostAPI, 'discovery_task_state_pf9',
                       stub_discovery_task_state_pf9)
        self.stubs.Set(compute.api.HostAPI, 'trigger_discovery_task_pf9',
                       stub_trigger_discovery_task_pf9)
        self.controller = discovery_task_pf9.DiscoveryTaskPf9Controller()

    def test_discovery_task_state_bad_host_pf9(self):
        body = {"discovery_task_state_pf9": "none"}
        dest = 'dummydest'
        with testtools.ExpectedException(webob.exc.HTTPNotFound,
                                         ".*%s.*" % dest):
            self.controller._discovery_task_state_pf9(FakeRequestWithNovaService(), dest, body)

    def test_discovery_task_state_pf9(self):
        body = {"discovery_task_state_pf9": "none"}
        result = self.controller._discovery_task_state_pf9(FakeRequestWithNovaService(), "host_c1", body)
        self.assertEqual(result["running"], True)

    def test_trigger_discovery_task_bad_host_pf9(self):
        body = {"trigger_discovery_task_pf9": "none"}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._trigger_discovery_task_pf9, FakeRequestWithNovaService(), 'dummydest', body)

    def test_trigger_discovery_task_pf9(self):
        body = {"trigger_discovery_task_pf9": "none"}
        result = self.controller._trigger_discovery_task_pf9(FakeRequestWithNovaService(), '192.168.1.1', body)
        self.assertEqual('202 Accepted', result.status)