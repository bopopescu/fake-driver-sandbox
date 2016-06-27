# Copyright (c) 2014 Platform9 Systems Inc.

"""
Handles the network discovery on this host
"""

from nova.openstack.common import processutils
from nova.compute.utils import StdTableOutputParser

class NetworkDiscovery:

    def find_all(self):
        """
        Find all bridges and associated information
        :return list of dict: each item in the dictionary contains the bridge
        and bridge_ethernet
        """
        pass


class BridgeUtilsDiscovery(NetworkDiscovery):
    """
    This is a simple utility that parses the brctl output
    A better one would be the one which uses functions defined in
    if_brctl.h but that will take some time before we use that.
    """

    def find_all(self):
        """
        :see find_all in parent NetworkDiscovery class
        Parses
        bridge name	bridge id		STP enabled	interfaces
        docker0		8000.000000000000	no
        virbr0		8000.52540051bad2	yes		virbr0-nic
							                    vnet0
							                    vnet1

        """
        try:
            (stdout, stderr) = processutils.execute("brctl", "show")
            headers = ["bridge name", "bridge id", "STP enabled", "interfaces"]
            stdout_parser = StdTableOutputParser(stdout, delimiter='\t',
                                                 headers=headers,
                                                 columns_desired=1)
            all_bridges = stdout_parser.get_all()
            ret_list = []
            for bridge in all_bridges:
                ret_list.append(self._convert_to_net_info(bridge))
            return ret_list
        except:
            # Log information
            raise

    @staticmethod
    def _convert_to_net_info(data):
        ret_info = {}
        ret_info['bridge'] = data['bridge name']
        return ret_info



# The global variable for the IPDiscovery
API = BridgeUtilsDiscovery()
