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

from solrorbit.builder.installers.bare_installer import BareInstaller
from solrorbit.builder.models.host import Host
from solrorbit.builder.cluster_config import ClusterConfigInstance, BootstrapPhase


class BareInstallerTests(TestCase):
    def setUp(self):
        self.host = Host(name="fake", address="10.17.22.23", metadata={}, node=None)
        self.binaries = {}
        self.all_node_ips = ["10.17.22.22", "10.17.22.23"]

        self.test_run_root = "fake_root"
        self.node_id = "abdefg"
        self.cluster_name = "my-cluster"

        self.executor = Mock()
        self.preparer = Mock()
        self.preparer2 = Mock()

        self.cluster_config = ClusterConfigInstance(
            names="defaults",
            root_path="fake",
            config_paths=["/tmp"],
            variables={
                "test_run_root": self.test_run_root,
                "cluster_name": self.cluster_name,
                "node": {
                    "port": "8983"
                },
                "preserve_install": False
            }
        )
        self.installer = BareInstaller(self.cluster_config, self.executor, self.preparer)
        self.installer.config_applier = Mock()
        self.installer.java_home_resolver = Mock()

        self.preparer.prepare.return_value = "fake node"
        self.preparer.get_config_vars.return_value = {"fake": "config"}
        self.preparer.get_config_paths.return_value = ["/tmp"]
        self.preparer2.prepare.return_value = "second node"
        self.preparer2.get_config_vars.return_value = {"new": "var"}
        self.preparer2.get_config_paths.return_value = ["/fake"]
        self.installer.java_home_resolver.resolve_java_home.return_value = (None, "/path/to/java/home")

    def test_install_node(self):
        node = self.installer.install(self.host, self.binaries, self.all_node_ips)
        self.assertEqual(node, "fake node")

        self.preparer.prepare.assert_has_calls([
            mock.call(self.host, self.binaries)
        ])
        self.preparer.get_config_vars.assert_has_calls([
            mock.call(self.host, "fake node", self.all_node_ips)
        ])
        self.installer.config_applier.apply_configs.assert_has_calls([
            mock.call(self.host, "fake node", ["/tmp"], {"fake": "config"})
        ])
        self.installer.java_home_resolver.resolve_java_home.assert_has_calls([
            mock.call(self.host, self.cluster_config)
        ])
        self.preparer.invoke_install_hook.assert_has_calls([
            mock.call(self.host, BootstrapPhase.post_install, {"fake": "config"}, {"JAVA_HOME": "/path/to/java/home"})
        ])

    def test_install_no_java_home(self):
        self.installer.java_home_resolver.resolve_java_home.return_value = (None, None)

        self.installer.install(self.host, self.binaries, self.all_node_ips)

        self.preparer.invoke_install_hook.assert_has_calls([
            mock.call(self.host, BootstrapPhase.post_install, {"fake": "config"}, {})
        ])

    def test_multiple_nodes_installed(self):
        self.installer.preparers = [self.preparer, self.preparer2]

        with self.assertRaises(AssertionError):
            self.installer.install(self.host, self.binaries, self.all_node_ips)

    def test_no_nodes_installed(self):
        self.preparer.prepare.return_value = None

        with self.assertRaises(AssertionError):
            self.installer.install(self.host, self.binaries, self.all_node_ips)
