# Copyright (c) 2015 Platform9 Systems Inc.

from ConfigParser import ConfigParser, NoOptionError
from glob import glob
from oslo_config import cfg
import logging
import oslo_messaging as messaging

hostagent_config_files = ['/var/opt/pf9/hostagent/data.conf']
nova_config_dir = '/opt/pf9/etc/nova/conf.d'

params = ['rabbit_host', 'rabbit_port', 'rabbit_password', 'rabbit_use_ssl',
          'kombu_ssl_certfile', 'kombu_ssl_keyfile', 'kombu_ssl_ca_certs',
          'rabbit_userid']

log = logging.getLogger(__name__)


class GlanceClient(object):
    topic = 'glance'
    version = '1.0'

    def __init__(self):

        nova_config_files = glob("{0}/nova-cluster*.conf".format(nova_config_dir))

        _pf9_config = ConfigParser({'host_id': "default_host_id"})
        _pf9_config.read(hostagent_config_files)
        self.host_id = _pf9_config.get('DEFAULT', 'host_id')

        _nova_config = ConfigParser()
        _nova_config.read(sorted(nova_config_files))
        config = cfg.ConfigOpts()
        rabbit_host = None
        rabbit_port = 0
        rabbit_userid = None
        rabbit_password = None

        for param in params:
            try:
                val = _nova_config.get('DEFAULT', param)
                setattr(config, param, val)

                if param == 'rabbit_host':
                    rabbit_host = val
                elif param == 'rabbit_port':
                    rabbit_port = val
                elif param == 'rabbit_userid':
                    rabbit_userid = val
                elif param == 'rabbit_password':
                    rabbit_password = val
            except NoOptionError:
                log.error('Value not found %s in config files' % param)

        if rabbit_host and rabbit_port:
            setattr(config, 'rabbit_hosts', ['%s:%s' % (rabbit_host,
                                                        rabbit_port)])
        url = 'rabbit://{0}:{1}@{2}:{3}/'.format(rabbit_userid,
                                                 rabbit_password,
                                                 rabbit_host,
                                                 rabbit_port)
        _transport = messaging.get_transport(config, url=url)
        _target = messaging.Target(topic=self.topic, version=self.version,
                                   exchange='glance')
        self._client = messaging.RPCClient(_transport, _target)

    def report_glance_imglib(self, imagelib):
        try:
            cctxt = self._client.prepare(version=self.version)
            cctxt.cast({'host_id': self.host_id}, 'report_imagelib_host', imagelib=imagelib)
        except Exception as e:
            log.error('report_imagelib_host: RPC failed %s', e)

    def call_method(self, method, images):
        try:
            cctxt = self._client.prepare(version=self.version)
            cctxt.cast({'host_id': self.host_id}, method, images=images)
        except Exception as e:
            log.error('report_discovered_images: RPC failed %s', e)
