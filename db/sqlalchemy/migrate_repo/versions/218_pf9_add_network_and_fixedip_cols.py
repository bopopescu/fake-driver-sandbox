#
# Copyright (c) Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table
from sqlalchemy import MetaData
from sqlalchemy import Column
from sqlalchemy import String
from nova.db.sqlalchemy import types
from nova.db.sqlalchemy import api as db

def create_column(table, shadow_table, name, type_):
    column = Column(name, type_)
    column.create(table)
    column = Column(name, type_)
    column.create(shadow_table)

def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    networks = Table('networks', meta, autoload=True)
    shadow_networks = Table(db._SHADOW_TABLE_PREFIX + 'networks', meta,
                            autoload=True)
    create_column(networks, shadow_networks, 'description', String(255))
    create_column(networks, shadow_networks, 'range_start', types.IPAddress())
    create_column(networks, shadow_networks, 'range_end', types.IPAddress())

def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    networks = Table('networks', meta, autoload=True)
    networks.c.description.drop()
    networks.c.range_start.drop()
    networks.c.range_end.drop()
    shadow_networks = Table(db._SHADOW_TABLE_PREFIX + 'networks', meta,
                            autoload=True)
    shadow_networks.c.description.drop()
    shadow_networks.c.range_start.drop()
    shadow_networks.c.range_end.drop()
