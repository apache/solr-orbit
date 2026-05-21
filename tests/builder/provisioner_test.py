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
# pylint: disable=protected-access

import os
import tempfile
import unittest.mock as mock
from unittest import TestCase

from osbenchmark.builder import provisioner, cluster_config

HOME_DIR = os.path.expanduser("~")


class BareProvisionerTests(TestCase):
    @mock.patch("glob.glob", lambda p: ["/opt/solr-9.0.0"])
    @mock.patch("osbenchmark.utils.io.decompress")
    @mock.patch("osbenchmark.utils.io.ensure_dir")
    @mock.patch("shutil.rmtree")
    def test_prepare_without_plugins(self, mock_rm, mock_ensure_dir, mock_decompress):
        apply_config_calls = []

        def null_apply_config(source_root_path, target_root_path, config_vars):
            apply_config_calls.append((source_root_path, target_root_path, config_vars))

        installer = provisioner.NodeInstaller(cluster_config=
        cluster_config.ClusterConfigInstance(
            names="unit-test-cluster-config-instance",
            root_path=None,
            config_paths=[HOME_DIR + "/.benchmark/benchmarks/cluster_configs/default/my-cluster-config-instance"],
            variables={"heap": "4g", "runtime.jdk": "8", "runtime.jdk.bundled": "true"}),
            java_home="/usr/local/javas/java8",
            node_name="benchmark-node-0",
            node_root_dir=HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest",
            all_node_ips=["10.17.22.22", "10.17.22.23"],
            all_node_names=["benchmark-node-0", "benchmark-node-1"],
            ip="10.17.22.23",
            http_port=8983)

        p = provisioner.BareProvisioner(os_installer=installer,
                                        apply_config=null_apply_config)

        node_config = p.prepare({"solr": "/opt/solr-9.0.0.tar.gz"})
        self.assertEqual("8", node_config.cluster_config_runtime_jdks)
        self.assertEqual("/opt/solr-9.0.0", node_config.binary_path)
        self.assertEqual(["/opt/solr-9.0.0/data"], node_config.data_paths)

        self.assertEqual(1, len(apply_config_calls))
        source_root_path, target_root_path, config_vars = apply_config_calls[0]

        self.assertEqual(HOME_DIR + "/.benchmark/benchmarks/cluster_configs/default/my-cluster-config-instance", source_root_path)
        self.assertEqual("/opt/solr-9.0.0", target_root_path)
        self.assertEqual({
            "cluster_settings": {
            },
            "heap": "4g",
            "runtime.jdk": "8",
            "runtime.jdk.bundled": "true",
            "cluster_name": "benchmark-provisioned-cluster",
            "node_name": "benchmark-node-0",
            "data_paths": ["/opt/solr-9.0.0/data"],
            "log_path": HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest/logs/server",
            "heap_dump_path": HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest/heapdump",
            "node_ip": "10.17.22.23",
            "network_host": "10.17.22.23",
            "http_port": "8983",
            "zookeeper_port": "9983",
            "all_node_ips": "[\"10.17.22.22\",\"10.17.22.23\"]",
            "all_node_names": "[\"benchmark-node-0\",\"benchmark-node-1\"]",
            "minimum_master_nodes": 2,
            "install_root_path": "/opt/solr-9.0.0"
        }, config_vars)

    class NoopHookHandler:
        def __init__(self, plugin):
            self.hook_calls = {}

        def can_load(self):
            return False

        def invoke(self, phase, variables, **kwargs):
            self.hook_calls[phase] = {
                "variables": variables,
                "kwargs": kwargs
            }


class NoopHookHandler:
    def __init__(self, component):
        self.hook_calls = {}

    def can_load(self):
        return False

    def invoke(self, phase, variables, **kwargs):
        self.hook_calls[phase] = {
            "variables": variables,
            "kwargs": kwargs,
        }


class NodeInstallerTests(TestCase):
    @mock.patch("glob.glob", lambda p: ["/install/solr-9.0.0"])
    @mock.patch("osbenchmark.utils.io.decompress")
    @mock.patch("osbenchmark.utils.io.ensure_dir")
    @mock.patch("shutil.rmtree")
    def test_prepare_default_data_paths(self, mock_rm, mock_ensure_dir, mock_decompress):
        installer = provisioner.NodeInstaller(cluster_config=cluster_config.ClusterConfigInstance(names="defaults",
                                                                    root_path=None,
                                                                    config_paths="/tmp"),
                                                       java_home="/usr/local/javas/java8",
                                                       node_name="benchmark-node-0",
                                                       all_node_ips=["10.17.22.22", "10.17.22.23"],
                                                       all_node_names=["benchmark-node-0", "benchmark-node-1"],
                                                       ip="10.17.22.23",
                                                       http_port=9200,
                                                       node_root_dir=HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest")

        installer.install("/data/builds/distributions")
        self.assertEqual(installer.os_home_path, "/install/solr-9.0.0")

        self.assertEqual({
            "cluster_name": "benchmark-provisioned-cluster",
            "node_name": "benchmark-node-0",
            "data_paths": ["/install/solr-9.0.0/data"],
            "log_path": HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest/logs/server",
            "heap_dump_path": HOME_DIR + "/.benchmark/benchmarks/test_runs/unittest/heapdump",
            "node_ip": "10.17.22.23",
            "network_host": "10.17.22.23",
            "http_port": "9200",
            "zookeeper_port": "10200",
            "all_node_ips": "[\"10.17.22.22\",\"10.17.22.23\"]",
            "all_node_names": "[\"benchmark-node-0\",\"benchmark-node-1\"]",
            "minimum_master_nodes": 2,
            "install_root_path": "/install/solr-9.0.0"
        }, installer.variables)

        self.assertEqual(installer.data_paths, ["/install/solr-9.0.0/data"])

    @mock.patch("glob.glob", lambda p: ["/install/solr-9.0.0"])
    @mock.patch("osbenchmark.utils.io.decompress")
    @mock.patch("osbenchmark.utils.io.ensure_dir")
    @mock.patch("shutil.rmtree")
    def test_prepare_user_provided_data_path(self, mock_rm, mock_ensure_dir, mock_decompress):
        installer = provisioner.NodeInstaller(cluster_config=cluster_config.ClusterConfigInstance(names="defaults",
                                                                    root_path=None,
                                                                    config_paths="/tmp",
                                                                    variables={"data_paths": "/tmp/some/data-path-dir"}),
                                                       java_home="/usr/local/javas/java8",
                                                       node_name="benchmark-node-0",
                                                       all_node_ips=["10.17.22.22", "10.17.22.23"],
                                                       all_node_names=["benchmark-node-0", "benchmark-node-1"],
                                                       ip="10.17.22.23",
                                                       http_port=9200,
                                                       node_root_dir="~/.benchmark/benchmarks/test_runs/unittest")

        installer.install("/data/builds/distributions")
        self.assertEqual(installer.os_home_path, "/install/solr-9.0.0")

        self.assertEqual({
            "cluster_name": "benchmark-provisioned-cluster",
            "node_name": "benchmark-node-0",
            "data_paths": ["/tmp/some/data-path-dir"],
            "log_path": "~/.benchmark/benchmarks/test_runs/unittest/logs/server",
            "heap_dump_path": "~/.benchmark/benchmarks/test_runs/unittest/heapdump",
            "node_ip": "10.17.22.23",
            "network_host": "10.17.22.23",
            "http_port": "9200",
            "zookeeper_port": "10200",
            "all_node_ips": "[\"10.17.22.22\",\"10.17.22.23\"]",
            "all_node_names": "[\"benchmark-node-0\",\"benchmark-node-1\"]",
            "minimum_master_nodes": 2,
            "install_root_path": "/install/solr-9.0.0"
        }, installer.variables)

        self.assertEqual(installer.data_paths, ["/tmp/some/data-path-dir"])

    def test_invokes_hook_with_java_home(self):
        installer = provisioner.NodeInstaller(cluster_config=cluster_config.ClusterConfigInstance(names="defaults",
                                                                    root_path="/tmp",
                                                                    config_paths="/tmp/templates",
                                                                    variables={"data_paths": "/tmp/some/data-path-dir"}),
                                                       java_home="/usr/local/javas/java8",
                                                       node_name="benchmark-node-0",
                                                       all_node_ips=["10.17.22.22", "10.17.22.23"],
                                                       all_node_names=["benchmark-node-0", "benchmark-node-1"],
                                                       ip="10.17.22.23",
                                                       http_port=9200,
                                                       node_root_dir="~/.benchmark/benchmarks/test_runs/unittest",
                                                       hook_handler_class=NoopHookHandler)

        self.assertEqual(0, len(installer.hook_handler.hook_calls))
        installer.invoke_install_hook(cluster_config.BootstrapPhase.post_install, {"foo": "bar"})
        self.assertEqual(1, len(installer.hook_handler.hook_calls))
        self.assertEqual({"foo": "bar"}, installer.hook_handler.hook_calls["post_install"]["variables"])
        self.assertEqual({"env": {"JAVA_HOME": "/usr/local/javas/java8"}},
                         installer.hook_handler.hook_calls["post_install"]["kwargs"])

    def test_invokes_hook_no_java_home(self):
        installer = provisioner.NodeInstaller(cluster_config=cluster_config.ClusterConfigInstance(names="defaults",
                                                                    root_path="/tmp",
                                                                    config_paths="/tmp/templates",
                                                                    variables={"data_paths": "/tmp/some/data-path-dir"}),
                                                       java_home=None,
                                                       node_name="benchmark-node-0",
                                                       all_node_ips=["10.17.22.22", "10.17.22.23"],
                                                       all_node_names=["benchmark-node-0", "benchmark-node-1"],
                                                       ip="10.17.22.23",
                                                       http_port=9200,
                                                       node_root_dir="~/.benchmark/benchmarks/test_runs/unittest",
                                                       hook_handler_class=NoopHookHandler)

        self.assertEqual(0, len(installer.hook_handler.hook_calls))
        installer.invoke_install_hook(cluster_config.BootstrapPhase.post_install, {"foo": "bar"})
        self.assertEqual(1, len(installer.hook_handler.hook_calls))
        self.assertEqual({"foo": "bar"}, installer.hook_handler.hook_calls["post_install"]["variables"])
        self.assertEqual({"env": {}}, installer.hook_handler.hook_calls["post_install"]["kwargs"])


class DockerProvisionerTests(TestCase):
    maxDiff = None
    @mock.patch("uuid.uuid4")
    def test_provisioning_with_defaults(self, uuid4):
        uuid4.return_value = "9dbc682e-d32a-4669-8fbe-56fb77120dd4"
        node_root_dir = tempfile.gettempdir()
        log_dir = os.path.join(node_root_dir, "logs", "server")
        heap_dump_dir = os.path.join(node_root_dir, "heapdump")
        data_dir = os.path.join(node_root_dir, "data", "9dbc682e-d32a-4669-8fbe-56fb77120dd4")

        benchmark_root = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, os.pardir, "osbenchmark"))

        c = cluster_config.ClusterConfigInstance("unit-test-cluster-config-instance", None, "/tmp", variables={
            "docker_image": "solr"
        })

        docker = provisioner.DockerProvisioner(cluster_config=c,
                                               node_name="benchmark-node-0",
                                               ip="10.17.22.33",
                                               http_port=38983,
                                               node_root_dir=node_root_dir,
                                               distribution_version="1.1.0",
                                               benchmark_root=benchmark_root)

        self.assertDictEqual({
            "cluster_name": "benchmark-provisioned-cluster",
            "node_name": "benchmark-node-0",
            "install_root_path": "/var/solr",
            "data_paths": ["/var/solr/data"],
            "log_path": "/var/solr/logs",
            "heap_dump_path": "/var/solr/heapdump",
            "discovery_type": "single-node",
            "network_host": "0.0.0.0",
            "http_port": "38983",
            "zookeeper_port": "39983",
            "cluster_settings": {
            },
            "docker_image": "solr"
        }, docker.config_vars)

        self.assertDictEqual({
            "solr_data_dir": data_dir,
            "solr_log_dir": log_dir,
            "solr_heap_dump_dir": heap_dump_dir,
            "solr_version": "1.1.0",
            "docker_image": "solr",
            "http_port": 38983,
            "mounts": {}
        }, docker.docker_vars(mounts={}))

        docker_cfg = docker._render_template_from_file(docker.docker_vars(mounts={}))

        self.assertEqual(
"""version: '3'
services:
  solr-node1:
    image: solr:1.1.0
    container_name: solr-node1
    labels:
      io.benchmark.description: "solr-benchmark"
    environment:
      - "SOLR_JAVA_OPTS=-Xms512m -Xmx512m"
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - %s:/var/solr/data
      - %s:/var/solr/logs
      - %s:/var/solr/heapdump
    ports:
      - 38983:8983
    networks:
      - solr-net
    healthcheck:
          test: curl -f http://localhost:8983/solr/admin/ping
          interval: 5s
          timeout: 2s
          retries: 10

volumes:
  solr-data1:
networks:
  solr-net:""" % (data_dir, log_dir, heap_dump_dir), docker_cfg)

    @mock.patch("uuid.uuid4")
    def test_provisioning_with_variables(self, uuid4):
        uuid4.return_value = "86f42ae0-5840-4b5b-918d-41e7907cb644"
        node_root_dir = tempfile.gettempdir()
        log_dir = os.path.join(node_root_dir, "logs", "server")
        heap_dump_dir = os.path.join(node_root_dir, "heapdump")
        data_dir = os.path.join(node_root_dir, "data", "86f42ae0-5840-4b5b-918d-41e7907cb644")

        benchmark_root = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, os.pardir, "osbenchmark"))

        c = cluster_config.ClusterConfigInstance("unit-test-cluster-config-instance", None, "/tmp", variables={
            "docker_image": "solr",
            "docker_mem_limit": "256m",
            "docker_cpu_count": 2
        })

        docker = provisioner.DockerProvisioner(cluster_config=c,
                                               node_name="benchmark-node-0",
                                               ip="10.17.22.33",
                                               http_port=38983,
                                               node_root_dir=node_root_dir,
                                               distribution_version="1.1.0",
                                               benchmark_root=benchmark_root)

        docker_cfg = docker._render_template_from_file(docker.docker_vars(mounts={}))

        self.assertEqual(
"""version: '3'
services:
  solr-node1:
    image: solr:1.1.0
    container_name: solr-node1
    labels:
      io.benchmark.description: "solr-benchmark"
    cpu_count: 2
    mem_limit: 256m
    environment:
      - "SOLR_JAVA_OPTS=-Xms512m -Xmx512m"
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - %s:/var/solr/data
      - %s:/var/solr/logs
      - %s:/var/solr/heapdump
    ports:
      - 38983:8983
    networks:
      - solr-net
    healthcheck:
          test: curl -f http://localhost:8983/solr/admin/ping
          interval: 5s
          timeout: 2s
          retries: 10

volumes:
  solr-data1:
networks:
  solr-net:""" % (data_dir, log_dir, heap_dump_dir), docker_cfg)


class CleanupTests(TestCase):
    @mock.patch("shutil.rmtree")
    @mock.patch("os.path.exists")
    def test_preserves(self, mock_path_exists, mock_rm):
        mock_path_exists.return_value = True

        provisioner.cleanup(
            preserve=True,
            install_dir="./benchmark/test_runs/install",
            data_paths=["./benchmark/test_runs/data"])

        self.assertEqual(mock_path_exists.call_count, 0)
        self.assertEqual(mock_rm.call_count, 0)

    @mock.patch("shutil.rmtree")
    @mock.patch("os.path.exists")
    def test_cleanup(self, mock_path_exists, mock_rm):
        mock_path_exists.return_value = True

        provisioner.cleanup(
            preserve=False,
            install_dir="./benchmark/test_runs/install",
            data_paths=["./benchmark/test_runs/data"])

        expected_dir_calls = [mock.call("/tmp/some/data-path-dir"), mock.call("/benchmark-root/workload/test_procedure/es-bin")]
        mock_path_exists.mock_calls = expected_dir_calls
        mock_rm.mock_calls = expected_dir_calls
