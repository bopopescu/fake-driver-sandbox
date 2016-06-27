#
# Copyright (c) 2015, Platform 9 Systems. All rights reserved.
#

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from oslo_log import log as logging

__author__ = 'Platform9'

""""The extended flavors attributes API extension."""


ALIAS = "OS-EXT-PF9-FLV-ATTR"

authorize = extensions.os_compute_soft_authorizer(ALIAS)


LOG = logging.getLogger(__name__)


class ExtendedFlavorAttribPf9Controller(wsgi.Controller):

    def _extend_flavor(self, context, flavor, instance):
        key = "%s:extra_specs" % ExtendedFlavorAttributes.alias
        if 'extra_specs' not in instance.keys():
            flavor[key] = {}
        else:
            flavor[key] = instance['extra_specs']

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            flavors = list(resp_obj.obj['flavors'])

            db_instances = req.get_db_items('flavors')
            for flavor in flavors:
                self._extend_flavor(context, flavor, db_instances[flavor['id']])


class ExtendedFlavorAttributes(extensions.V21APIExtensionBase):
    """Extended flavor attributes support """

    name = "ExtendedFlavorAttributesPf9"
    alias = ALIAS 
    version = 1

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_flavor"
                 "_attributes/api/v21")

    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedFlavorAttribPf9Controller()
        extension = extensions.ControllerExtension(self,
                                                   'flavors',
                                                   controller)
        return [extension]

    def get_resources(self):
        return []
