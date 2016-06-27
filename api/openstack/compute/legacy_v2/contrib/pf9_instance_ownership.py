# Copyright (c) 2014 Platform9 systems. All rights reserved

import logging
import webob

from nova import compute
from nova import exception
from nova import quota
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.openstack.common.gettextutils import _

LOG = logging.getLogger(__name__)
AUTHORIZE = extensions.soft_extension_authorizer('compute', 'change_owner')
QUOTAS = quota.QUOTAS

class InstanceOwnershipController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(InstanceOwnershipController, self).__init__(*args, **kwargs)
        self._compute_api = compute.API()

    @staticmethod
    def _get_params(body):
        if body and isinstance(body, dict) and body.has_key('changeOwner'):
            return body['changeOwner']
        else:
            raise webob.exc.HTTPBadRequest(explanation=_(
               "body must be a dictionary containing 'changeOwner'"))

    @wsgi.action("changeOwner")
    def _change_owner(self, req, id, body):
        """
        Expected body (dict):
        {
            "changeOwner": {
                "user": new_owner,
                "tenant": new_tenant
            }
        }
        """
        context = req.environ['nova.context']
        AUTHORIZE(context)
        params = self._get_params(body)
        instance = self._compute_api.get(context, id)
        old_owner = instance['user_id']
        old_tenant = instance['project_id']
        new_owner = params.get('user', old_owner)
        new_tenant = params.get('tenant', old_tenant)
        if old_tenant == new_tenant and old_owner == new_owner:
            LOG.info('Instance %s is already owned by %s and in tenant %s, '
                     'changeOwner skipped', id, new_owner, new_tenant)
            return

        LOG.info('Instance %s: Changing owner to %s and moving to tenant %s',
                id, new_owner, new_tenant)
        vcpus = instance['vcpus']
        memory_mb = instance['memory_mb']
        root_gb = instance['root_gb']
        deltas = dict(instances=1, cores=vcpus, ram=memory_mb, root_gb=root_gb)

        resplus, resminus = None, None
        try:
            resplus = QUOTAS.reserve(context, user_id=new_owner,
                    project_id=new_tenant, **deltas)
            resminus = QUOTAS.reserve(context, user_id=old_owner,
                project_id=old_tenant, instances=-1, cores=-vcpus,
                ram=-memory_mb, root_gb=-root_gb)
            self._compute_api.update(context, instance, user_id=new_owner,
                project_id=new_tenant)
        except exception.OverQuota as exc:
            quotas = exc.kwargs['quotas']
            usages = exc.kwargs['usages']
            overs = exc.kwargs['overs']
            resource = overs[0]
            used = usages[resource]['in_use'] + usages[resource]['reserved']
            LOG.warn('Quota exceeded for user = %s, tenant = %s, tried to '
                     'change owner/tenant for instance %s, overs = %s.',
                     new_owner, new_tenant, id, overs)
            raise exception.TooManyInstances(overs=overs,
                                             req=deltas[resource],
                                             used=used,
                                             allowed=quotas[resource],
                                             resource=resource)
        except exception.InstanceNetworksNotAccessiblePf9 as exc:

            if resplus:
                QUOTAS.rollback(context, resplus, user_id=new_owner,
                                project_id=new_tenant)
            if resminus:
                QUOTAS.rollback(context, resminus, user_id=old_owner,
                                project_id=old_tenant)

            raise webob.exc.HTTPMethodNotAllowed(explanation=exc.format_message())

        QUOTAS.commit(context, resplus, user_id=new_owner,
                project_id=new_tenant)
        QUOTAS.commit(context, resminus, user_id=old_owner,
                project_id=old_tenant)

class Pf9_instance_ownership(extensions.ExtensionDescriptor):
    """PF9 Extension for change the owner and tenant for an instance."""
    name = "InstanceOwnership"
    alias = "OS-PF9-EXT-INSTANCE-OWNERSHIP"
    namespace = ("http://docs.pf9.org/compute/ext/instance-ownership/api/v2")
    updated = "2014-11-10T00:00:00+00:00"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(
                self, 'servers', InstanceOwnershipController())

        return [extension]
