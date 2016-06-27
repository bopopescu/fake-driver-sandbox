#
# Copyright (c) 2014 Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table
from sqlalchemy import MetaData
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import DateTime
from sqlalchemy import Integer

from nova.db.sqlalchemy import api as db

nw_to_inst_tables = [('instance_networks_pf9', 'networks', 'instances'),
    (db._SHADOW_TABLE_PREFIX + 'instance_networks_pf9',
    db._SHADOW_TABLE_PREFIX + 'networks',
    db._SHADOW_TABLE_PREFIX + 'instances')]

def _upgrade_network_to_instance_mapping(migrate_engine):
    """
    Add network-instance mapping
    """
    meta = MetaData(bind=migrate_engine)

    for (table_name, nw_tbl, inst_tbl) in nw_to_inst_tables:
        Table(nw_tbl, meta, autoload=True)
        Table(inst_tbl, meta, autoload=True)
        map_table = Table(table_name, meta,
                          Column('created_at', DateTime),
                          Column('updated_at', DateTime),
                          Column('deleted_at', DateTime),
                          Column('id', Integer, primary_key=True,
                                 nullable=False),
                          Column('network_id', Integer,
                                 ForeignKey('%s.id' % nw_tbl)),
                          Column('instance_id', Integer,
                                 ForeignKey('%s.id' % inst_tbl)),
                          Column('deleted', Integer, nullable=True))
        map_table.create()

def _downgrade_network_to_instance_mapping(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    for (table_name, _, _) in nw_to_inst_tables:
        table = Table(table_name, meta)
        table.drop()

def upgrade(migrate_engine):
    _upgrade_network_to_instance_mapping(migrate_engine)

def downgrade(migrate_engine):
    _downgrade_network_to_instance_mapping(migrate_engine)