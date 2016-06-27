#
# Copyright (c) Platform9 Systems, All Rights Reserved.
#
__author__ = 'Platform9'

from nova.i18n import _
from oslo_log import log as logging
from nova.scheduler import filters
from nova import db

LOG = logging.getLogger(__name__)

class ComputeNetworkFilterPf9(filters.BaseHostFilter):
    """Filter hosts based on availability of requested networks"""

    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties, filter_errors={}):
        """Return a list of hosts that can provide requested network(s)"""
        requested_networks = filter_properties.get('requested_networks')

        # Requested networks are tuples of form (network-uuid, fixedIp)
        requested_uuids = set()

        if requested_networks:
            requested_uuids = set([n[0] for n in requested_networks])
        else:
            # Query all tenant networks here since nova will try to associate all available networks
            # in case none are specified during instance creation
            project_networks = db.network_get_all(filter_properties.get('context'),
                                                  filter_properties.get('project_id'))
            requested_uuids = set(net.uuid for net in project_networks)

        LOG.debug('Node: {node} Requested networks: {req}, available '
                  '{avail}'.format(node=host_state, req=requested_uuids,
                                   avail=host_state.network_uuids))
        ret = requested_uuids.issubset(host_state.network_uuids)

        if ret is False:
            self.mark_filter_error(self.__class__, filter_errors)
        return ret

    @classmethod
    def description(cls):
        return _('Can not find a hypervisor with all requested networks')
