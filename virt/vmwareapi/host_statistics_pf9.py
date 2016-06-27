# Copyright (c) 2014 Platform9 Systems Inc.

# This module will hold all the methods related to collection of host i.e.
# vCenter, cluster and ESX.
# TODO:As a part of IAAS-1778, functions related to collection of host stats (from
#     vm_utils_pf9.py) will be moved to this.

import vim_util
from oslo_vmware import vim_util as oslo_vutil
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def get_cluster_usage_and_percentage(session, cluster_mor):
    """
    Get the CPU and memory usage and usage percentage from cluster
    """

    # Get total memory and CPU from cluster
    cluster_props = session._call_method(oslo_vutil, "get_object_properties_dict",
                                         cluster_mor,
                                         ["host", "summary"])

    try:
        host_mors = cluster_props['host'].ManagedObjectReference
    except:
        host_mors = []
    summary = cluster_props['summary']
    # total memory is reported in bytes, converting to MB
    total_memory = summary['totalMemory'] / 1024.0 ** 2
    total_cpu = summary['totalCpu']

    # Get total used memory and CPU by summing the corresponding stats over
    # the hosts
    used_memory = 0
    used_cpu = 0
    for host_mor in host_mors:
        host_props = session._call_method(oslo_vutil, "get_object_property",
                                          host_mor, "summary")
        try:
            used_cpu += host_props['quickStats']['overallCpuUsage']
            used_memory += host_props['quickStats']['overallMemoryUsage']
        except:
            LOG.warn('host {host_mor} seems to have been disconnected'.format(
                host_mor=str(host_mor)))

    return {
        'total_memory': total_memory,
        'total_cpu': total_cpu,
        'used_memory': used_memory,
        'used_cpu': used_cpu
    }


def get_datastore_usage_stats(session, datastore_mors):
    total_capacity = 0
    total_free = 0
    for datastore_mor in datastore_mors:
        ds_props = session._call_method(oslo_vutil, "get_object_properties_dict",
                                        datastore_mor,
                                        ['summary.capacity',
                                         'summary.freeSpace'])
        ds_capacity = ds_props.get('summary.capacity', 0)
        ds_usage = ds_props.get('summary.freeSpace', 0)
        if not ds_capacity:
            # Not checking for ds_usage since usage of a datastore can be 0
            LOG.warn("Encountered a datastore with 0 capacity - "
                     "{ds_mor}".format(ds_mor=str(datastore_mor)))
        else:
            total_capacity += ds_capacity
            total_free += ds_usage
    return {
        'total_capacity': total_capacity,
        'total_used': total_capacity - total_free
    }
