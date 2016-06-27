#
# Copyright (c) 2014, Platform 9 Systems. All rights reserved.
#

__author__ = 'Platform9'

""""The extended hypervisor attributes API extension."""
from nova import db
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
import logging

authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_hypervisor_attributes')

LOG = logging.getLogger(__name__)

class ExtendedHypervisorAttribController(wsgi.Controller):

    def _extend_hypervisor(self, context, hypervisor, instance):
        key = "%s:ip_info" % Extended_hypervisor_attributes.alias
        hypervisor[key] = []

        if 'ip_info' not in instance.keys():
            hypervisor[key].append({})
        else:
            for ip_info in instance['ip_info']:
                hypervisor[key].append({'if_name': ip_info['interface_name'],
                                        'ip': ip_info['ip']})

        # Now populate the PF9's extended host_id attribute
        key = "%s:host_id" % Extended_hypervisor_attributes.alias
        hypervisor[key] = instance['ext'][0]['host_name']

        key = "{alias}:networks".\
            format(alias=Extended_hypervisor_attributes.alias)
        if 'pf9_networks' in instance:
            networks = dict((n['id'], n['uuid'])
                            for n in db.network_get_all(context))
            hypervisor[key] = [{'uuid': networks[n['network_id']]} for n
                               in instance['pf9_networks']]
        else:
            hypervisor[key] = []

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            resp_obj.attach(xml=ExtendedHypervisorAttribTemplate())

            hypervisors = list(resp_obj.obj['hypervisors'])

            for hypervisor in hypervisors:
                db_instance = req.get_db_item('compute_nodes',
                                              hypervisor['id'])
                self._extend_hypervisor(context, hypervisor, db_instance)


class Extended_hypervisor_attributes(extensions.ExtensionDescriptor):
    """Extended hypervisor attributes support """

    name = "ExtendedHypervisorPf9Attributes"
    alias = "OS-EXT-PF9-HYP-ATTR"

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_hypervisor"
                 "_attributes/api/v1")

    updated = "2014-04-21T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedHypervisorAttribController()
        extension = extensions.ControllerExtension(self,
                                                   'os-hypervisors',
                                                   controller)
        return [extension]


def make_hypervisor(elem):
    elem.set('{%s}ip_info' % Extended_hypervisor_attributes.namespace,
             '%s:ip_info' % Extended_hypervisor_attributes.alias)
    elem.set('{%s}host_id' % Extended_hypervisor_attributes.namespace,
             '%s:host_id' % Extended_hypervisor_attributes.alias)


class ExtendedHypervisorAttribTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisor', selector='hypervisor')
        make_hypervisor(root)
        alias = Extended_hypervisor_attributes.alias
        namespace = Extended_hypervisor_attributes.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
