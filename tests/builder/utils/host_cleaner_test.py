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
from unittest import TestCase, mock
from unittest.mock import Mock

from solrorbit.builder.models.host import Host
from solrorbit.builder.models.node import Node
from solrorbit.builder.utils.host_cleaner import HostCleaner


class HostCleanerTest(TestCase):
    def setUp(self):
        self.node = Node(binary_path="/fake", data_paths=["/fake1", "/fake2"],
                         name=None, pid=None, telemetry=None, port=None, root_dir=None, log_path=None, heap_dump_path=None)
        self.host = Host(address="fake", name="fake", metadata={}, node=self.node)

        self.path_manager = Mock()
        self.host_cleaner = HostCleaner(self.path_manager)

    def test_cleanup(self):
        self.host_cleaner.cleanup(self.host, False)

        self.path_manager.delete_path.assert_has_calls([
            mock.call(self.host, "/fake1"),
            mock.call(self.host, "/fake2"),
            mock.call(self.host, "/fake")
        ])

    def test_cleanup_preserve_install(self):
        self.host_cleaner.cleanup(self.host, True)

        self.path_manager.delete_path.assert_has_calls([])
