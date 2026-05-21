# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

from osbenchmark.utils import convert


class DistributionRepositoryProvider:
    def __init__(self, cluster_config, repository_url_provider):
        self.logger = logging.getLogger(__name__)
        self.cluster_config = cluster_config
        self.repository_url_provider = repository_url_provider

    def get_download_url(self, host):
        distribution_repository = self.cluster_config.variables["distribution"]["repository"]
        url_key = f"distribution.{distribution_repository}_url"
        self.logger.info("key: [%s]", url_key)
        return self.repository_url_provider.render_url_for_key(host, self.cluster_config.variables, url_key)

    def get_file_name_from_download_url(self, download_url):
        return download_url[download_url.rfind("/") + 1:]

    def is_cache_enabled(self):
        distribution_repository = self.cluster_config.variables["distribution"]["repository"]
        is_cache_enabled = self.cluster_config.variables["distribution"][distribution_repository]["cache"]

        return convert.to_bool(is_cache_enabled)
