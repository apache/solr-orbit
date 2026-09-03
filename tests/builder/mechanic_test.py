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

import unittest.mock as mock
from unittest import TestCase

from solrorbit import client, config, exceptions
from solrorbit.builder import builder
from solrorbit.utils import opts, versions


class HostHandlingTests(TestCase):
    @mock.patch("solrorbit.utils.net.resolve")
    def test_converts_valid_hosts(self, resolver):
        resolver.side_effect = ["127.0.0.1", "10.16.23.5", "11.22.33.44"]

        hosts = [
            {"host": "127.0.0.1", "port": 8983},
            # also applies default port if none given
            {"host": "10.16.23.5"},
            {"host": "site.example.com", "port": 8983},
        ]

        self.assertEqual([
            ("127.0.0.1", 8983),
            ("10.16.23.5", 8983),
            ("11.22.33.44", 8983),
        ], builder.to_ip_port(hosts))

    @mock.patch("solrorbit.utils.net.resolve")
    def test_rejects_hosts_with_unexpected_properties(self, resolver):
        resolver.side_effect = ["127.0.0.1", "10.16.23.5", "11.22.33.44"]

        hosts = [
            {"host": "127.0.0.1", "port": 8983, "ssl": True},
            {"host": "10.16.23.5", "port": 10983},
            {"host": "site.example.com", "port": 8983},
        ]

        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            builder.to_ip_port(hosts)
        self.assertEqual("When specifying nodes to be managed by "
                         "solr-orbit you can only supply hostname:port pairs (e.g. 'localhost:8983'), "
                         "any additional options cannot be supported.", ctx.exception.args[0])

    def test_groups_nodes_by_host(self):
        ip_port = [
            ("127.0.0.1", 9200),
            ("127.0.0.1", 9200),
            ("127.0.0.1", 9200),
            ("10.16.23.5", 9200),
            ("11.22.33.44", 9200),
            ("11.22.33.44", 9200),
        ]

        self.assertDictEqual(
            {
                ("127.0.0.1", 9200): [0, 1, 2],
                ("10.16.23.5", 9200): [3],
                ("11.22.33.44", 9200): [4, 5],

            }, builder.nodes_by_host(ip_port)
        )

    def test_extract_all_node_ips(self):
        ip_port = [
            ("127.0.0.1", 9200),
            ("127.0.0.1", 9200),
            ("127.0.0.1", 9200),
            ("10.16.23.5", 9200),
            ("11.22.33.44", 9200),
            ("11.22.33.44", 9200),
        ]
        self.assertSetEqual({"127.0.0.1", "10.16.23.5", "11.22.33.44"},
                            builder.extract_all_node_ips(ip_port))


class BuilderTests(TestCase):
    class Node:
        def __init__(self, node_name):
            self.node_name = node_name

    class TestLauncher:
        def __init__(self):
            self.started = False

        def start(self, node_configs):
            self.started = True
            return [BuilderTests.Node("benchmark-node-{}".format(n)) for n in range(len(node_configs))]

        def stop(self, nodes, metrics_store):
            self.started = False

    # We stub irrelevant methods for the test
    class TestBuilder(builder.Builder):
        def _current_test_run(self):
            return "test_run 17"

        def _add_results(self, current_test_run, node):
            pass

    @mock.patch("solrorbit.builder.provisioner.cleanup")
    def test_start_stop_nodes(self, cleanup):
        supplier = lambda: "/home/user/src/elasticsearch/es.tar.gz"
        provisioners = [mock.Mock(), mock.Mock()]
        launcher = BuilderTests.TestLauncher()
        cfg = config.Config()
        cfg.add(config.Scope.application, "system", "test_run.id", "17")
        cfg.add(config.Scope.application, "builder", "preserve.install", False)
        metrics_store = mock.Mock()
        m = BuilderTests.TestBuilder(cfg, metrics_store, supplier, provisioners, launcher)
        m.start_engine()
        self.assertTrue(launcher.started)
        for p in provisioners:
            self.assertTrue(p.prepare.called)

        m.stop_engine()
        self.assertFalse(launcher.started)
        self.assertEqual(cleanup.call_count, 2)


class ClusterDistributionVersionTests(TestCase):
    @staticmethod
    def cfg_for(hosts="localhost:8983"):
        cfg = config.Config()
        cfg.add(config.Scope.application, "client", "hosts", opts.TargetHosts(hosts))
        cfg.add(config.Scope.application, "client", "options", opts.ClientOptions("timeout:60"))
        return cfg

    @staticmethod
    def factory_returning(client_instance):
        return lambda hosts, client_options: mock.Mock(create=lambda: client_instance)

    def test_reads_the_version_from_the_cluster(self):
        solr_client = mock.create_autospec(client.SolrClient, instance=True)
        solr_client.get_version.return_value = "10.0.0"

        version = builder.cluster_distribution_version(self.cfg_for(), client_factory=self.factory_returning(solr_client))

        self.assertEqual("10.0.0", version)
        solr_client.get_version.assert_called_once_with()

    def test_selects_the_workload_branch_of_the_actual_major(self):
        # The version is not informational: WorkloadRepository.update feeds it to versions.best_match,
        # so a wrong value benchmarks the cluster with another major's workloads.
        solr_client = mock.create_autospec(client.SolrClient, instance=True)
        solr_client.get_version.return_value = "10.0.0"

        version = builder.cluster_distribution_version(self.cfg_for(), client_factory=self.factory_returning(solr_client))

        self.assertEqual("10", versions.best_match(["main", "9", "10"], version))

    def test_fails_instead_of_guessing_when_the_cluster_cannot_be_reached(self):
        solr_client = mock.create_autospec(client.SolrClient, instance=True)
        solr_client.get_version.side_effect = client.SolrClientError("connection refused")

        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            builder.cluster_distribution_version(self.cfg_for(), client_factory=self.factory_returning(solr_client))

        self.assertIn("--distribution-version", str(ctx.exception))
        self.assertIn("connection refused", str(ctx.exception))

    def test_returns_none_for_a_non_solr_client(self):
        self.assertIsNone(
            builder.cluster_distribution_version(self.cfg_for(), client_factory=self.factory_returning(mock.Mock()))
        )
