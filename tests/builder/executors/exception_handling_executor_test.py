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

from solrorbit.builder.executors.exception_handling_shell_executor import ExceptionHandlingShellExecutor
from solrorbit.exceptions import ExecutorError


class ExceptionHandlingShellExecutorTests(TestCase):
    def setUp(self):
        self.executor_impl = mock.Mock()
        self.executor_impl.execute.return_value = None
        self.executor_impl.copy.return_value = None

        self.executor = ExceptionHandlingShellExecutor(self.executor_impl)
        self.host = None
        self.command = None
        self.source = "/path/to/source"
        self.destination = "/path/to/dest"

    def test_success_executing_command(self):
        self.executor.execute(self.host, self.command)

    def test_failure_executing_command(self):
        self.executor_impl.execute.side_effect = Exception("error")

        with self.assertRaises(ExecutorError):
            self.executor.execute(self.host, self.command)
