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

from solrorbit.builder.utils.path_manager import PathManager
from solrorbit.exceptions import ExecutorError


class PathManagerTest(TestCase):
    def setUp(self):
        self.host = None
        self.path = "fake"

        self.executor = Mock()
        self.path_manager = PathManager(self.executor)

    @mock.patch('solrorbit.utils.io.ensure_dir')
    def test_create_path(self, ensure_dir):
        self.path_manager.create_path(self.host, self.path)

        ensure_dir.assert_has_calls([
            mock.call(self.path)
        ])
        self.executor.execute.assert_has_calls([
            mock.call(self.host, f"mkdir -m 0777 -p {self.path}")
        ])

    @mock.patch('solrorbit.utils.io.ensure_dir')
    def test_create_path_no_local_copy(self, ensure_dir):
        self.path_manager.create_path(self.host, self.path)

        ensure_dir.assert_has_calls([])
        self.executor.execute.assert_has_calls([
            mock.call(self.host, f"mkdir -m 0777 -p {self.path}")
        ])

    def test_delete_valid_path(self):
        self.path_manager.delete_path(self.host, self.path)

        self.executor.execute.assert_has_calls([
            mock.call(self.host, f"rm -r {self.path}")
        ])

    def test_delete_invalid_path(self):
        self.path_manager.delete_path(self.host, "/")

        self.executor.execute.assert_has_calls([])

    def test_path_is_present(self):
        self.executor.execute.return_value = None

        is_path_present = self.path_manager.is_path_present(self.host, self.path)
        self.assertEqual(is_path_present, True)

    def test_path_is_not_present(self):
        self.executor.execute.side_effect = ExecutorError("fake")

        is_path_present = self.path_manager.is_path_present(self.host, self.path)
        self.assertEqual(is_path_present, False)
