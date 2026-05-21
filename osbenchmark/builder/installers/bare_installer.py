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

from osbenchmark.builder.installers.installer import Installer
from osbenchmark.builder.cluster_config import BootstrapPhase
from osbenchmark.builder.utils.config_applier import ConfigApplier
from osbenchmark.builder.utils.java_home_resolver import JavaHomeResolver
from osbenchmark.builder.utils.path_manager import PathManager
from osbenchmark.builder.utils.template_renderer import TemplateRenderer


class BareInstaller(Installer):
    def __init__(self, cluster_config, executor, preparers):
        super().__init__(executor)
        self.cluster_config = cluster_config
        if isinstance(preparers, list):
            self.preparers = preparers
        else:
            self.preparers = [preparers]
        self.template_renderer = TemplateRenderer()
        self.path_manager = PathManager(executor)
        self.config_applier = ConfigApplier(executor, self.template_renderer, self.path_manager)
        self.java_home_resolver = JavaHomeResolver(executor)

    def install(self, host, binaries, all_node_ips):
        preparer_to_node = self._prepare_nodes(host, binaries)
        config_vars = self._get_config_vars(host, preparer_to_node, all_node_ips)
        self._apply_configs(host, preparer_to_node, config_vars)
        self._invoke_install_hooks(host, config_vars)

        return self._get_node(preparer_to_node)

    def _prepare_nodes(self, host, binaries):
        preparer_to_node = {}
        for preparer in self.preparers:
            preparer_to_node[preparer] = preparer.prepare(host, binaries)

        return preparer_to_node

    def _get_config_vars(self, host, preparer_to_node, all_node_ips):
        config_vars = {}

        for preparer, node in preparer_to_node.items():
            config_vars.update(preparer.get_config_vars(host, node, all_node_ips))

        return config_vars

    def _apply_configs(self, host, preparer_to_node, config_vars):
        for preparer, node in preparer_to_node.items():
            self.config_applier.apply_configs(host, node, preparer.get_config_paths(), config_vars)

    def _invoke_install_hooks(self, host, config_vars):
        _, java_home = self.java_home_resolver.resolve_java_home(host, self.cluster_config)

        env = {}
        if java_home:
            env["JAVA_HOME"] = java_home

        config_vars_copy = config_vars.copy()
        for preparer in self.preparers:
            preparer.invoke_install_hook(host, BootstrapPhase.post_install, config_vars_copy, env)

    def _get_node(self, preparer_to_node):
        nodes_list = list(filter(lambda node: node is not None, preparer_to_node.values()))

        assert len(nodes_list) == 1, f"Exactly one node must be provisioned per host, but found nodes: {nodes_list}"

        return nodes_list[0]

    def cleanup(self, host):
        for preparer in self.preparers:
            preparer.cleanup(host)
