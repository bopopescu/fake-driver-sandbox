#
# Copyright (c) Platform9 Systems Inc, All rights reserved
#
__author__ = 'Platform9'

#
# Collect periodic resource statistics from hypervisor
#

from collections import deque
from threading import Lock


class Stat(object):

    # A set of utility functions to compute stats
    def compute_moving_avg(self, val=None):
        """Computes rolling average

        :return: rolling average from last n samples
        """
        if not val:
            return self._val / max(len(self._buf), 1)
        if len(self._buf) < self._num_samples:
            self._buf.append(val)
            self._val += val
        else:
            old_data = self._buf.popleft()
            self._buf.append(val)
            self._val -= old_data
            self._val += val
        return self._val / max(len(self._buf), 1)

    def compute_delta(self, val=None):
        """Computes moving delta

        :return: value accumulated in moving window
        """

        if not val:
            return self._buf[-1] - self._buf[0] if len(self._buf) > 2 \
                else 0

        if len(self._buf) > self._num_samples:
            self._buf.popleft()

        self._buf.append(val)
        return self._buf[-1] - self._buf[0]

    def compute_avg_delta(self, val=None):
        """Computes moving average with delta semantic

        :return: avg value of accumulated samples in moving window
        """
        delta = self.compute_delta(val)

        if len(self._buf) < self._num_samples:
            return 0

        return 1.0 * delta / len(self._buf)

    def compute_latest(self, val=None):
        """Computes latest seen value

        :return: latest stat value
        """
        if not val:
            return self._val
        self._val = val
        return self._val

    def compute_min(self, val=None):
        """Computes minimum value

        :return: min value seen so far
        """
        if not val:
            return self._val
        else:
            if self._val > val:
                self._val = val
            return self._val

    def compute_max(self, val=None):
        """Computes max value

        :return: maximum value seen so far
        """
        if not val:
            return self._val
        else:
            if self._val < val:
                self._val = val
            return self._val

    ROLLUP_TYPES = {'avg': compute_moving_avg,
                    'latest': compute_latest,
                    'min': compute_min,
                    'max': compute_max,
                    'delta': compute_delta,
                    'delta_avg': compute_avg_delta}
    MIN_INTERVAL_SEC = 5

    def __init__(self, name, stat_type, rollup_type,
                 duration_min, unit, sampling_interval_sec=60):
        self._name = name
        self._type = stat_type

        self._rollup = rollup_type.lower()
        assert self._rollup in self.ROLLUP_TYPES
        self._rollup_func = self.ROLLUP_TYPES[self._rollup]

        self._duration = duration_min * 60
        assert 5 * 60 <= self._duration <= 60 * 60

        self._sampling_sec = sampling_interval_sec
        assert self.MIN_INTERVAL_SEC < self._sampling_sec < self._duration

        self._num_samples = max(self._duration / self._sampling_sec, 1)

        self._buf = deque([], maxlen=self._num_samples)
        self._val = 0
        self._last_run = 0
        self._last_sample_time = 0
        self._unit = unit
        self._lock = Lock()

    def add_sample(self, val, current_time):
        """Collect and add stat sample

        :return: Latest rollup value
        """
        with self._lock:
            if current_time - self._last_run >= self._duration:
                self._last_run = current_time

            return self._rollup_func(self, val)

    def is_right_iteration(self, current_time):
        """Get indicator if this is right iteration to add/update stat

        :return: True if time is right to update stat false otherwise
        """
        return True if current_time - self._last_run >= self._sampling_sec \
            else False

    def did_rollover(self, current_time):
        """Returns indicator on whether stats rolled over since last
        invocation

        :return: True if rollover happened, False otherwise
        """

        with self._lock:
            rollover = False

            if current_time - self._last_sample_time > self._duration:
                rollover = True
                self._last_sample_time = current_time

        return rollover

    @property
    def rollup_val(self):
        """Get rollup value

        :return: Latest rollup value
        """
        with self._lock:
            return self._rollup_func(self, None)

    @property
    def unit(self):
        return self._unit

    @property
    def rollup_type(self):
        return self.rollup_type

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

