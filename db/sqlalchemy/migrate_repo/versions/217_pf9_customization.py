#
# Copyright (c) 2014, Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table
from sqlalchemy import MetaData
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer, Boolean, String, Float
from nova.db.sqlalchemy import types, utils
from sqlalchemy import DateTime

meta = MetaData()

comp_tables = ['compute_nodes', 'shadow_compute_nodes']

def upgrade(migrate_engine):
    meta.bind = migrate_engine
    # Need to load the compute_nodes table so that standalone version works
    for table_name in comp_tables:
        Table(table_name, meta, autoload=True)
        compute_nodes_ip = Table('%s_pf9_ip_info' % table_name, meta,
                                Column('created_at', DateTime),
                                Column('updated_at', DateTime),
                                Column('deleted_at', DateTime),
                                Column('id', Integer,
                                       primary_key=True, nullable=False),
                                Column('host_id', Integer,
                                       ForeignKey("%s.id" % table_name),
                                       nullable=False),
                                Column('deleted', Boolean),
                                Column('interface_name', String(128)),
                                Column('ip', types.IPAddress()),
                                extend_existing=True)

        compute_nodes_ip.create()

        compute_nodes_ext = Table('%s_pf9_ext' % table_name, meta,
                                  Column('created_at', DateTime),
                                  Column('updated_at', DateTime),
                                  Column('deleted_at', DateTime),
                                  Column('id', Integer,
                                         primary_key=True, nullable=False),
                                  Column('host_id', Integer,
                                         ForeignKey("%s.id" % table_name)),
                                  Column('deleted', Boolean),
                                  Column('host_name', String(128)),
                                  extend_existing=True)
        compute_nodes_ext.create()

        compute_nodes_stat = Table('%s_pf9_stats' % table_name, meta,
                                   Column('created_at', DateTime),
                                   Column('updated_at', DateTime),
                                   Column('deleted_at', DateTime),
                                   Column('id', Integer,
                                          primary_key=True, nullable=False),
                                   Column('host_id', Integer,
                                          ForeignKey("%s.id" % table_name)),
                                   Column('deleted', Boolean),
                                   Column('key', String(128)),
                                   Column('value', String(256)),
                                   extend_existing=True)
        compute_nodes_stat.create()


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    for table_name in comp_tables:
        table = Table('%s_pf9_ip_info' % table_name, meta, autoload=True)
        table.drop()
        table = Table('%s_pf9_ext' % table_name, meta, autoload=True)
        table.drop()
        table = Table('%s_pf9_stats' % table_name, meta, autoload=True)
        table.drop()
