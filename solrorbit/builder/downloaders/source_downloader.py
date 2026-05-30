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
import os

from solrorbit.builder.downloaders.downloader import Downloader
from solrorbit.builder.utils.binary_keys import BinaryKeys


class SourceDownloader(Downloader):
    def __init__(self, cluster_config, executor, source_repository_provider, binary_builder, template_renderer, artifact_variables_provider):
        super().__init__(executor)
        self.logger = logging.getLogger(__name__)
        self.cluster_config = cluster_config
        self.source_repository_provider = source_repository_provider
        self.binary_builder = binary_builder
        self.template_renderer = template_renderer
        self.artifact_variables_provider = artifact_variables_provider

    def download(self, host):
        source_path = self._get_source_path()
        self._fetch(host, source_path)

        artifact_variables = self.artifact_variables_provider.get_artifact_variables(host)
        self._prepare(host, artifact_variables)

        return {BinaryKeys.SOLR: self._get_zip_path(source_path, artifact_variables)}

    def _get_source_path(self):
        node_root_dir = self.cluster_config.variables["source"]["root"]["dir"]
        source_subdir = self.cluster_config.variables["source"]["solr"]["subdir"]
        return os.path.join(node_root_dir, source_subdir)

    def _fetch(self, host, source_path):
        plugin_remote_url = self.cluster_config.variables["source"]["remote"]["repo"]["url"]
        plugin_revision = self.cluster_config.variables["source"]["revision"]

        self.source_repository_provider.fetch_repository(host, plugin_remote_url, plugin_revision, source_path)

    def _prepare(self, host, artifact_variables):
        clean_command_template = self.cluster_config.variables["source"]["clean"]["command"]
        build_command_template = self.cluster_config.variables["source"]["build"]["command"]

        if self.binary_builder:
            self.binary_builder.build(
                host,
                [
                    self.template_renderer.render_template_string(clean_command_template, artifact_variables),
                    self.template_renderer.render_template_string(build_command_template, artifact_variables),
                ],
            )

    def _get_zip_path(self, source_path, artifact_variables):
        artifact_path_pattern_template = self.cluster_config.variables["source"]["artifact_path_pattern"]
        artifact_path_pattern = self.template_renderer.render_template_string(artifact_path_pattern_template, artifact_variables)

        return os.path.join(source_path, artifact_path_pattern)
