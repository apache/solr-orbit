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

from solrorbit.builder.cluster_config import ClusterConfigInstance
from solrorbit.builder.utils.java_home_resolver import JavaHomeResolver


class JavaHomeResolverTests(TestCase):
    def setUp(self):
        self.host = None
        self.executor = Mock()
        self.java_home_resolver = JavaHomeResolver(self.executor)
        self.java_home_resolver.jdk_resolver = Mock()

        self.variables = {
            "system": {
                "runtime": {
                    "jdk": {
                        "version": "12,11,10,9,8"
                    }
                }
            }
        }
        self.cluster_config = ClusterConfigInstance("fake_cluster_config", "/path/to/root",
                                                                 ["/path/to/config"], variables=self.variables)

    def test_resolves_java_home_for_default_runtime_jdk(self):
        self.java_home_resolver.jdk_resolver.resolve_jdk_path.return_value = (12, "/opt/jdk12")
        major, java_home = self.java_home_resolver.resolve_java_home(self.host, self.cluster_config)

        self.assertEqual(major, 12)
        self.assertEqual(java_home, "/opt/jdk12")

    def test_resolves_java_home_for_specific_runtime_jdk(self):
        self.variables["system"]["runtime"]["jdk"]["version"] = "8"
        self.java_home_resolver.jdk_resolver.resolve_jdk_path.return_value = (8, "/opt/jdk8")
        major, java_home = self.java_home_resolver.resolve_java_home(self.host, self.cluster_config)

        self.assertEqual(major, 8)
        self.assertEqual(java_home, "/opt/jdk8")
        self.java_home_resolver.jdk_resolver.resolve_jdk_path.assert_called_with(None, [8])
