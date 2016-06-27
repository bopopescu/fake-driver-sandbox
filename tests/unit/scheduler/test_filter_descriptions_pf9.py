#
# Copyright (c) 2015, Platform9 Systems. All Rights Reserved
#
__author__ = 'Platform9'

"""
Tests for Platform9 additions to filters
"""

from nova.scheduler.filters import aggregate_instance_extra_specs
from nova.scheduler.filters import compute_filter
from nova.scheduler.filters import core_filter
from nova.scheduler.filters import compute_network_filter_pf9
from nova.scheduler.filters import image_props_filter
from nova.scheduler.filters import ram_filter
from nova.scheduler.filters import retry_filter

from nova import test

class FilterDescriptionTest(test.NoDBTestCase):
    def setUp(self):
        super(FilterDescriptionTest, self).setUp()
        # When enabling/adding new filters, add it to this test
        self._filters = [aggregate_instance_extra_specs.AggregateInstanceExtraSpecsFilter,
                         compute_filter.ComputeFilter,
                         core_filter.CoreFilter,
                         compute_network_filter_pf9.ComputeNetworkFilterPf9,
                         image_props_filter.ImagePropertiesFilter,
                         ram_filter.RamFilter,
                         retry_filter.RetryFilter
                         ]

    def test_filters_have_description(self):
        for filter in self._filters:
            self.assertNotEqual('', filter.description().strip())