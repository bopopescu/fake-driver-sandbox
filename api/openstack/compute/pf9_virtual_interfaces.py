#
# Copyright (c) 2015. Platform9 Systems. All Rights Reserved.
#

__author__ = 'Platform9'


from webob import exc
from webob import Response
from nova import network
from nova import exception
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _
from oslo_log import log

LOG = log.getLogger(__name__)

ALIAS = "OS-EXT-PF9-virtual-interfaces"

authorize = extensions.os_compute_authorizer(ALIAS)


class VirtualInterfacePf9Controller(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VirtualInterfacePf9Controller, self).__init__(*args, **kwargs)
        self.network_api = network.API()

    @classmethod
    def _check_body(cls, body, subject):
        if not body or not body[subject]:
            raise exc.HTTPBadRequest(_("No request body"))

    @wsgi.action('removeVif')
    def _removeVif(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action='removeVif')

        self._check_body(body, 'removeVif')
        vif_id = body['removeVif']
        LOG.debug('Deleting virtual interface {vif} for instance {inst}'.\
                  format(vif=vif_id, inst=id))
        try:
            self.network_api.delete_vif_for_instance_pf9(context, id, vif_id)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(e.format_message())

        return Response(status_int=202)

class VirtualInterfacesPf9(extensions.V21APIExtensionBase):
    """Support for managing virtual interfaces of an instance"""
    name = "VirtualInterfacesPF9"
    alias = ALIAS
    version = 1

    # FIXME create this namespace
    namespace = "http://docs.platform9.com/compute/ext/virtual_interfaces_pf9/api/v21"
    updated = "2016-03-03T00:00:00Z"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self, 'servers', VirtualInterfacePf9Controller())
        return [extension]

    def get_resources(self):
        return []
