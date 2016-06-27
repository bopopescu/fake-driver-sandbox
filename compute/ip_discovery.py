# Copyright (c) 2014 Platform9 Systems Inc.

"""
Handles the IP address discovery through various strategies
* ARP Cache: The only implementation that is needed
* IPAM : Not Implemented
* Guest Tools: Not Implemented
"""

from nova.openstack.common import processutils

class IPDiscovery:

    def find_all(self):
        """
        Find all the mac_address -> ip_address mapping on this host
        :return dict: The return value is a dictionary of
        mac_address->ip_address
        """
        return self.find_by_mac_addresses(None)

    def find_by_mac_addresses(self, mac_addresses):
        """
        :mac_addresses array: The list of mac_addresses that we need to query
        for, if None search for all
        :return dict: The return value is a dictionary of
        mac_address->ip_address mapping
        """
        pass

class ArpCacheIPDiscovery(IPDiscovery):
    """
    ARP Cache discovery uses the ARP utility to discover the IP address.
    This is little dangerous because we are assuming one version of arp with
    one way of returning the result, we should be using API whenever possible.
    """

    def find_by_mac_addresses(self, mac_addresses):
        """
        :mac_addresses array: The list of mac_addresses that we need to query
        for.
        :return dict: The return value is a dictionary of
        mac_address->ip_address mapping
        """
        try:
            (stdout, stderr) = processutils.execute("arp", "-n")
            all_mappings = self._parse_result(stdout)
            if mac_addresses:
                return self._filter(all_mappings, mac_addresses)
            else:
                return all_mappings
        except:
            # Log information
            raise

    @staticmethod
    def _filter(all_addresses, mac_addresses):
        valid_addresses_set = set(mac_addresses)
        return dict((k, v) for (k, v) in all_addresses.items()
                    if k in valid_addresses_set)

    @staticmethod
    def _parse_result(stdout):
        """
        :param stdout:
        The stdout is formatted int he following way
        Address                  HWtype  HWaddress           Flags Mask   Iface
        10.1.10.213              ether   00:23:54:9c:95:88   C            eth3
        10.1.10.165              ether   00:50:56:a9:bd:ec   C            eth3
        10.1.10.1                ether   9c:d3:6d:c3:86:ab   C            eth3
        10.1.10.2                ether   00:50:56:a9:a0:c2   C            eth3
        :return:
        Map from mac-address-> ip-address
        """
        ret_data = {}
        lines = stdout.split("\n")
        index = 0
        for line in lines:
            # Ignore the first line
            if index == 0:
                index += 1
                continue
            index += 1
            columns = line.split()
            if len(columns) < 2:
                continue
            # Column[0] is the ip-address
            ip_address = columns[0]
            # Column [2] is the HWaddress
            mac_address = columns[2]
            # Can there be multiple IP address for the same mac ?
            ret_data[mac_address] = ip_address

        return ret_data


# The global variable for the IPDiscovery
API = ArpCacheIPDiscovery()
