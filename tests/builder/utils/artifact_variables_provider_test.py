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

from solrorbit.builder.utils.artifact_variables_provider import ArtifactVariablesProvider


class ArtifactVariablesProviderTest(TestCase):
    def setUp(self):
        self.host = None

        self.executor = Mock()
        self.artifact_variables_provider = ArtifactVariablesProvider(self.executor)

    def test_x86(self):
        self.executor.execute.side_effect = [["Linux"], ["x86_64"]]
        variables = self.artifact_variables_provider.get_artifact_variables(self.host)

        self.assertEqual(variables, {
            "VERSION": None,
            "OSNAME": "linux",
            "ARCH": "x64"
        })

    def test_arm(self):
        self.executor.execute.side_effect = [["Linux"], ["aarch64"]]
        variables = self.artifact_variables_provider.get_artifact_variables(self.host)

        self.assertEqual(variables, {
            "VERSION": None,
            "OSNAME": "linux",
            "ARCH": "arm64"
        })

    def test_version_supplied(self):
        self.executor.execute.side_effect = [["Linux"], ["aarch64"]]
        variables = self.artifact_variables_provider.get_artifact_variables(self.host, "1.23")

        self.assertEqual(variables, {
            "VERSION": "1.23",
            "OSNAME": "linux",
            "ARCH": "arm64"
        })
