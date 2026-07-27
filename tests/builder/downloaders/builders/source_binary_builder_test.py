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

from solrorbit.builder.downloaders.builders.source_binary_builder import SourceBinaryBuilder
from solrorbit.exceptions import BuildError, ExecutorError


class SourceBinaryBuilderTest(TestCase):
    def setUp(self):
        self.host = None
        self.build_commands = ["gradle build"]

        self.executor = Mock()
        self.path_manager = Mock()
        self.jdk_resolver = Mock()

        self.os_src_dir = "/fake/src/dir"
        self.build_jdk_version = 13
        self.log_dir = "/benchmark/logs"

        self.source_binary_builder = SourceBinaryBuilder(self.executor, self.path_manager, self.jdk_resolver,
                                                         self.os_src_dir, self.build_jdk_version, self.log_dir)

        self.jdk_resolver.resolve_jdk_path.return_value = (13, "/path/to/jdk")

    def test_build(self):
        self.source_binary_builder.build(self.host, self.build_commands)

        self.executor.execute.assert_has_calls([
            mock.call(self.host, "export JAVA_HOME=/path/to/jdk"),
            mock.call(self.host, "/fake/src/dir/gradle build > /benchmark/logs/build.log 2>&1")
        ])

    def test_build_with_src_dir_override(self):
        self.source_binary_builder.build(self.host, self.build_commands, "/override/src")

        self.executor.execute.assert_has_calls([
            mock.call(self.host, "export JAVA_HOME=/path/to/jdk"),
            mock.call(self.host, "/override/src/gradle build > /benchmark/logs/build.log 2>&1")
        ])

    def test_build_failure(self):
        # Set JAVA_HOME, execute build command
        self.executor.execute.side_effect = [None, ExecutorError("fake err")]

        with self.assertRaises(BuildError):
            self.source_binary_builder.build(self.host, self.build_commands)
