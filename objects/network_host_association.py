#
# Copyright (c) 2015, Platform9 Systems. All Rights Reserved.
#
__author__ = 'Platform9'

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from oslo_log import log as logging
LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class NetworkHostAssociation(base.NovaPersistentObject, base.NovaObject,
                             base.NovaObjectDictCompat):
    """
    Maintains association between networks and compute nodes
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'network_id': fields.IntegerField(),
        'host_id': fields.IntegerField()
    }

    @staticmethod
    def _from_db_object(context, net_host_obj, db_net_host_obj):
        for key in net_host_obj.fields:
            net_host_obj[key] = db_net_host_obj[key]
        net_host_obj._context = context
        net_host_obj.obj_reset_changes()
        return net_host_obj

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create', reason='Already created')

        db_net_host_obj = db.compute_node_associate_network_pf9(self._context, self.host_id,
                                                                self.network_id)
        self._from_db_object(self._context, self, db_net_host_obj)



@base.NovaObjectRegistry.register
class NetworkHostAssociationList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('NetworkHostAssociation')
    }
    obj_relationships = {
        'objects': [('1.0', '1.0')]
    }

    @base.remotable_classmethod
    def get_by_host_id(cls, context, host_id):
        db_list = db.compute_node_get_all_networks_pf9(context, host_id)
        return base.obj_make_list(context, cls(context), objects.NetworkHostAssociation,
                                  db_list)
