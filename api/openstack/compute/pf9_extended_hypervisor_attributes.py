#
# Copyright (c) 2014, Platform 9 Systems. All rights reserved.
#

__author__ = 'Platform9'

""""The extended hypervisor attributes API extension."""
from nova import db
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.exception import NoNetworksFound
import logging

ALIAS = "OS-EXT-PF9-HYP-ATTR"

authorize = extensions.os_compute_soft_authorizer(ALIAS)


LOG = logging.getLogger(__name__)

class ExtendedHypervisorAttribController(wsgi.Controller):

    def _extend_hypervisor(self, context, hypervisor, instance):
        # Populate host ip info
        key = "%s:ip_info" % ExtendedHypervisorAttributes.alias
        hypervisor[key] = []

        if 'pf9_ip_info' in dir(instance):
            for ip_info in instance['pf9_ip_info']:
                hypervisor[key].append({'if_name': ip_info['interface_name'],
                                        'ip': ip_info['ip']})
        else:
            hypervisor[key].append({})

        # Now populate the PF9's extended host_id attribute
        key = "%s:host_id" % ExtendedHypervisorAttributes.alias
        hypervisor[key] = instance['host']

        # Populate host networks
        key = "{alias}:networks".\
            format(alias=ExtendedHypervisorAttributes.alias)

        if 'pf9_networks' in dir(instance) and len(instance['pf9_networks']) > 0:
            try:
                networks = dict((n['id'], n['uuid'])
                            for n in db.network_get_all(context))
                hypervisor[key] = [{'uuid': networks[long(n)]} for n
                               in instance['pf9_networks']]
            except NoNetworksFound:
                LOG.warning('No networks found in db.')
        else:
            hypervisor[key] = []

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            hypervisors = list(resp_obj.obj['hypervisors'])

            for hypervisor in hypervisors:
                db_instance = req.get_db_item('compute_nodes', hypervisor['id'])
                self._extend_hypervisor(context, hypervisor, db_instance)


class ExtendedHypervisorAttributes(extensions.V21APIExtensionBase):
    """Extended hypervisor attributes support """

    name = "ExtendedHypervisorPf9Attributes"
    alias = ALIAS
    version = 1

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_hypervisor_attributes/api/v21")

    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedHypervisorAttribController()
        extension = extensions.ControllerExtension(self, 'os-hypervisors', controller)
        return [extension]

    def get_resources(self):
        return []

