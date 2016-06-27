# Copyright (c) 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Scheduler host filters
"""

from nova import filters


class BaseHostFilter(filters.BaseFilter):
    """Base class for host filters."""
    def _filter_one(self, obj, filter_properties, filter_errors={}):
        """Return True if the object passes the filter, otherwise False."""
        return self.host_passes(obj, filter_properties,
                                filter_errors=filter_errors)

    def host_passes(self, host_state, filter_properties, filter_errors={}):
        """Return True if the HostState passes the filter, otherwise False.
        Override this in a subclass.
        """
        raise NotImplementedError()


class HostFilterHandler(filters.BaseFilterHandler):
    def __init__(self):
        super(HostFilterHandler, self).__init__(BaseHostFilter)

    @classmethod
    def get_error_description(cls, filter_errors):
        """
        PF9 function: Collect filtering errors from all filters
        """
        msg = ""
        for class_obj, count in filter_errors.iteritems():
            msg = '\n'.join([msg, '{num} hosts failed with error: {error}'.\
                            format(num=count, error=class_obj.description())])
        return msg

def all_filters():
    """Return a list of filter classes found in this directory.

    This method is used as the default for available scheduler filters
    and should return a list of all filter classes available.
    """
    return HostFilterHandler().get_all_classes()
