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
import unittest.mock as mock
from unittest import TestCase

from solrorbit.builder.executors.local_shell_executor import LocalShellExecutor
from solrorbit.exceptions import ExecutorError


class LocalShellExecutorTests(TestCase):
    def setUp(self):
        self.executor = LocalShellExecutor()
        self.host = None
        self.command = None

    @mock.patch("solrorbit.utils.process.run_subprocess_with_output")
    def test_command_with_output(self, run_subprocess_with_output):
        run_subprocess_with_output.return_value = ["test", "output"]

        output = self.executor.execute(self.host, self.command, output=True)
        self.assertEqual(output, ["test", "output"])

    @mock.patch("solrorbit.utils.process.run_subprocess_with_logging")
    def test_command_with_logging_success(self, run_subprocess_with_logging):
        run_subprocess_with_logging.return_value = 0

        self.executor.execute(self.host, self.command)

    @mock.patch("solrorbit.utils.process.run_subprocess_with_logging")
    def test_command_with_logging_failure(self, run_subprocess_with_logging):
        run_subprocess_with_logging.return_value = 86

        with self.assertRaises(ExecutorError):
            self.executor.execute(self.host, self.command)
