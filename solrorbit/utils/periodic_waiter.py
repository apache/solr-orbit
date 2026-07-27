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
from solrorbit import time


class PeriodicWaiter:
    def __init__(self, poll_interval, poll_timeout, clock=time.Clock):
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.clock = clock

    def wait(self, poll_function, *poll_function_args, **poll_function_kwargs):
        stop_watch = self.clock.stop_watch()
        stop_watch.start()

        while stop_watch.split_time() < self.poll_timeout:
            if poll_function(*poll_function_args, **poll_function_kwargs):
                return
            time.sleep(self.poll_interval)

        raise TimeoutError
