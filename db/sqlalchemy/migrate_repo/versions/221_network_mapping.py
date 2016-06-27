#
# Copyright (c) 2014 Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table
from sqlalchemy import MetaData
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy import Integer

from nova.db.sqlalchemy import api as db

nw_to_proj_tables = [('network_projects_pf9', 'networks'),
                     (db._SHADOW_TABLE_PREFIX + 'network_projects_pf9',
                      db._SHADOW_TABLE_PREFIX + 'networks')]
host_to_network_tables = [('compute_node_networks_pf9', 'networks',
                           'compute_nodes'),
    (db._SHADOW_TABLE_PREFIX + 'compute_node_networks_pf9',
    db._SHADOW_TABLE_PREFIX + 'networks',
    db._SHADOW_TABLE_PREFIX + 'compute_nodes')]


def _upgrade_network_to_project_mapping(migrate_engine):
    """
    Upgrades the DB by adding a mapping table between networks and projects.
    This mapping enables sharing of networks between projects. Core
    nova-network stack does not allow sharing, a network object can only
    be assigned to a single project. This mapping keeps information about
    additional projects which are allowed to view a network in addition to its
    owner.
    """
    meta = MetaData(bind=migrate_engine)

    for (table_name, ref_name) in nw_to_proj_tables:
        Table(ref_name, meta, autoload=True)
        map_table = Table(table_name, meta,
                          Column('created_at', DateTime),
                          Column('updated_at', DateTime),
                          Column('deleted_at', DateTime),
                          Column('id', Integer, primary_key=True,
                                 nullable=False),
                          Column('network_id', Integer,
                                 ForeignKey('%s.id' % ref_name)),
                          Column('project_id', String(length=255)),
                          Column('deleted', Integer, nullable=True),
                          extend_existing=True)
        map_table.create()


def _upgrade_host_to_network_mapping(migrate_engine):
    """
    Add network-host mapping
    """

    meta = MetaData(bind=migrate_engine)

    for (table_name, nw_tbl, host_tbl) in host_to_network_tables:
        Table(nw_tbl, meta, autoload=True)
        Table(host_tbl, meta, autoload=True)
        map_table = Table(table_name, meta,
                          Column('created_at', DateTime),
                          Column('updated_at', DateTime),
                          Column('deleted_at', DateTime),
                          Column('id', Integer, primary_key=True,
                                 nullable=False),
                          Column('network_id', Integer,
                                 ForeignKey('%s.id' % nw_tbl)),
                          Column('host_id', Integer,
                                 ForeignKey('%s.id' % host_tbl)),
                          Column('deleted', Integer, nullable=True))
        map_table.create()


def upgrade(migrate_engine):
    _upgrade_network_to_project_mapping(migrate_engine)
    _upgrade_host_to_network_mapping(migrate_engine)


def _downgrade_network_to_project_mapping(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for (table_name, _) in nw_to_proj_tables:
        table = Table(table_name, meta)
        table.drop()


def _downgrade_host_to_network_mapping(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    for (table_name, _, _) in host_to_network_tables:
        table = Table(table_name, meta)
        table.drop()


def downgrade(migrate_engine):
    _downgrade_network_to_project_mapping(migrate_engine)
    _downgrade_host_to_network_mapping(migrate_engine)