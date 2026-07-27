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

from solrorbit.builder.downloaders.repositories.plugin_distribution_repository_provider import \
    PluginDistributionRepositoryProvider
from solrorbit.builder.cluster_config import PluginDescriptor


class PluginDistributionRepositoryProviderTest(TestCase):
    def setUp(self):
        self.host = None
        self.plugin = PluginDescriptor(name="my-plugin", variables={"distribution": {"repository": "release"}})
        self.repository_url_provider = Mock()
        self.plugin_distro_repo_provider = PluginDistributionRepositoryProvider(self.plugin, self.repository_url_provider)


    def test_get_plugin_url(self):
        self.plugin_distro_repo_provider.get_download_url(self.host)
        self.plugin_distro_repo_provider.repository_url_provider.render_url_for_key.assert_has_calls([
            mock.call(None, {"distribution": {"repository": "release"}}, "distribution.release.remote.repo.url", mandatory=False)
        ])
