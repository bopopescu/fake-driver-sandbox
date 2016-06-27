# vim: tabstop=6 shiftwidth=4 softtabstop=4
# Copyright (c) 2014 Platform9 Systems Inc.

from datetime import datetime, timedelta
from oslo_config import cfg
from oslo_vmware import vim_util as oslo_vutil
import vim_util
from numpy import mean
import logging

_counter_name_to_id = None
_counter_id_to_name = None
_disk_query_time = None
#Get disk stats every 5 minutes (keeping this at 5 min to match stat
#collection of other parameters)
_disk_query_interval = timedelta(minutes=5)
#get VC stats every 5 min
_vc_query_time = None
_vc_query_interval = timedelta(minutes=5)

LOG = logging.getLogger(__name__)

stats_opts = [
    cfg.IntOpt('stats_query_interval',
               default=5,
               help='Time interval in minutes between 2 successive '
                    'calls for getting host statistics')
]
CONF = cfg.CONF
CONF.register_opts(stats_opts, 'vmware')


def get_vc_properties_pf9(vim, respools, datastores, hosts, host_res_types,
                          perf_manager=None):
    """
    Gets statistics for vCenter.
    1. CPU and memory usage is collected from resource pools.
    2. Disk usage and capacity is collected from datastore.
    3. Network statistics are aggregated from host systems
    """
    global _vc_query_interval
    global _vc_query_time

    # TBD: Removing this for now, since this method is called in quick succession for each node
    # This optimization needs to keep track of time per node / datastore

    # current_time = datetime.now()
    # if _vc_query_time and \
    #        current_time - _vc_query_time <= _vc_query_interval:
    #    return {}
    # _vc_query_time = current_time

    #Get cpu and mem usage from respool. Get net and disk stats from hosts
    vc_stats = dict()
    if respools is None:
        return None

    if perf_manager is None:
        perf_manager = vim.service_content.perfManager

    cpu_overall_usage = 0
    cpu_max_usage = 0
    mem_overall_usage = 0
    mem_max_usage = 0

    # Get statistics from all resource pools, and sum to provide a view for the entire cluster
    for respool in respools:
        #Performance manager does not provide cpu and memory stats for resource
        #pools. Hence get those stats from runtime.cpu and runtime.mem
        cpu_props = oslo_vutil.get_object_property(vim, respool, "ResourcePool",
                                              "runtime.cpu")
        mem_props = oslo_vutil.get_object_property(vim, respool, "ResourcePool",
                                              "runtime.memory")

        if cpu_props:
            cpu_overall_usage += cpu_props['overallUsage']
            cpu_max_usage += cpu_props['maxUsage']

        if mem_props:
            mem_overall_usage += mem_props['overallUsage']
            mem_max_usage += mem_props['maxUsage']

    cpu_percentage = 1.0 * cpu_overall_usage / max(cpu_max_usage, 1) * 100
    mem_percentage = 1.0 * mem_overall_usage / max(mem_max_usage, 1) * 100

    disk_overall_capacity = 0
    disk_overall_used = 0
    for datastore in datastores:
        disk_capacity = oslo_vutil.get_object_property(vim, datastore,
                                                      "summary.capacity")
        disk_used = disk_capacity - oslo_vutil.get_object_property(
            vim, datastore, "summary.freeSpace")
        disk_overall_capacity += disk_capacity
        disk_overall_used += disk_used

    total_packet_transmitted = 0
    total_packet_received = 0
    total_transmitted_kbps = 0
    total_received_kbps = 0
    for host in hosts:
        host_net_stats = get_esx_properties_pf9(vim, host, host_res_types,
                                                perf_manager)
        total_received_kbps += mean(host_net_stats.get('net.received.average', [0]))
        total_transmitted_kbps += \
            mean(host_net_stats.get('net.transmitted.average', [0]))
        total_packet_received += \
            mean(host_net_stats.get('net.packetsRx.summation', [0]))
        total_packet_transmitted += \
            mean(host_net_stats.get('net.packetsTx.summation', [0]))

    vc_stats['cpu.usage.average'] = cpu_percentage
    vc_stats['mem.usage.average'] = mem_percentage
    vc_stats['disk.capacity'] = disk_overall_capacity
    vc_stats['disk.usage'] = disk_overall_used
    vc_stats['net.transmitted.average'] = total_transmitted_kbps
    vc_stats['net.received.average'] = total_received_kbps
    vc_stats['net.packetsRx.summation'] = total_packet_received
    vc_stats['net.packetsTx.summation'] = total_packet_transmitted

    return vc_stats


def get_esx_properties_pf9(vim, mobj, res_types, perf_manager=None,
                           sampling_period=20):
    """
    Gets the host required properties
    Return format is -
    {
        'mem.usage.average':[xx, yy, zz],
        'cpu.usage.average':[aa, bb, cc],
        'net.transmitted.average':[d, e, f],
        'net.packetsRx.summation':[g, h, i],
        'net.packetsTx.summation':[j, k, l],
        'disk.usage.average':[m, n, o],
        'disk.capacity': p
    }
    All these values need not be arrays every time. Sometimes only a single
    value may be reported.
    """
    #Cache all these values in global variables as they do not change unless
    #host is upgraded
    global _counter_name_to_id
    global _disk_query_time
    global _counter_id_to_name
    global _disk_query_interval
    esx_stats = dict()
    get_disk_stats = False
    client_factory = vim.client.factory
    if mobj is None:
        return None

    if perf_manager is None:
        perf_manager = vim.get_service_content().perfManager

    _init_counters(vim, perf_manager)

    queryspec = client_factory.create('ns0:PerfQuerySpec')
    queryspec.entity = mobj

    counter_dict = _counter_name_to_id
    start_time, end_time = _get_time_interval()

    #20 seconds sampling period with time interval of 5 minutes
    queryspec.startTime = start_time
    queryspec.endTime = end_time
    queryspec.metricId = []
    queryspec.intervalId = sampling_period
    for metric in res_types:
        if "disk" not in metric:
            metric_id = client_factory.create('ns0:PerfMetricId')
            metric_id.counterId = counter_dict.get(metric)
            metric_id.instance = ""
            queryspec.metricId.append(metric_id)
        else:
            get_disk_stats = True

    res = vim.QueryPerf(perf_manager, querySpec=[queryspec])
    if res:
        for val in res[0].value:
            if _counter_id_to_name[val.id.counterId] in \
                    ['cpu.usage.average', 'mem.usage.average']:
                esx_stats[_counter_id_to_name[val.id.counterId]] = [x / 100.0 for x in val.value]
            else:
                esx_stats[_counter_id_to_name[val.id.counterId]] = val.value

    current_time = datetime.now()
    if get_disk_stats and (_disk_query_time is None) or \
            ((current_time - _disk_query_time) >= _disk_query_interval):

        (esx_stats['disk.capacity'], esx_stats['disk.usage']) \
            = _get_total_ds_capacity_for_host(vim, mobj)
        _disk_query_time = current_time

    return esx_stats


def _init_counters(vim, performance_manager):
    global _counter_id_to_name
    global _counter_name_to_id
    if (_counter_name_to_id is None) or (_counter_id_to_name is None):
        (_counter_name_to_id, _counter_id_to_name) = \
            _get_all_counter_info(vim, performance_manager)


def _get_total_ds_capacity_for_host(vim, host):
    """
    Gets the total disk capacity for host. It is done by looking up all the
    datastores of the host and return a summation of their capacities
    """
    datastores = vim_util.get_object_properties(
        vim, None, host, "HostSystem", "datastore")
    # OpenStack uses the first datastore found
    for datastore_obj in datastores.objects:
        for prop in datastore_obj.propSet:
            ds_refs = prop.val[0]
            for ds_ref in ds_refs:
                total_capacity = oslo_vutil.get_object_property(
                    vim, ds_ref, "summary.capacity")
                total_free = oslo_vutil.get_object_property(
                    vim, ds_ref, "summary.freeSpace")
                return total_capacity, (total_capacity - total_free)
    return 0, 0


def _get_time_interval():
    """
    Gets start and end time based on the stats query interval set in the
    nova/nova.conf
    """
    interval = CONF.vmware.stats_query_interval
    current_time = datetime.now()
    start_time = current_time - timedelta(minutes=interval)
    end_time = current_time
    return start_time, end_time


def _get_all_counter_info(vim, performance_manager):
    """
    This function gets all the performance counters.
    This method returns 2 dictionaries one that maps counter names to
    counter ids and another that maps counter ids to counter names
    NOTE: The structure of this function i.e. multiple if's and nested for's is
    based on checking the object structure in debug view.
    """
    #get perfCounter info
    counter_name_to_id = dict()
    counter_id_to_name = dict()
    array_of_counters_obj = None
    all_counters = vim_util.get_object_properties(
        vim, None, performance_manager, "PerformanceManager", ['perfCounter'])

    for counter_prop in all_counters.objects[0].propSet:
        if counter_prop.name == "perfCounter":
            array_of_counters_obj = counter_prop.val
            break

    if array_of_counters_obj is None:
        #We should have received a list of all objects here
        #Return blank dictionary'
        LOG.error("Could not get performance counters")
        raise RuntimeError()

    for counter in array_of_counters_obj[0]:
        key = "%s.%s.%s" % (counter.groupInfo.key,
                            counter.nameInfo.key,
                            counter.rollupType)
        counter_id_to_name[counter.key] = key
        counter_name_to_id[key] = counter.key
    return counter_name_to_id, counter_id_to_name
