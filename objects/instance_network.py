#
# Copyright (c) 2015, Platform9 Systems. All Rights Reserved.
#
__author__ = 'Platform9'

from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields
from oslo_log import log as logging
LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class InstanceNetwork(base.NovaPersistentObject, base.NovaObject,
                      base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'instance_id': fields.IntegerField(),
        'network_id': fields.IntegerField()
    }

    @staticmethod
    def _from_db_object(context, instance_network, db_obj):
        for field in instance_network.fields:
            if field == 'deleted':
                instance_network.deleted = db_obj['deleted'] == db_obj['id']
            else:
                instance_network[field] = db_obj[field]
        instance_network._context = context
        instance_network.obj_reset_changes()
        return instance_network

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create', reason='Already created')
        db_list = db.instance_associate_networks_pf9(self._context,
                                            self.instance_id,
                                            [self.network_id])
        if db_list is not None and len(db_list) > 0:
            self._from_db_object(self._context, self, db_list[0])
