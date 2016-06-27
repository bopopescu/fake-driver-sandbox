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
authorize = extensions.soft_extension_authorizer('compute', 'virtual_interfaces_pf9')


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
        if not authorize(context):
            raise exc.HTTPForbidden()

        self._check_body(body, 'removeVif')
        vif_id = body['removeVif']
        LOG.debug('Deleting virtual interface {vif} for instance {inst}'.\
                  format(vif=vif_id, inst=id))
        try:
            self.network_api.delete_vif_for_instance_pf9(context, id, vif_id)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(e.format_message())

        return Response(status_int=202)

class Virtual_interfaces_pf9(extensions.ExtensionDescriptor):
    """Support for managing virtual interfaces of an instance"""
    name = "VirtualInterfacesPF9"
    alias = "OS-EXT-PF9-virtual-interfaces"

    # FIXME create this namespace
    namespace = "http://docs.platform9.com/compute/ext/virtual_interfaces_pf9/api/v1"
    updated = "2015-04-16T00:00:00Z"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self, 'servers', VirtualInterfacePf9Controller())
        return [extension]
