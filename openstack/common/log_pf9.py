#
# Copyright(c) 2015, Platform9 Systems. All Rights Reserved
#

__author__ = 'Platform9'

import os
import inspect
import logging
import logging.handlers
from oslo_config import cfg

CONF = cfg.CONF
#
# Setup logging for platform9 specific functionality
#

pf9_logger = None

def _get_binary_name():
    return os.path.basename(inspect.stack()[-1][1])

def _get_log_file_path(binary=None):
    logfile = CONF.log_file
    logdir = CONF.log_dir

    if logfile and not logdir:
        return logfile

    if logfile and logdir:
        return os.path.join(logdir, logfile)

    if logdir:
        binary = binary or _get_binary_name()
        return '%s.log' % (os.path.join(logdir, 'perf-' + binary),)

    return None


def setup(name):
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

    global pf9_logger
    pf9_logger = logging.getLogger(name=name + '-profile')

    logpath = _get_log_file_path()

    if logpath is not None:
        filelog = logging.handlers.WatchedFileHandler(logpath)
        pf9_logger.addHandler(filelog)
    else:
        null_log = logging.NullHandler()
        pf9_logger.addHandler(null_log)

    for handler in pf9_logger.handlers:
        handler.setFormatter(formatter)

    # Just info log for now
    pf9_logger.setLevel(logging.INFO)
    pf9_logger.propagate = False


def getLogger():
    global pf9_logger
    return pf9_logger