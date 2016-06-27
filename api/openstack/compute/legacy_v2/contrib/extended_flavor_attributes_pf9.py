#
# Copyright (c) 2015, Platform 9 Systems. All rights reserved.
#

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from oslo_log import log as logging

__author__ = 'Platform9'

""""The extended flavors attributes API extension."""


authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_flavor_attributes_pf9')

LOG = logging.getLogger(__name__)


class ExtendedFlavorAttribPf9Controller(wsgi.Controller):

    def _extend_flavor(self, context, flavor, instance):
        key = "%s:extra_specs" % Extended_flavor_attributes_pf9.alias
        if 'extra_specs' not in instance.keys():
            flavor[key] = {}
        else:
            flavor[key] = instance['extra_specs']

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            resp_obj.attach(xml=ExtendedFlavorAttribPf9Template())
            flavors = list(resp_obj.obj['flavors'])

            db_instances = req.get_db_items('flavors')
            for flavor in flavors:
                self._extend_flavor(context, flavor, db_instances[flavor['id']])


class Extended_flavor_attributes_pf9(extensions.ExtensionDescriptor):
    """Extended flavor attributes support """

    name = "ExtendedFlavorAttributesPf9"
    alias = "OS-EXT-PF9-FLV-ATTR"

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_flavor"
                 "_attributes/api/v1")

    updated = "2015-01-27T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedFlavorAttribPf9Controller()
        extension = extensions.ControllerExtension(self,
                                                   'flavors',
                                                   controller)
        return [extension]


def make_flavor(elem):
    elem.set('{%s}extra_specs' % Extended_flavor_attributes_pf9.namespace,
             '%s:extra_specs' % Extended_flavor_attributes_pf9.alias)


# class ExtendedFlavorAttribPf9Template(xmlutil.TemplateBuilder):
#     def construct(self):
#         root = xmlutil.TemplateElement('flavor', selector='flavor')
#         make_flavor(root)
#         alias = Extended_flavor_attributes_pf9.alias
#         namespace = Extended_flavor_attributes_pf9.namespace
#         return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
