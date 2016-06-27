#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# This is a placeholder for Kilo backports.
# Do not use this number for new Liberty work.  New work starts after
# all the placeholders.
#
# See this for more information:
# http://lists.openstack.org/pipermail/openstack-dev/2013-March/006827.html

from sqlalchemy import MetaData, Table
from sqlalchemy.sql.expression import select, and_


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    compute_nodes = Table('compute_nodes', meta, autoload=True)
    services = Table('services', meta, autoload=True)
    compute_nodes.update().values(
        host=select([services.c.host]).
        where(and_(services.c.id == compute_nodes.c.service_id,
                   compute_nodes.c.deleted == 0,
                   services.c.deleted == 0)).as_scalar()).execute()
