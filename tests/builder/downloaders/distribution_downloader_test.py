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

from solrorbit.builder.downloaders.distribution_downloader import DistributionDownloader
from solrorbit.builder.cluster_config import ClusterConfigInstance
from solrorbit.exceptions import ExecutorError


class DistributionDownloaderTest(TestCase):
    def setUp(self):
        self.host = None

        self.executor = Mock()
        self.cluster_config = ClusterConfigInstance(names="fake", root_path="also fake", config_paths="fake2", variables={
            "node": {
                "root": {
                    "dir": "/fake/dir/for/download"
                }
            },
            "distribution": {
                "version": "1.2.3"
            }
        })

        self.path_manager = Mock()
        self.distribution_repository_provider = Mock()
        self.os_distro_downloader = DistributionDownloader(self.cluster_config, self.executor, self.path_manager,
                                                                     self.distribution_repository_provider)


        self.os_distro_downloader.distribution_repository_provider.get_download_url.return_value = "https://fake/download.tar.gz"
        self.os_distro_downloader.distribution_repository_provider.get_file_name_from_download_url.return_value = "my-distro"
        self.os_distro_downloader.distribution_repository_provider.is_cache_enabled.return_value = True

    def test_download_distro(self):
        # Check if file exists, download via curl
        self.executor.execute.side_effect = [ExecutorError("file doesn't exist"), None]

        binary_map = self.os_distro_downloader.download(self.host)
        self.assertEqual(binary_map, {"solr": "/fake/dir/for/download/distributions/my-distro"})

        self.executor.execute.assert_has_calls([
            mock.call(self.host, "test -f /fake/dir/for/download/distributions/my-distro"),
            mock.call(self.host, "curl -o /fake/dir/for/download/distributions/my-distro https://fake/download.tar.gz")
        ])

    def test_download_distro_exists_and_cache_enabled(self):
        # Check if file exists, download via curl
        self.executor.execute.side_effect = [None]

        binary_map = self.os_distro_downloader.download(self.host)
        self.assertEqual(binary_map, {"solr": "/fake/dir/for/download/distributions/my-distro"})

        self.executor.execute.assert_has_calls([
            mock.call(self.host, "test -f /fake/dir/for/download/distributions/my-distro")
        ])

    def test_download_distro_exists_and_cache_disabled(self):
        self.os_distro_downloader.distribution_repository_provider.is_cache_enabled.return_value = False
        # Check if file exists, download via curl
        self.executor.execute.side_effect = [None, None]

        binary_map = self.os_distro_downloader.download(self.host)
        self.assertEqual(binary_map, {"solr": "/fake/dir/for/download/distributions/my-distro"})

        self.executor.execute.assert_has_calls([
            mock.call(self.host, "test -f /fake/dir/for/download/distributions/my-distro"),
            mock.call(self.host, "curl -o /fake/dir/for/download/distributions/my-distro https://fake/download.tar.gz")
        ])
