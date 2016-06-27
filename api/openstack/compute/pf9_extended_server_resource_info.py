#
# Copyright (c) 2014 Platform 9 Systems. All rights reserved.
#
__author__ = 'Platform9'

"""The extended server resource information API extension"""
from nova.api.openstack import extensions, wsgi

ALIAS = "OS-EXT-PF9-SRV-RES-INFO"

authorize = extensions.os_compute_soft_authorizer(ALIAS)


class ExtendedServerResInfoController(wsgi.Controller):
    def _extend_server(self, context, server, instance):
        key = "%s:res_info" % ExtendedServerResourceInfo.alias
        res_info = dict()
        res_info['cpu_mhz'] = 1000
        res_info['vcpus'] = instance['vcpus']
        res_info['cfg_memory_mb'] = instance['memory_mb']

        # Space configured = root_gb + ephemeral_gb for now
        res_info['cfg_disk_gb'] = instance['root_gb'] + instance['ephemeral_gb']
        server[key] = res_info

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])

            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                self._extend_server(context, server, db_instance)

class ExtendedServerResourceInfo(extensions.V21APIExtensionBase):
    """Extended server resource information support"""

    name = "ExtendedServerResourceInfo"
    alias = ALIAS
    version = 1

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_server_"
                 "resource_info/api/v21")
    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedServerResInfoController()
        extension = extensions.ControllerExtension(self,
                                                   'servers',
                                                   controller)
        return [extension]

    def get_resources(self):
        return []
