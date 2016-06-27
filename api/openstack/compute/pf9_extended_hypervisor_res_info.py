#
# Copyright (c) 2014, Platform 9 Systems. All rights reserved.
#

__author__ = 'Platform9'

""""The extended hypervisor resource information API extension."""
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.virt.resource_types as res_types
import logging

ALIAS = "OS-EXT-PF9-HYP-RES"

authorize = extensions.os_compute_soft_authorizer(ALIAS)


db_to_api_map = {
    res_types.CPU: 'cpu_util_percent',
    res_types.MEMORY: 'mem_used_percent',
    res_types.DISK_USED: 'disk_used_gb',
    res_types.DISK_TOTAL: 'disk_total_gb',
    res_types.NETWORK_SEND_RATE: 'net_sent_mibps',
    res_types.NETWORK_RECV_RATE: 'net_recvd_mibps',
    res_types.NETWORK_SENT_PKTS: 'net_sent_pkts_k',
    res_types.NETWORK_RECV_PKTS: 'net_recvd_pkts_k'
}

LOG = logging.getLogger(__name__)

class ExtendedHypervisorResInfoController(wsgi.Controller):

    def _extend_hypervisor(self, context, hypervisor, instance):

        if 'pf9_stat' not in dir(instance):
            hypervisor[ExtendedHypervisorResInfo.alias] = {}
            return

        api_info = dict()
        for key, value in instance['pf9_stat'].items():
            api_info[db_to_api_map[key]] = value
        hypervisor[ExtendedHypervisorResInfo.alias] = api_info


    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            hypervisors = list(resp_obj.obj['hypervisors'])

            for hypervisor in hypervisors:
                db_instance = req.get_db_item('compute_nodes',
                                              hypervisor['id'])
                self._extend_hypervisor(context, hypervisor, db_instance)


class ExtendedHypervisorResInfo(extensions.V21APIExtensionBase):
    """Extended hypervisor resource information support """

    name = "ExtendedHypervisorResInfo"
    alias = ALIAS
    version = 1

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_hypervisor"
                 "_resinfo/api/v21")

    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedHypervisorResInfoController()
        extension = extensions.ControllerExtension(self,
                                                   'os-hypervisors',
                                                   controller)
        return [extension]

    def get_resources(self):
        return []
