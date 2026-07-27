# SPDX-License-Identifier: Apache-2.0
#
# Originally developed by OpenSearch Contributors; licensed under the Apache License, Version 2.0.
# License header was absent in the original source; added when adopted into Apache Solr Orbit.
# Modified by Apache Solr contributors; see git log for details.
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import sys
from unittest import TestCase
from unittest.mock import Mock

from solrorbit.utils.periodic_waiter import PeriodicWaiter


class PeriodicWaiterTest(TestCase):
    def setUp(self):
        self.polling_function = Mock()

        stop_watch = IterationBasedStopWatch(max_iterations=2)
        clock = TestClock(stop_watch=stop_watch)

        self.periodic_waiter = PeriodicWaiter(0, 2, clock=clock)

    def test_success_before_timeout(self):
        self.polling_function.side_effect = [False, True]

        self.periodic_waiter.wait(self.polling_function)

    def test_timeout(self):
        self.polling_function.side_effect = [False, False]

        with self.assertRaises(TimeoutError):
            self.periodic_waiter.wait(self.polling_function)


class IterationBasedStopWatch:
    __test__ = False

    def __init__(self, max_iterations):
        self.iterations = 0
        self.max_iterations = max_iterations

    def start(self):
        self.iterations = 0

    def split_time(self):
        if self.iterations < self.max_iterations:
            self.iterations += 1
            return 0
        else:
            return sys.maxsize


class TestClock:
    __test__ = False

    def __init__(self, stop_watch):
        self._stop_watch = stop_watch

    def stop_watch(self):
        return self._stop_watch
