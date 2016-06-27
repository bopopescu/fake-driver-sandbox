#
# Copyright (c) 2014, Platform9 Systems, All rights reserved
#
__author__ = 'Platform9'

import webob
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import network
from nova import exception
from gettext import gettext as _

ALIAS = "OS-EXT-PF9-network-access"

authorize = extensions.os_compute_authorizer(ALIAS)


class NetworkAccessController(wsgi.Controller):
    def __init__(self, network_api=None):
        super(NetworkAccessController, self).__init__()
        self.network_api = network_api or network.API()

    def _check_body(self, body, subject):
        if not body or not body[subject]:
            raise webob.exc.HTTPBadRequest(_("No request body"))

    @wsgi.action('addProject')
    def _addProject(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action='addProject')
        self._check_body(body, 'addProject')
        vals = body['addProject']
        project_id = vals['project_id']

        try:
            self.network_api.add_access_pf9(context, id, project_id)
        except exception.NetworkAccessExists as e:
            raise webob.exc.HTTPConflict(e.format_message())
        except exception.NetworkNotFound as e:
            raise webob.exc.HTTPNotFound(e.format_message())

    @wsgi.action('removeProject')
    def _removeProject(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action='removeProject')
        self._check_body(body, 'removeProject')
        vals = body['removeProject']
        project_id = vals['project_id']

        try:
            self.network_api.remove_access_pf9(context, id, project_id)
        except exception.NetworkAccessNotFound as e:
            raise webob.exc.HTTPNotFound(e.format_message())
        except exception.NetworkNotFound as e:
            raise webob.exc.HTTPNotFound(e.format_message())

class NetworkAccessPf9(extensions.V21APIExtensionBase):
    """Support for tenant based network access"""

    name = "NetworkSharingSupport"
    alias = ALIAS
    version = 1

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/network_access_pf9"
                 "/api/v21")

    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self,
                                    'os-networks',
                                    NetworkAccessController())
        return [extension]

    def get_resources(self):
        return []
