#
# Copyright (c) 2015. Platform9 Systems. All Rights Reserved.
#

from webob import exc
from webob import Response
from nova import compute
from nova import exception
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from oslo_log import log

__author__ = 'Platform9'

LOG = log.getLogger(__name__)
authorize = extensions.soft_extension_authorizer('compute', 'discovery_task_pf9')


class DiscoveryTaskPf9Controller(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(DiscoveryTaskPf9Controller, self).__init__(*args, **kwargs)
        self.host_api = compute.HostAPI()

    @wsgi.action('discovery_task_state_pf9')
    def _discovery_task_state_pf9(self, req, id, body):
        """
        Pf9 task to query the state of the discovery task
        Returns: {"running": True} if discovery is in progress
                {"running": False} if discovery is complete / not running
        """
        context = req.environ['nova.context']
        authorize(context)

        try:
            state = self.host_api.discovery_task_state_pf9(context, host_name=id)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(e.format_message())
        return state

    @wsgi.action('trigger_discovery_task_pf9')
    def _trigger_discovery_task_pf9(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        try:
            self.host_api.trigger_discovery_task_pf9(context, host_name=id)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(e.format_message())

        return Response(status_int=202)


class Discovery_task_pf9(extensions.ExtensionDescriptor):
    """Support for triggering discovery task to run outside of periodic interval"""
    name = "DiscoveryTaskPF9"
    alias = "OS-EXT-PF9-discovery-task"

    namespace = "http://docs.platform9.com/compute/ext/discovery_task_pf9/api/v1"
    updated = "2015-05-29T00:00:00Z"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self, 'os-hosts', DiscoveryTaskPf9Controller())
        return [extension]

