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
class PluginDistributionRepositoryProvider:
    def __init__(self, plugin, repository_url_provider):
        self.plugin = plugin
        self.repository_url_provider = repository_url_provider

    def get_download_url(self, host):
        distribution_repository = self.plugin.variables["distribution"]["repository"]

        default_key = f"distribution.{distribution_repository}.remote.repo.url"
        return self.repository_url_provider.render_url_for_key(host, self.plugin.variables, default_key, mandatory=False)
