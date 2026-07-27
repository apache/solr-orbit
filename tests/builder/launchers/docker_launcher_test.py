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
# pylint: disable=protected-access

from unittest import TestCase, mock
from unittest.mock import Mock

from solrorbit import telemetry
from solrorbit.builder import cluster
from solrorbit.builder.launchers.docker_launcher import DockerLauncher
from solrorbit.builder.provisioner import NodeConfiguration


class DockerLauncherTests(TestCase):
    def setUp(self):
        self.shell_executor = Mock()
        self.metrics_store = Mock()

        self.launcher = DockerLauncher(None, self.shell_executor, self.metrics_store)
        self.launcher.waiter = Mock()

        self.host = None
        self.node_config = NodeConfiguration(build_type="docker",
                                        cluster_config_runtime_jdks="12,11",
                                        ip="127.0.0.1", node_name="testnode",
                                        node_root_path="/tmp", binary_path="/bin",
                                        data_paths="/tmp")

    def test_starts_container_successfully(self):
        # [Start container (from docker-compose up), Docker container id (from docker-compose ps),
        self.shell_executor.execute.side_effect = [None, ["de604d0d"]]
        self.launcher.waiter.wait.return_value = None

        nodes = self.launcher.start(self.host, [self.node_config])
        self.assertEqual(1, len(nodes))
        node = nodes[0]

        self.assertEqual(None, node.pid)
        self.assertEqual("/bin", node.binary_path)
        self.assertEqual("127.0.0.1", node.host_name)
        self.assertEqual("testnode", node.node_name)
        self.assertIsNotNone(node.telemetry)

        self.shell_executor.execute.assert_has_calls([
            mock.call(self.host, "docker-compose -f /bin/docker-compose.yml up -d"),
            mock.call(self.host, "docker-compose -f /bin/docker-compose.yml ps -q", output=True),
        ])

    def test_container_not_started(self):
        # [Start container (from docker-compose up), Docker container id (from docker-compose ps),
        self.shell_executor.execute.side_effect = [None, ["de604d0d"]]
        self.launcher.waiter.wait.side_effect = TimeoutError

        with self.assertRaises(TimeoutError):
            self.launcher.start(self.host, [self.node_config])

    @mock.patch("solrorbit.telemetry.add_metadata_for_node")
    def test_stops_container_successfully_with_metrics_store(self, add_metadata_for_node):
        nodes = [cluster.Node(0, "/bin", "127.0.0.1", "testnode", telemetry.Telemetry())]
        self.launcher.stop(self.host, nodes)

        add_metadata_for_node.assert_called_once_with(self.metrics_store, "testnode", "127.0.0.1")
        self.shell_executor.execute.assert_called_once_with(self.host, "docker-compose -f /bin/docker-compose.yml down")

    @mock.patch("solrorbit.telemetry.add_metadata_for_node")
    def test_stops_container_when_no_metrics_store_is_provided(self, add_metadata_for_node):
        self.launcher.metrics_store = None

        nodes = [cluster.Node(0, "/bin", "127.0.0.1", "testnode", telemetry.Telemetry())]
        self.launcher.stop(self.host, nodes)

        self.assertEqual(0, add_metadata_for_node.call_count)
        self.shell_executor.execute.assert_called_once_with(self.host, "docker-compose -f /bin/docker-compose.yml down")

    def test_container_not_healthy(self):
        self.shell_executor.execute.return_value = []
        output = self.launcher._is_container_healthy(self.host, "de604d0d")

        self.assertEqual(output, False)
        self.shell_executor.execute.assert_has_calls([
            mock.call(self.host, 'docker ps -a --filter "id=de604d0d" --filter "status=running" --filter "health=healthy" -q', output=True)
        ])

    def test_container_healthy(self):
        self.shell_executor.execute.return_value = ["We have a container"]
        output = self.launcher._is_container_healthy(self.host, "de604d0d")

        self.assertEqual(output, True)
        self.shell_executor.execute.assert_has_calls([
            mock.call(self.host, 'docker ps -a --filter "id=de604d0d" --filter "status=running" --filter "health=healthy" -q', output=True)
        ])
