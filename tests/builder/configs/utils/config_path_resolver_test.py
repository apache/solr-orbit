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

from solrorbit.builder.configs.utils.config_path_resolver import ConfigPathResolver
from solrorbit.exceptions import SystemSetupError


class ConfigPathResolverTest(TestCase):
    def setUp(self):
        self.config_type = "red"
        self.config_format_version = "36"

        self.cfg = Mock()
        self.config_path_resolver = ConfigPathResolver(self.cfg)

    @mock.patch('os.path.exists')
    def test_cluster_config_path_defined(self, path_exists):
        path_exists.return_value = True
        # opts("builder", "cluster_config.path")
        self.cfg.opts.return_value = "/path/to/configs"

        config_path = self.config_path_resolver.resolve_config_path(self.config_type, self.config_format_version)
        self.assertEqual(config_path, "/path/to/configs/red/v36")

    @mock.patch('solrorbit.utils.git.fetch')
    @mock.patch('solrorbit.utils.repo.BenchmarkRepository')
    @mock.patch('solrorbit.utils.repo.BenchmarkRepository.set_cluster_configs_dir')
    @mock.patch('os.path.exists')
    def test_cluster_config_path_not_defined(self, path_exists, set_repo, benchmark_repo, git_fetch):
        path_exists.return_value = True

        # opts("builder", "cluster_config.path"), opts("builder", "distribution.version"), opts("builder", "repository.name"),
        # opts("builder", "repository.revision"), opts("system", "offline.mode"), opts("cluster_configs", "%s.dir" % repo_name),
        # opts("node", "root.dir"), opts("builder", "cluster_config.repository.dir")
        self.cfg.opts.side_effect = [None, "1.0", "fake-repo", "fake-revision", False, "fake-repo.dir", "/root_dir", "repo_dir"]

        config_path = self.config_path_resolver.resolve_config_path(self.config_type, self.config_format_version)
        self.assertEqual(config_path, "/root_dir/repo_dir/fake-repo/red/v36")

    @mock.patch('os.path.exists')
    def test_cluster_config_path_does_not_exist(self, path_exists):
        path_exists.return_value = False
        # opts("builder", "cluster_config.path")
        self.cfg.opts.return_value = "/path/to/configs"

        with self.assertRaises(SystemSetupError):
            self.config_path_resolver.resolve_config_path(self.config_type, self.config_format_version)
