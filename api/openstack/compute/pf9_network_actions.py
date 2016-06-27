#
# Copyright (c) 2015, Platform9 Systems. All Rights Reserved.
#

__author__ = 'Platform9'

from webob import exc
from webob import Response
from nova import objects
from nova import exception

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from oslo_log import log
from gettext import gettext as  _

LOG = log.getLogger(__name__)

ALIAS = "OS-EXT-PF9-network-actions" 
authorize = extensions.os_compute_authorizer(ALIAS)


class NetworkActionController(wsgi.Controller):
    def __init__(self):
        super(NetworkActionController, self).__init__()

    @classmethod
    def _check_body(cls, body, subject):
        if not body or subject not in body:
            raise exc.HTTPBadRequest(_("No request body"))

    @wsgi.action('deleteFixedIPs')
    def _deleteFixedIPs(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action='deleteFixedIPs')
        self._check_body(body, 'deleteFixedIPs')

        try:
            net = objects.Network.get_by_uuid(context, id)
            net.delete_fixed_ips(context)
        except exception.NotFound:
            msg = _('Network {net} not found'.format(net=id))
            LOG.error(msg)
            raise exc.HTTPNotFound()
        except exception.FixedIpAlreadyInUse as e:
            msg = _('Cannot delete, fixed ip in use: {e}'.format(e=e))
            LOG.error(msg)
            raise exc.HTTPServerError(detail=msg)

        return Response(status_int=202)

class NetworkActionsPf9(extensions.V21APIExtensionBase):
    """Platform9 Specific network actions"""
    name = "NetworkActionsPF9"
    alias = ALIAS
    version = 1

    updated = "2016-03-03T00:00:00Z"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(self, 'os-networks',
            NetworkActionController())
        return [extension]

    def get_resources(self):
        return []
