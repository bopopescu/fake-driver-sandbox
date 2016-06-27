# Copyright (c) 2014 Platform9 systems. All rights reserved

import logging
import webob

from nova import compute
from nova import db
from nova import exception
from nova import notifications
from nova import objects
from nova import quota
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _

__author__ = 'Platform9'

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
ALIAS = "OS-PF9-EXT-INSTANCE-OWNERSHIP"

authorize = extensions.os_compute_authorizer(ALIAS)

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
        authorize(context, action="changeOwner")

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

            # Update the instance record and send a state update notification
            # if task or vm state changed
            values = {"user_id": new_owner, "project_id": new_tenant}
            old_ref, instance_ref = db.instance_update_and_get_original(
                                       context, instance['uuid'], values)
            instance_obj = objects.Instance._from_db_object(context, objects.Instance(context), instance_ref)
            notifications.send_update(context, old_ref, instance_obj, service="api")

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

class InstanceOwnershipPf9(extensions.V21APIExtensionBase):
    """PF9 Extension for change the owner and tenant for an instance."""
    name = "InstanceOwnership"
    alias = ALIAS
    version = 1

    namespace = ("http://docs.pf9.org/compute/ext/instance-ownership/api/v21")
    updated = "2016-03-03T00:00:00+00:00"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(
                self, 'servers', InstanceOwnershipController())

        return [extension]

    def get_resources(self):
        return []
