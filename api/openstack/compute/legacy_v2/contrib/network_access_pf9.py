#
# Copyright (c) 2014, Platform9 Systems, All rights reserved
#
__author__ = 'Platform9'

import webob
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import network
from nova import exception
from nova.openstack.common.gettextutils import _

authorize = extensions.soft_extension_authorizer('compute',
                                                 'network_access_pf9')

def make_network_access_pf9(elem):
    elem.set('{%s}access' % Network_access_pf9.namespace)
    elem.set('%s:access' % Network_access_pf9.alias)

class NetworkAccessTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('network', selector='network')
        make_network_access_pf9(root)
        alias = Network_access_pf9.alias
        namespace = Network_access_pf9.namespace
        return xmlutil.MasterTemplate(root, 1,
                                      nsmap={alias: namespace})

class NetworkAccessesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('networks')
        elem = xmlutil.SubTemplateElement(root, 'network', selector='networks')
        make_network_access_pf9(elem)
        alias = Network_access_pf9.alias
        namespace = Network_access_pf9.namespace
        return xmlutil.MasterTemplate(root, 1,
                                      nsmap={alias: namespace})

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
        authorize(context)
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
        authorize(context)
        self._check_body(body, 'removeProject')
        vals = body['removeProject']
        project_id = vals['project_id']

        try:
            self.network_api.remove_access_pf9(context, id, project_id)
        except exception.NetworkAccessNotFound as e:
            raise webob.exc.HTTPNotFound(e.format_message())
        except exception.NetworkNotFound as e:
            raise webob.exc.HTTPNotFound(e.format_message())

class Network_access_pf9(extensions.ExtensionDescriptor):
    """Support for tenant based network access"""

    name = "NetworkSharingSupport"
    alias = "OS-EXT-PF9-network-access"

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/network_access_pf9"
                 "/api/v1")

    updated = "2014-10-16T00:00:00+00:00"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self,
                                    'os-networks',
                                    NetworkAccessController())
        return [extension]
