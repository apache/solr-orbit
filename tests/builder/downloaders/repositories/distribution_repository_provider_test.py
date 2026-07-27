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

from solrorbit.builder.downloaders.repositories.distribution_repository_provider import \
    DistributionRepositoryProvider
from solrorbit.builder.cluster_config import ClusterConfigInstance


class DistributionRepositoryProviderTest(TestCase):
    def setUp(self):
        self.host = None
        self.cluster_config = ClusterConfigInstance(names=None, config_paths=None, root_path=None, variables={
            "distribution": {
                "repository": "release",
                "release": {
                    "cache": True
                }
            }
        })
        self.repository_url_provider = Mock()
        self.os_distro_repo_provider = DistributionRepositoryProvider(self.cluster_config,
                                                                                self.repository_url_provider)

    def test_get_download_url(self):
        self.os_distro_repo_provider.get_download_url(self.host)
        self.os_distro_repo_provider.repository_url_provider.render_url_for_key.assert_has_calls([
            mock.call(None, self.cluster_config.variables, "distribution.release_url")
        ])

    def test_get_file_name(self):
        file_name = self.os_distro_repo_provider.get_file_name_from_download_url(
            "https://archive.apache.org/dist/solr/solr/9.10.1/solr-9.10.1.tgz")

        self.assertEqual(file_name, "solr-9.10.1.tgz")

    def test_is_cache_enabled_true(self):
        is_cache_enabled = self.os_distro_repo_provider.is_cache_enabled()
        self.assertEqual(is_cache_enabled, True)

    def test_is_cache_enabled_false(self):
        self.cluster_config.variables["distribution"]["release"]["cache"] = False
        is_cache_enabled = self.os_distro_repo_provider.is_cache_enabled()
        self.assertEqual(is_cache_enabled, False)
