# Copyright (c) 2015 Platform9 Systems, Inc.

from oslo_concurrency import processutils
from nova.compute import utils as compute_utils
import ConfigParser

def get_all_networks_pf9():
    # The node parameter is not used by libvirt, because there is only 1 node / host
    # It is mainly needed for VMwareVCDriver
    try:
        (stdout, stderr) = processutils.execute("brctl", "show")
        headers = ["bridge name", "bridge id", "STP enabled", "interfaces"]
        stdout_parser = compute_utils.\
            StdTableOutputParser(stdout, delimiter='\t', headers=headers,
                                 columns_desired=1)
        all_bridges = stdout_parser.get_all()
        ret_list = []
        for bridge in all_bridges:
            ret_list.append({'bridge': bridge['bridge name']})
        return ret_list
    except:
        raise

def get_pf9_hostid(log, default_value):
    """
    Platform9 deployments use different host identifier than host name.
    This is because hostnames can be duplicated and not all evironments
    may use proper DNS resolution
    """
    try:
        # Use hostagent identifier, default to nova
        host_agent_data_file = '/var/opt/pf9/hostagent/data.conf'
        pf9_cfg = ConfigParser.ConfigParser()
        pf9_cfg.read(host_agent_data_file)
        return pf9_cfg.get('DEFAULT', 'host_id')
    except ConfigParser.Error as e:
        log.warn('Cannot read host agent data, error: %s' % e)
        return default_value

