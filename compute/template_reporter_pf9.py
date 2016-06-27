# Copyright (c) 2015 Platform9 Systems Inc.

import logging
import re
import netifaces
from glance_client_pf9 import GlanceClient

log = logging.getLogger(__name__)


def instance_to_image(instance):
    """
    This method converts instance dictionary created by get_instance_info to
    a dictionary of image expected by glance server APIs.
    """
    if not instance['template']:
        raise RuntimeError('Trying to convert non-template VM [{0}] to '
                           'image'.format(instance))
    template_data = dict()
    template_data['name'] = instance['name']
    template_data['checksum'] = None
    template_data['path'] = instance['template']['path']
    template_data['type'] = instance['template']['type']
    template_data['size'] = instance['template']['size']
    template_data['virtual_size'] = instance['template']['virtual_size']
    template_data['vmware_adaptertype'] = instance['template']['vmware_adaptertype']
    template_data['vmware_disktype'] = instance['template']['vmware_disktype']
    template_data['hypervisor_type'] = instance['template']['hypervisor_type']
    template_data['disk_format'] = instance['template']['disk_format']
    template_data['template_uuid'] = instance['instance_uuid']
    template_data['template_name'] = instance['name']
    template_data['vmware_ostype'] = instance['template']['vmware_ostype']
    template_data['template'] = True
    if 'moref' in instance.keys():
        template_data['moref'] = instance['moref']
    return template_data


def check_if_template_pf9(instance):
    if 'template' in instance and instance['template']:
        return True
    return False


class TemplateReporter(GlanceClient):

    def __init__(self):
        super(TemplateReporter, self).__init__()
        self.image_cache = dict()
        self.is_reported_imglib = False

    def get_interface_info(self):
        """
        Get interface information on this host
        """
        interfaces = sorted(netifaces.interfaces())
        regex = re.compile('^(0.0.0.0|127.0.0.1)$')
        ips = []
        for interface in interfaces:
            addresses = netifaces.ifaddresses(interface)

            try:
                # No IPv6 for now
                ip = addresses[netifaces.AF_INET][0]['addr']
                if not regex.match(ip):
                    ips.append(addresses[netifaces.AF_INET][0])
            except KeyError:
                pass

        return ips

    def report_imglib(self):
        if self.is_reported_imglib:
            log.debug("Image Library already reported")
            return

        netinfo = self.get_interface_info()
        if not netinfo:
            log.debug("Not reporting Image Library due to no interface info")
            return

        log.debug("Reporting Image Library for host: %s", self.host_id)
        imagelib = dict()
        imagelib['addresses'] = netinfo
        imagelib['port'] = '8080'
        imagelib['scheme'] = 'http'
        imagelib['host_id'] = self.host_id
        self.report_glance_imglib(imagelib)

        self.is_reported_imglib = True

    def convert_and_report_template(self, instances):
        template_data = []
        for instance in instances:
            template_info = instance_to_image(instance)
            template_data.append(template_info)
            self.image_cache[instance['instance_uuid']] = \
                {'path': instance['template']['path']}
        self.report_template(template_data)

    def report_template(self, template_data):
        self.report_imglib()
        images = {'host_id': self.host_id, 'images': template_data}
        self.call_method('report_discovered_images', images)

    def delete_template(self, uuid):
        self.report_imglib()
        template_info = {
            'path': self.image_cache[uuid]['path'],
            'deleted': True
        }
        images = {'host_id': self.host_id, 'images': [template_info]}
        self.call_method('report_discovered_images', images)
