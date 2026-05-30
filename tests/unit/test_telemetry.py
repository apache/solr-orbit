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

"""Unit tests for opt-in telemetry devices in solrorbit/telemetry.py"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from solrorbit.telemetry import (
    ClusterEnvironmentInfo,
    FlightRecorder,
    Gc,
    Heapdump,
    JitCompiler,
    SegmentStats,
    ShardStats,
    ShardStatsRecorder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_client(base_url="http://localhost:8983"):
    """Return a mock SolrAdminClient with a shared session."""
    client = MagicMock()
    client.base_url = base_url
    session = MagicMock()
    client._get_session.return_value = session
    return client, session


def _make_metrics_store():
    """Return a MagicMock metrics store and a dict capturing stored values."""
    stored = {}
    store = MagicMock()
    store.put_value_cluster_level = MagicMock(side_effect=lambda name, value, unit="": stored.update({name: value}))
    return store, stored


# ---------------------------------------------------------------------------
# T139: SegmentStats (Luke API)
# ---------------------------------------------------------------------------


class TestSegmentStats(unittest.TestCase):
    def _make_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    def test_segment_stats_luke_success(self):
        """SegmentStats writes segment data from Luke API to log file."""
        with tempfile.TemporaryDirectory() as log_root:
            admin_client = MagicMock()
            admin_client.list_collections.return_value = ["my_coll"]
            admin_client.get_luke_stats.return_value = {
                "numDocs": 1000,
                "maxDoc": 1001,
                "deletedDocs": 1,
                "segmentCount": 5,
                "sizeInBytes": 204800,
            }
            device = SegmentStats(log_root=log_root, admin_client=admin_client)
            device.on_benchmark_stop()

            stats_file = os.path.join(log_root, "segment_stats.log")
            self.assertTrue(os.path.exists(stats_file), "segment_stats.log should be created")
            content = open(stats_file).read()
            self.assertIn("numDocs", content)
            self.assertIn("my_coll", content)
            self.assertIn("1000", content)

    def test_segment_stats_luke_failure_graceful(self):
        """SegmentStats swallows Luke API errors without propagating exceptions."""
        with tempfile.TemporaryDirectory() as log_root:
            admin_client = MagicMock()
            admin_client.list_collections.return_value = ["bad_coll"]
            admin_client.get_luke_stats.side_effect = Exception("HTTP 500")
            device = SegmentStats(log_root=log_root, admin_client=admin_client)
            # Should not raise
            device.on_benchmark_stop()

    def test_segment_stats_connection_error_graceful(self):
        """SegmentStats swallows connection errors without propagating exceptions."""
        with tempfile.TemporaryDirectory() as log_root:
            admin_client = MagicMock()
            admin_client.list_collections.side_effect = ConnectionError("refused")
            device = SegmentStats(log_root=log_root, admin_client=admin_client)
            # Should not raise
            device.on_benchmark_stop()


# ---------------------------------------------------------------------------
# T140: ShardStats (CLUSTERSTATUS + Core STATUS)
# ---------------------------------------------------------------------------

CLUSTERSTATUS_RESPONSE = {
    "cluster": {
        "liveNodes": ["127.0.0.1:8983_solr"],
        "collections": {
            "my_coll": {
                "shards": {
                    "shard1": {
                        "replicas": {
                            "core_node1": {
                                "state": "active",
                                "leader": "true",
                                "core": "my_coll_shard1_replica_n1",
                                "base_url": "http://localhost:8983/solr",
                            }
                        }
                    }
                }
            }
        },
    }
}

CORE_STATUS_RESPONSE = {"status": {"my_coll_shard1_replica_n1": {"index": {"numDocs": 500, "sizeInBytes": 10240}}}}


class TestShardStats(unittest.TestCase):
    def _make_session_resp(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    def test_shard_stats_solrcloud_starts_sampler(self):
        """ShardStats starts a sampler thread when CLUSTERSTATUS shows collections."""
        admin_client, _ = _make_admin_client()
        metrics_store, _ = _make_metrics_store()
        admin_client.get_clusterstatus.return_value = CLUSTERSTATUS_RESPONSE

        device = ShardStats(telemetry_params={}, admin_client=admin_client, metrics_store=metrics_store)
        device.on_benchmark_start()

        self.assertEqual(1, len(device.samplers))
        # cleanup
        device.on_benchmark_stop()

    def test_shard_stats_standalone_skipped(self):
        """ShardStats skips silently when CLUSTERSTATUS has no cluster.collections."""
        admin_client, _ = _make_admin_client()
        metrics_store, _ = _make_metrics_store()
        admin_client.get_clusterstatus.return_value = {"responseHeader": {}}

        device = ShardStats(telemetry_params={}, admin_client=admin_client, metrics_store=metrics_store)
        device.on_benchmark_start()

        self.assertEqual(0, len(device.samplers), "No samplers should be created for standalone Solr")

    def test_shard_stats_recorder_emits_metrics(self):
        """ShardStatsRecorder polls CLUSTERSTATUS and Core STATUS and emits metrics."""
        admin_client, _ = _make_admin_client()
        metrics_store, stored = _make_metrics_store()

        admin_client.get_clusterstatus.return_value = CLUSTERSTATUS_RESPONSE
        admin_client.get_core_status.return_value = {"index": {"numDocs": 500, "sizeInBytes": 10240}}

        recorder = ShardStatsRecorder(admin_client=admin_client, metrics_store=metrics_store, sample_interval=60)
        recorder.record()

        self.assertIn("shard_shard1_num_docs", stored)
        self.assertEqual(500, stored["shard_shard1_num_docs"])
        self.assertIn("shard_shard1_size_bytes", stored)
        self.assertEqual(10240, stored["shard_shard1_size_bytes"])

    def test_shard_stats_connection_error_graceful(self):
        """ShardStatsRecorder swallows connection errors."""
        admin_client, _ = _make_admin_client()
        metrics_store, _ = _make_metrics_store()
        admin_client.get_clusterstatus.side_effect = ConnectionError("refused")

        recorder = ShardStatsRecorder(admin_client=admin_client, metrics_store=metrics_store, sample_interval=60)
        # Should not raise
        recorder.record()

    def test_shard_stats_invalid_interval(self):
        """ShardStats raises SystemSetupError for non-positive sample interval."""
        from solrorbit.exceptions import SystemSetupError

        admin_client, _ = _make_admin_client()
        metrics_store, _ = _make_metrics_store()
        with self.assertRaises(SystemSetupError):
            ShardStats(
                telemetry_params={"shard-stats-sample-interval": 0},
                admin_client=admin_client,
                metrics_store=metrics_store,
            )


# ---------------------------------------------------------------------------
# T141: ClusterEnvironmentInfo (/api/node/system)
# ---------------------------------------------------------------------------

SYSTEM_INFO_RESPONSE = {
    "lucene": {"solr-spec-version": "9.7.0"},
    "jvm": {"version": "21.0.1", "name": "OpenJDK 21"},
    "system": {"availableProcessors": 8},
}


class TestClusterEnvironmentInfo(unittest.TestCase):
    def _make_session_resp(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    def test_cluster_env_info_stores_version_and_jvm(self):
        """ClusterEnvironmentInfo stores Solr version, JVM info, and CPU count."""
        admin_client, _session = _make_admin_client()

        meta_store = {}
        metrics_store = MagicMock()
        metrics_store.add_meta_info = MagicMock(side_effect=lambda scope, node, key, value: meta_store.update({key: value}))

        system_resp = self._make_session_resp(SYSTEM_INFO_RESPONSE)
        admin_client.raw_request.return_value = system_resp

        device = ClusterEnvironmentInfo(admin_client=admin_client, metrics_store=metrics_store)
        device.on_benchmark_start()

        self.assertEqual("9.7.0", meta_store.get("distribution_version"))
        self.assertEqual("21.0.1", meta_store.get("jvm_version"))
        self.assertEqual("OpenJDK 21", meta_store.get("jvm_vendor"))
        self.assertEqual(8, meta_store.get("cpu_logical_cores"))

    def test_cluster_env_info_failure_graceful(self):
        """ClusterEnvironmentInfo swallows connection errors."""
        admin_client, _session = _make_admin_client()
        metrics_store = MagicMock()
        admin_client.raw_request.side_effect = ConnectionError("refused")

        device = ClusterEnvironmentInfo(admin_client=admin_client, metrics_store=metrics_store)
        # Should not raise
        device.on_benchmark_start()


# ---------------------------------------------------------------------------
# T142: JVM device pipeline-skip behavior
# ---------------------------------------------------------------------------


class TestFlightRecorderPipelineSkip(unittest.TestCase):
    def test_jfr_benchmark_only_returns_empty(self):
        """FlightRecorder returns [] when pipeline is benchmark-only."""
        with tempfile.TemporaryDirectory() as log_root:
            device = FlightRecorder(
                telemetry_params={"pipeline": "benchmark-only"},
                log_root=log_root,
                java_major_version=21,
            )
            result = device.instrument_java_opts()
            self.assertEqual([], result)

    def test_jfr_docker_returns_jfr_flags(self):
        """FlightRecorder returns JFR flags when pipeline is docker."""
        with tempfile.TemporaryDirectory() as log_root:
            device = FlightRecorder(
                telemetry_params={"pipeline": "docker"},
                log_root=log_root,
                java_major_version=21,
            )
            result = device.instrument_java_opts()
            self.assertTrue(len(result) > 0)
            jfr_flag = next((f for f in result if "-XX:StartFlightRecording=" in f), None)
            self.assertIsNotNone(jfr_flag, "Should contain -XX:StartFlightRecording flag")

    def test_jfr_no_pipeline_key_returns_flags(self):
        """FlightRecorder returns JFR flags when pipeline key is absent (provisioned context)."""
        with tempfile.TemporaryDirectory() as log_root:
            device = FlightRecorder(
                telemetry_params={},
                log_root=log_root,
                java_major_version=21,
            )
            result = device.instrument_java_opts()
            self.assertTrue(len(result) > 0)


class TestGcPipelineSkip(unittest.TestCase):
    def test_gc_benchmark_only_returns_empty(self):
        """Gc returns [] when pipeline is benchmark-only."""
        with tempfile.TemporaryDirectory() as log_root:
            device = Gc(
                telemetry_params={"pipeline": "benchmark-only"},
                log_root=log_root,
                java_major_version=21,
            )
            result = device.instrument_java_opts()
            self.assertEqual([], result)

    def test_gc_docker_returns_xlog_flag(self):
        """Gc returns -Xlog: flag when pipeline is docker."""
        with tempfile.TemporaryDirectory() as log_root:
            device = Gc(
                telemetry_params={"pipeline": "docker"},
                log_root=log_root,
                java_major_version=21,
            )
            result = device.instrument_java_opts()
            self.assertTrue(len(result) > 0)
            self.assertTrue(any("-Xlog:" in f for f in result), "Should contain -Xlog: flag")


class TestJitCompilerPipelineSkip(unittest.TestCase):
    def test_jit_benchmark_only_returns_empty(self):
        """JitCompiler returns [] when pipeline is benchmark-only."""
        with tempfile.TemporaryDirectory() as log_root:
            device = JitCompiler(log_root=log_root, telemetry_params={"pipeline": "benchmark-only"})
            result = device.instrument_java_opts()
            self.assertEqual([], result)

    def test_jit_docker_returns_flags(self):
        """JitCompiler returns JIT flags when pipeline is docker."""
        with tempfile.TemporaryDirectory() as log_root:
            device = JitCompiler(log_root=log_root, telemetry_params={"pipeline": "docker"})
            result = device.instrument_java_opts()
            self.assertTrue(len(result) > 0)
            self.assertIn("-XX:+LogCompilation", result)

    def test_jit_no_telemetry_params(self):
        """JitCompiler works with no telemetry_params (defaults to empty dict)."""
        with tempfile.TemporaryDirectory() as log_root:
            device = JitCompiler(log_root=log_root)
            result = device.instrument_java_opts()
            self.assertTrue(len(result) > 0)


class TestHeapdumpDockerSupport(unittest.TestCase):
    def test_heapdump_local_calls_jmap(self):
        """Heapdump calls jmap directly for non-Docker nodes."""
        with tempfile.TemporaryDirectory() as log_root:
            device = Heapdump(log_root=log_root)
            node = MagicMock()
            node.pid = 12345
            with patch("solrorbit.utils.process.run_subprocess_with_logging") as mock_run:
                mock_run.return_value = 0
                device.detach_from_node(node, running=True)
                call_args = mock_run.call_args[0][0]
                self.assertIn("jmap", call_args)
                self.assertIn("12345", call_args)
                self.assertNotIn("docker", call_args)

    def test_heapdump_docker_calls_docker_exec(self):
        """Heapdump uses docker exec when docker_container is set."""
        with tempfile.TemporaryDirectory() as log_root:
            device = Heapdump(log_root=log_root, docker_container="solr-orbit")
            node = MagicMock()
            node.pid = 12345
            with patch("solrorbit.utils.process.run_subprocess_with_logging") as mock_run:
                mock_run.return_value = 0
                device.detach_from_node(node, running=True)
                call_args = mock_run.call_args[0][0]
                self.assertIn("docker exec", call_args)
                self.assertIn("solr-orbit", call_args)
                self.assertIn("jmap", call_args)

    def test_heapdump_not_running_skips(self):
        """Heapdump does nothing when running=False."""
        with tempfile.TemporaryDirectory() as log_root:
            device = Heapdump(log_root=log_root)
            node = MagicMock()
            node.pid = 12345
            with patch("solrorbit.utils.process.run_subprocess_with_logging") as mock_run:
                device.detach_from_node(node, running=False)
                mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
