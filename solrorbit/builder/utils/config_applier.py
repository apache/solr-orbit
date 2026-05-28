# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import os

from solrorbit.utils import io


class ConfigApplier:
    def __init__(self, executor, template_renderer, path_manager):
        self.logger = logging.getLogger(__name__)
        self.executor = executor
        self.template_renderer = template_renderer
        self.path_manager = path_manager

    def apply_configs(self, host, node, config_paths, config_vars):
        mounts = {}
        for config_path in config_paths:
            mounts.update(self._apply_config(host, config_path, node.binary_path, config_vars))

        return mounts

    def _apply_config(self, host, source_root_path, target_root_path, config_vars):
        mounts = {}

        for root, _, files in os.walk(source_root_path):
            relative_root = root[len(source_root_path) + 1:]
            absolute_target_root = os.path.join(target_root_path, relative_root)
            self.path_manager.create_path(host, absolute_target_root)

            for name in files:
                source_file = os.path.join(root, name)
                target_file = os.path.join(absolute_target_root, name)
                mounts[target_file] = os.path.join("/var/solr", relative_root, name)

                if io.is_plain_text(source_file):
                    self.logger.info("Reading config template file [%s] and writing to [%s].", source_file, target_file)
                    with open(target_file, mode="a", encoding="utf-8") as f:
                        f.write(self.template_renderer.render_template_file(root, config_vars, source_file))

                    self.executor.execute(host, f"cp {target_file} {target_file}")
                else:
                    self.logger.info("Treating [%s] as binary and copying as is to [%s].", source_file, target_file)
                    self.executor.execute(host, f"cp {source_file} {target_file}")

        return mounts
