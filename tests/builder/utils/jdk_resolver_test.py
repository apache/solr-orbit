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
from unittest import TestCase
from unittest.mock import Mock

from solrorbit.builder.utils.jdk_resolver import JdkResolver
from solrorbit.exceptions import SystemSetupError


class JdkResolverTests(TestCase):
    def setUp(self):
        self.host = None
        self.executor = Mock()
        self.jdk_resolver = JdkResolver(self.executor)

    def test_success_pre_java_9(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [["JAVA7_HOME=/fake/path"], ["java.vm.specification.version = 1.7.0"]]

        _, jdk_path = self.jdk_resolver.resolve_jdk_path(self.host, 7)
        self.assertEqual("/fake/path", jdk_path)

    def test_success_post_java_8(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [["JAVA9_HOME=/fake/path"], ["java.vm.specification.version = 9"]]

        _, jdk_path = self.jdk_resolver.resolve_jdk_path(self.host, 9)
        self.assertEqual("/fake/path", jdk_path)

    def test_generic_java_home_matches(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [["JAVA_HOME=/fake/path"], ["java.vm.specification.version = 9"]]

        _, jdk_path = self.jdk_resolver.resolve_jdk_path(self.host, 9)
        self.assertEqual("/fake/path", jdk_path)

    def test_multiple_majors(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version x 2
        self.executor.execute.side_effect = [
            ["JAVA_HOME=/fake/path", "JAVA14_HOME=/another/fake/path"], ["java.vm.specification.version = 14"],
            ["java.vm.specification.version = 9"]
        ]

        _, jdk_path = self.jdk_resolver.resolve_jdk_path(self.host, [8, 14, 16])
        self.assertEqual("/another/fake/path", jdk_path)

    def test_no_matching_version(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [["JAVA_HOME=/fake/path"], ["java.vm.specification.version = 9"]]

        with self.assertRaises(SystemSetupError):
            self.jdk_resolver.resolve_jdk_path(self.host, 10)

    def test_no_java_home_set(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [[]]

        with self.assertRaises(SystemSetupError):
            self.jdk_resolver.resolve_jdk_path(self.host, 10)

    def test_version_does_not_match_env_var_name(self):
        # printenv, $JAVA_HOME -XshowSettings:properties -version
        self.executor.execute.side_effect = [["JAVA8_HOME=/fake/path"], ["java.vm.specification.version = 9"]]

        with self.assertRaises(SystemSetupError):
            self.jdk_resolver.resolve_jdk_path(self.host, 8)
