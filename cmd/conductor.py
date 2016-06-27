#    Copyright 2012 IBM Corp.
#
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

"""Starter script for Nova Conductor."""

import sys

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr

from nova import config
from nova import objects
# PF9 change
from nova.openstack.common import log_pf9 as logging_pf9
# PF9 end
from nova import service
from nova import utils
from nova import version

CONF = cfg.CONF
CONF.import_opt('topic', 'nova.conductor.api', group='conductor')


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, "nova")
    # PF9 begin
    logging_pf9.setup("nova")
    # PF9 end
    utils.monkey_patch()
    objects.register_all()

    gmr.TextGuruMeditation.setup_autorun(version)

    server = service.Service.create(binary='nova-conductor',
                                    topic=CONF.conductor.topic,
                                    manager=CONF.conductor.manager)
    # PF9 change:
    if CONF.conductor.workers is None:
        # If unset, use openstack default of cpu count
        workers = processutils.get_worker_count()
    else:
        workers = CONF.conductor.workers
        # If set to 0, set it to half of cpu count
        if workers == 0:
            workers = (processutils.get_worker_count() + 1) / 2
    # PF9 end
    service.serve(server, workers=workers)
    service.wait()
