#
# Copyright (c) 2014 Platform 9 Systems. All rights reserved.
#
__author__ = 'Platform9'

"""The extended server resource information API extension"""
from nova.api.openstack import extensions, wsgi, xmlutil

authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_server_resource_info')


class ExtendedServerResInfoController(wsgi.Controller):
    def _extend_server(self, context, server, instance):
        key = "%s:res_info" % Extended_server_resource_info.alias
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
            resp_obj.attach(xml=ExtendedServerResourceInfoTemplate())
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            resp_obj.attach(xml=ExtendedServerResourceInfosTemplate())
            servers = list(resp_obj.obj['servers'])

            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                self._extend_server(context, server, db_instance)

class Extended_server_resource_info(extensions.ExtensionDescriptor):
    """Extended server resource information support"""

    name = "ExtendedServerResourceInfo"
    alias = "OS-EXT-PF9-SRV-RES-INFO"

    # FIXME: Create namespace
    namespace = ("http://docs.platform9.net/compute/ext/extended_server_"
                 "resource_info/api/v1")
    updated = "2014-04-21T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedServerResInfoController()
        extension = extensions.ControllerExtension(self,
                                                   'servers',
                                                   controller)
        return [extension]


def make_server(elem):
    elem.set('{%s}res_info' % Extended_server_resource_info.namespace,
             '%s:res_info' % Extended_server_resource_info.alias)


class ExtendedServerResourceInfoTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        alias = Extended_server_resource_info.alias
        namespace = Extended_server_resource_info.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class ExtendedServerResourceInfosTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        alias = Extended_server_resource_info.alias
        namespace = Extended_server_resource_info.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
