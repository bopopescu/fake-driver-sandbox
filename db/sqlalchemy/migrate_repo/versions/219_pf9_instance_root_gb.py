#
# Copyright (c) Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table, MetaData, Column
from sqlalchemy.types import Integer, Float
from nova.db.sqlalchemy import api as db


def upgrade_instance_root_gb(migrate_engine):
    """
    Upgrade the root_gb column of instances to use float to accomodate
    Images like cirros whose size is in MB instead of GB
    """
    meta = MetaData(bind=migrate_engine)
    instances = Table('instances', meta, autoload=True)
    shadow_instances = Table(db._SHADOW_TABLE_PREFIX + 'instances', meta,
                            autoload=True)
    instances.c.root_gb.alter(Float)
    shadow_instances.c.root_gb.alter(Float)

def upgrade(migrate_engine):
    upgrade_instance_root_gb(migrate_engine)

def downgrade(migrate_engine):
    downgrade_instance_root_gb(migrate_engine)


def downgrade_instance_root_gb(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    instances = Table('instances', meta, autoload=True)
    shadow_instances = Table(db._SHADOW_TABLE_PREFIX + 'instances', meta,
                            autoload=True)
    instances.c.root_gb.alter(Integer)
    shadow_instances.c.root_gb.alter(Integer)
