#
# Copyright (c) Platform9 Systems, All rights reserved.
#

__author__ = "Platform9"

from sqlalchemy import Table, MetaData
from sqlalchemy.types import Integer, Boolean

pf9_compute_node_tables = ['compute_nodes_pf9_ip_info',
                       'shadow_compute_nodes_pf9_ip_info',
                       'compute_nodes_pf9_ext',
                       'shadow_compute_nodes_pf9_ext',
                       'compute_nodes_pf9_stats',
                       'shadow_compute_nodes_pf9_stats']

def upgrade(migrate_engine):
    """
    The column 'deleted' in the above mentioned tables was set to 'Boolean' but most of the nova-db code
    assumes it to be an Integer, changing it to reflect that.
    """
    meta = MetaData(bind=migrate_engine)
    for table_name in pf9_compute_node_tables:
        table = Table(table_name, meta, autoload=True)
        table.c.deleted.alter(type=Integer, default=0)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    for table_name in pf9_compute_node_tables:
        table = Table(table_name, meta, autoload=True)
        table.c.deleted.alter(type=Boolean, default=False)

