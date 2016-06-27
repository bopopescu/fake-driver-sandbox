#
# Copyright (c) 2015, Platform9 Systems. All Rights Reserved
#
__author__ = 'Platform9'

from oslo_config import cfg

from nova.scheduler import weights

vcpu_weight_opts = [
        cfg.FloatOpt('vcpu_weight_multiplier',
                     default=0.5,
                     help='Multiplier used for weighing vcpu.  Negative '
                          'numbers mean to stack vs spread.'),
]

CONF = cfg.CONF
pf9_opt_group = cfg.OptGroup(name='PF9', title='PF9 specific options')
CONF.register_group(pf9_opt_group)
CONF.register_opts(vcpu_weight_opts, group=pf9_opt_group)


class VcpuWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.PF9.vcpu_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        return 1.0 * host_state.vcpus_total / max(host_state.vcpus_used, 1)
