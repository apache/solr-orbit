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
import os.path

from osbenchmark.builder.downloaders.downloader import Downloader
from osbenchmark.builder.utils.binary_keys import BinaryKeys
from osbenchmark.exceptions import ExecutorError


class DistributionDownloader(Downloader):
    def __init__(self, cluster_config, executor, path_manager, distribution_repository_provider):
        super().__init__(executor)
        self.logger = logging.getLogger(__name__)
        self.cluster_config = cluster_config
        self.path_manager = path_manager
        self.distribution_repository_provider = distribution_repository_provider

    def download(self, host):
        binary_path = self._fetch_binary(host)
        return {BinaryKeys.SOLR: binary_path}

    def _fetch_binary(self, host):
        download_url = self.distribution_repository_provider.get_download_url(host)
        distribution_path = self._create_distribution_path(host, download_url)
        version = self.cluster_config.variables["distribution"]["version"]

        is_binary_present = self._is_binary_present(host, distribution_path)
        is_cache_enabled = self.distribution_repository_provider.is_cache_enabled()

        if is_binary_present and is_cache_enabled:
            self.logger.info("Skipping download for version [%s]. Found existing binary at [%s].", version,
                             distribution_path)
        else:
            self._download(host, distribution_path, download_url, version)

        return distribution_path

    def _create_distribution_path(self, host, download_url):
        distribution_root_path = os.path.join(self.cluster_config.variables["node"]["root"]["dir"], "distributions")
        self.path_manager.create_path(host, distribution_root_path)

        distribution_binary_name = self.distribution_repository_provider.get_file_name_from_download_url(download_url)
        return os.path.join(distribution_root_path, distribution_binary_name)

    def _is_binary_present(self, host, distribution_path):
        try:
            self.executor.execute(host, f"test -f {distribution_path}")
            return True
        except ExecutorError:
            return False

    def _download(self, host, distribution_path, download_url, version):
        self.logger.info("Resolved download URL [%s] for version [%s]", download_url, version)
        self.logger.info("Starting download of distribution [%s]", version)

        try:
            self.executor.execute(host, f"curl -o {distribution_path} {download_url}")
        except ExecutorError as e:
            self.logger.exception("Exception downloading distribution for version [%s] from [%s].",
                                  version, download_url)
            raise e

        self.logger.info("Successfully downloaded distribution [%s].", version)
