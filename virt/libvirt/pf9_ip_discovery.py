# Copyright (c) 2015 Platform9 systems. All rights reserved

import re
import logging
import time
import os.path
from xml.etree import ElementTree as ET

LOG = logging.getLogger(__name__)

# add nova.virt.libvirt.pf9_ip_discovery=DEBUG to the end of default_log_levels in nova.conf

def discover_ips_from_nwfilter(conn):
    """
    libvirt can add filters and expose their metadata through both its API and through virsh.
       obtain a list of instances
       for each instance, obtain its MAC address
       obtain a list of network filters and remember those which
         correspond directly to instances
       from the above list, peek into the filter definition, looking for an IP number
    """

    instances = set(conn.listDefinedDomains())

    instances_to_mac = {}
    for instance in instances:
        instance_info = conn.lookupByName(instance)
        # the Python libvirt bindings are only partially implemented, so many things including
        # instance interface information are only available through the XML
        xml_root = ET.fromstring(instance_info.XMLDesc(0))
        if xml_root is not None:
            mac = xml_root.find('./devices/interface/mac')
            if mac is not None:
                hw_addr = mac.get('address')
                if hw_addr is not None:
                    instances_to_mac[instance] = hw_addr

    instances_to_nw = {}
    filters = conn.listNWFilters()
    for nw_name in filters:
        m = re.search(r"-(instance-[0-9a-f]+)-", nw_name)
        if m:
            instance = m.group(1)
            if instance in instances:
                # an instance may have more than one network associated with it
                if instance not in instances_to_nw:
                    instances_to_nw[instance] = []
                instances_to_nw[instance].append(nw_name)

    macs_to_ips = {}
    for instance in instances_to_mac:
        mac = instances_to_mac[instance]
        if instance not in instances_to_nw:
            continue
        for network in instances_to_nw[instance]:
            network_info = conn.nwfilterLookupByName(network)
            xml_root = ET.fromstring(network_info.XMLDesc(0))
            if xml_root is not None:
                parameters = xml_root.findall('./filterref/parameter')
                if parameters is not None:
                    for parameter in parameters:
                        name = parameter.get('name')
                        if name == 'IP':
                            ip = parameter.get('value')
                            if ip is not None:
                                if mac not in macs_to_ips:
                                    macs_to_ips[mac] = []
                                macs_to_ips[mac].append(ip)

    # code calling this assumes only one ip number
    macs_to_single_ips = {}
    for mac in macs_to_ips:
        macs_to_single_ips[mac] = macs_to_ips[mac][0]

    LOG.debug("nwfilter discovery: %s" % repr(macs_to_single_ips))
    return macs_to_single_ips


def discover_ips_from_arp(runner):
    """
    Among the traffic sent by instances to their host are ARP packets, from which
    ip numbers associated with the instances' MAC addresses can be obtained. Unfortunately
    not all hypervisors will have this mapping available.
    """

    (stdout, stderr) = runner("arp", "-n")

    # Example output from arp -n:
    # Address       HWtype  HWaddress           Flags Mask            Iface
    # 10.1.10.213   ether   00:23:54:9c:95:88   C                     eth3

    macs_to_single_ips = {}

    index = 0
    for line in stdout.split("\n"):
        # skip the first line
        index += 1
        if index > 1:
            columns = line.split()
            if len(columns) >= 2:
                macs_to_single_ips[columns[2]] = columns[0]

    LOG.debug("arp discovery: %s" % repr(macs_to_single_ips))
    return macs_to_single_ips

def discover_ips_from_sniffer():
    """
    If there is a sniffing daemon running, access its cache file. Neither Nova nor
    this driver knows or cares if it's running, so no harm if it isn't there.
    """

    now = int(time.time())
    six_hours = 3600 * 6

    macs_to_single_ips = {}

    # fields in the ip-discovery.cache file:
    #   ipaddr
    #   hwaddr
    #   packet count
    #   first encountered timestamp
    #   last seen timestamp
    #   age in seconds (delta between previous two fields)

    cache = "/opt/pf9/data/ip-discovery.cache"

    if os.path.isfile(cache):
        with open(cache, "r") as f:
            for line in f:
                columns = line.split()
                if len(columns) >= 5:
                    ipaddr = columns[0]
                    hwaddr = columns[1]
                    timestamp = int(columns[4])
                    age = now - timestamp
                    if '.' in ipaddr and ':' in hwaddr and age < six_hours:
                        macs_to_single_ips[columns[1]] = columns[0]

    LOG.debug("sniffing discovery: %s" % repr(macs_to_single_ips))
    return macs_to_single_ips
