# Copyright (c)2016 Platform9 Systems
"""
Payload inspection middleware: Displays short JSON payloads in the Nova API log.
"""

import json
import logging

import webob.dec
import webob.exc
from nova import wsgi

LOG = logging.getLogger(__name__)

def bleep(js, profanity):
    """ Operating in-place, replace any matching objects in hierarchy with censor marks """
    if isinstance(js, dict):
        for thing, item in js.iteritems():
            if isinstance(item, dict):
                bleep(item, profanity)
            elif isinstance(item, str) or isinstance(item, unicode):
                if thing == profanity:
                    js [thing] = "******"

class PF9_PayloadInspector(wsgi.Middleware):

    def __init__(self, *args, **kwargs):
        super(PF9_PayloadInspector, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
       env = req.environ
       if env ['REQUEST_METHOD'] == "POST":
           req_id = ""
           if "openstack.request_id" in env:
               req_id = env["openstack.request_id"]
           if hasattr(req, "body"):
               length = len(req.body)
               if length > 1 and length < 4096:
                   try:
                       js = json.loads(req.body)
                       # remove CloudInit user_data, which can include passwords
                       bleep(js, "user_data")
                       LOG.info("%s Payload: %s" % (req_id, json.dumps(js)))
                   except:
                       LOG.info("%s Payload json parse failed" % req_id)
               else:
                   LOG.info("%s Payload is long, %d bytes" % (req_id, length))
       return self.application
