#
# Copyright (c) Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Float, Column, MetaData, Table
from sqlalchemy.sql import select, func, null

def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    sysmeta = Table('instance_system_metadata', meta, autoload=True)
    cn = Table('compute_nodes', meta, autoload=True)

    # Check if this is a KVM deployment
    if select([func.count()]).where(cn.c.hypervisor_type == 'QEMU').execute().scalar() > 0:
        # Persist name_on_host for all legacy PF9 created instances based on the old name template
        for i in select([instances.c.uuid, instances.c.id]). \
                        where(instances.c.deleted == 0). \
                        where(instances.c.display_description != 'Discovered Instance').execute():
            # Only add key-value metadata if the name_on_host key is not already present for the instance
            if select([func.count()]).where(i[instances.c.uuid] == sysmeta.c.instance_uuid). \
                     where('name_on_host' == sysmeta.c.key).execute().scalar() == 0:
                sysmeta.insert().values(instance_uuid = i[instances.c.uuid], \
                                        key = 'name_on_host', \
                                        value = 'instance-%08x' % i[instances.c.id], \
                                        deleted = 0, deleted_at = null()).execute()
