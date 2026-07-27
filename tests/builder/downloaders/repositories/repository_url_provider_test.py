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

from solrorbit.builder.downloaders.repositories.repository_url_provider import RepositoryUrlProvider
from solrorbit.exceptions import SystemSetupError


class RepositoryUrlProviderTest(TestCase):
    def setUp(self):
        self.template_renderer = Mock()
        self.artifact_variables_provider = Mock()

        self.host = None
        self.variables = {
            "distribution": {
                "version": "1.2.3"
            },
            "fake": {
                "url": "opensearch/{{VERSION}}/opensearch-{{VERSION}}-{{OSNAME}}-{{ARCH}}.tar.gz"
            }
        }
        self.url_key = "fake.url"

        self.repo_url_provider = RepositoryUrlProvider(self.template_renderer, self.artifact_variables_provider)

    def test_get_url(self):
        self.artifact_variables_provider.get_artifact_variables.return_value = {"fake": "vars"}

        self.repo_url_provider.render_url_for_key(self.host, self.variables, self.url_key)
        self.artifact_variables_provider.get_artifact_variables.assert_has_calls([
            mock.call(self.host, "1.2.3")
        ])
        self.template_renderer.render_template_string.assert_has_calls([
            mock.call("opensearch/{{VERSION}}/opensearch-{{VERSION}}-{{OSNAME}}-{{ARCH}}.tar.gz", {"fake": "vars"})
        ])

    def test_no_url_template_found(self):
        with self.assertRaises(SystemSetupError):
            self.repo_url_provider.render_url_for_key(self.host, self.variables, "not.real")

    def test_no_url_template_found_not_mandatory(self):
        url = self.repo_url_provider.render_url_for_key(self.host, self.variables, "not.real", False)
        self.assertEqual(url, None)
