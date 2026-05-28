# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for Solr telemetry devices (solrorbit/telemetry.py)"""

import time
import unittest
from unittest.mock import MagicMock

from solrorbit.telemetry import (
    SolrCacheStats,
    SolrCollectionStats,
    SolrIndexingStats,
    SolrJvmStats,
    SolrNodeStats,
    SolrQueryStats,
    SolrTelemetryDevice,
    _parse_prometheus_text,
)


# ---------------------------------------------------------------------------
# Helper: captured metrics store
# ---------------------------------------------------------------------------

def _make_metrics_store():
    """Return a MagicMock metrics store and a dict that captures stored values."""
    stored = {}
    store = MagicMock()
    store.put_value_cluster_level = MagicMock(
        side_effect=lambda name, value, **kw: stored.update({name: value})
    )
    return store, stored


# ---------------------------------------------------------------------------
# _parse_prometheus_text
# ---------------------------------------------------------------------------

class TestParsePrometheusText(unittest.TestCase):
    def test_basic_metric(self):
        text = "jvm_heap_used_bytes 1234567\n"
        result = _parse_prometheus_text(text)
        self.assertAlmostEqual(1234567.0, result["jvm_heap_used_bytes"])

    def test_comment_lines_skipped(self):
        text = "# HELP jvm_heap JVM heap\n# TYPE jvm_heap gauge\njvm_heap 9999\n"
        result = _parse_prometheus_text(text)
        self.assertIn("jvm_heap", result)
        self.assertAlmostEqual(9999.0, result["jvm_heap"])

    def test_labels_stripped(self):
        text = 'http_requests_total{method="GET",code="200"} 42\n'
        result = _parse_prometheus_text(text)
        self.assertIn("http_requests_total", result)
        self.assertAlmostEqual(42.0, result["http_requests_total"])

    def test_labels_accumulated(self):
        text = (
            'requests_total{status="200"} 100\n'
            'requests_total{status="404"} 10\n'
        )
        result = _parse_prometheus_text(text)
        self.assertAlmostEqual(110.0, result["requests_total"])

    def test_empty_text(self):
        result = _parse_prometheus_text("")
        self.assertEqual({}, result)

    def test_multiple_metrics(self):
        text = "a 1\nb 2\nc 3\n"
        result = _parse_prometheus_text(text)
        self.assertEqual(3, len(result))
        self.assertAlmostEqual(2.0, result["b"])

    def test_invalid_value_skipped(self):
        text = "good_metric 1.5\nbad_metric NaN_text\n"
        result = _parse_prometheus_text(text)
        self.assertIn("good_metric", result)
        self.assertNotIn("bad_metric", result)


# ---------------------------------------------------------------------------
# SolrTelemetryDevice base class helpers
# ---------------------------------------------------------------------------

class TestBaseClassHelpers(unittest.TestCase):
    def _make_device(self, raw_metrics):
        client = MagicMock()
        client.get_node_metrics.return_value = raw_metrics
        store, _ = _make_metrics_store()
        # Use a concrete subclass for testing
        device = SolrJvmStats(client, store)
        return device

    def test_fetch_node_metrics_json(self):
        data = {"metrics": {"solr.jvm": {"memory.heap.used": 512}}}
        device = self._make_device(data)
        fmt, result = device._fetch_node_metrics_parsed()
        self.assertEqual("json", fmt)
        self.assertIsInstance(result, dict)

    def test_fetch_node_metrics_prometheus(self):
        text = "jvm_memory_heap_used_bytes 512000\n"
        device = self._make_device(text)
        fmt, result = device._fetch_node_metrics_parsed()
        self.assertEqual("prometheus", fmt)
        self.assertIn("jvm_memory_heap_used_bytes", result)

    def test_get_metric_json_nested(self):
        data = {"a": {"b.c": {"d.e": 42}}}
        result = SolrTelemetryDevice._get_metric_json(data, "a", "b.c", "d.e")
        self.assertEqual(42, result)

    def test_get_metric_json_missing_key(self):
        data = {"a": {"b": 1}}
        result = SolrTelemetryDevice._get_metric_json(data, "a", "x", default=99)
        self.assertEqual(99, result)

    def test_get_metric_json_non_dict_intermediate(self):
        data = {"a": 5}
        result = SolrTelemetryDevice._get_metric_json(data, "a", "b", default="fallback")
        self.assertEqual("fallback", result)

    def test_get_metric_prometheus_found(self):
        data = {"some_metric": 3.14}
        result = SolrTelemetryDevice._get_metric_prometheus(data, "some_metric")
        self.assertAlmostEqual(3.14, result)

    def test_get_metric_prometheus_missing(self):
        result = SolrTelemetryDevice._get_metric_prometheus({}, "missing", default=0.0)
        self.assertEqual(0.0, result)


# ---------------------------------------------------------------------------
# SolrJvmStats
# ---------------------------------------------------------------------------

class TestSolrJvmStatsJson(unittest.TestCase):
    def _device(self, json_data):
        store, stored = _make_metrics_store()
        client = MagicMock()
        client.get_node_metrics.return_value = json_data
        return SolrJvmStats(client, store), stored

    def test_heap_metrics_extracted(self):
        data = {"metrics": {"solr.jvm": {
            "memory.heap.used": 512_000_000,
            "memory.heap.max": 2_000_000_000,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertEqual(512_000_000, stored["jvm_heap_used_bytes"])
        self.assertEqual(2_000_000_000, stored["jvm_heap_max_bytes"])

    def test_gc_metrics_summed(self):
        data = {"metrics": {"solr.jvm": {
            "memory.heap.used": 1,
            "memory.heap.max": 2,
            "gc.G1-Young-Generation.count": 10,
            "gc.G1-Old-Generation.count": 2,
            "gc.G1-Young-Generation.time": 150,
            "gc.G1-Old-Generation.time": 30,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertEqual(12, stored["jvm_gc_count"])
        self.assertEqual(180, stored["jvm_gc_time_ms"])

    def test_gc_young_old_split(self):
        data = {"metrics": {"solr.jvm": {
            "gc.G1 Young Generation.count": 10,
            "gc.G1 Young Generation.time": 100,
            "gc.G1 Old Generation.count": 2,
            "gc.G1 Old Generation.time": 50,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertEqual(10, stored.get("jvm_gc_young_count"))
        self.assertEqual(100, stored.get("jvm_gc_young_time_ms"))
        self.assertEqual(2, stored.get("jvm_gc_old_count"))
        self.assertEqual(50, stored.get("jvm_gc_old_time_ms"))

    def test_thread_metrics_extracted(self):
        data = {"metrics": {"solr.jvm": {
            "threads.count": 42,
            "threads.peak.count": 50,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertEqual(42, stored["jvm_thread_count"])
        self.assertEqual(50, stored["jvm_thread_peak_count"])

    def test_buffer_pool_metrics_extracted(self):
        data = {"metrics": {"solr.jvm": {
            "buffers.direct.MemoryUsed": 1_048_576,
            "buffers.mapped.MemoryUsed": 0,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertEqual(1_048_576, stored["jvm_buffer_pool_direct_bytes"])
        self.assertEqual(0, stored["jvm_buffer_pool_mapped_bytes"])

    def test_missing_jvm_section_no_error(self):
        client = MagicMock()
        client.get_node_metrics.return_value = {"metrics": {}}
        device = SolrJvmStats(client, MagicMock())
        device._collect()  # must not raise


class TestSolrJvmStatsPrometheus(unittest.TestCase):
    def test_prometheus_heap_extracted(self):
        store, stored = _make_metrics_store()
        prometheus_text = (
            "# HELP jvm_memory_heap_used_bytes JVM heap used\n"
            "jvm_memory_heap_used_bytes 123456789\n"
            "jvm_memory_heap_max_bytes 2048000000\n"
            "jvm_threads_current 30\n"
            "jvm_threads_peak 45\n"
        )
        client = MagicMock()
        client.get_node_metrics.return_value = prometheus_text
        device = SolrJvmStats(client, store)
        device._collect()

        self.assertAlmostEqual(123456789.0, stored["jvm_heap_used_bytes"])
        self.assertAlmostEqual(2048000000.0, stored["jvm_heap_max_bytes"])
        self.assertAlmostEqual(30.0, stored["jvm_thread_count"])
        self.assertAlmostEqual(45.0, stored["jvm_thread_peak_count"])


# ---------------------------------------------------------------------------
# SolrNodeStats
# ---------------------------------------------------------------------------

class TestSolrNodeStats(unittest.TestCase):
    def _make_client(self, system_data=None, metrics_raw=None):
        client = MagicMock()
        system_resp = MagicMock()
        system_resp.ok = True
        system_resp.json.return_value = {"system": system_data or {}}

        props_resp = MagicMock()
        props_resp.ok = True
        props_resp.json.return_value = metrics_raw or {}

        def _get_side_effect(path):
            if "/api/node/system" in path:
                return system_resp
            return props_resp

        client._get.side_effect = _get_side_effect
        client.get_node_metrics.return_value = metrics_raw or {}
        return client

    def test_cpu_extracted_from_system(self):
        store, stored = _make_metrics_store()
        client = self._make_client(
            system_data={"processCpuLoad": 0.45, "freePhysicalMemorySize": 4_000_000_000},
            metrics_raw={}
        )
        device = SolrNodeStats(client, store)
        device._collect()

        self.assertAlmostEqual(45.0, stored["cpu_usage_percent"])
        self.assertEqual(4_000_000_000, stored["os_memory_free_bytes"])

    def test_file_descriptors_extracted(self):
        store, stored = _make_metrics_store()
        client = self._make_client(
            system_data={"openFileDescriptorCount": 128, "maxFileDescriptorCount": 65536},
            metrics_raw={}
        )
        device = SolrNodeStats(client, store)
        device._collect()

        self.assertEqual(128, stored["node_file_descriptors_open"])
        self.assertEqual(65536, stored["node_file_descriptors_max"])

    def test_query_handler_avg_latency_json(self):
        store, stored = _make_metrics_store()
        metrics_data = {"metrics": {"solr.core": {
            "QUERY./select.requests": 500,
            "QUERY./select.errors": 3,
            "QUERY./select.requestTimes.mean": 12.5,
        }, "solr.jetty": {
            "org.eclipse.jetty.server.handler.StatisticsHandler.requests": 1000,
        }}}
        client = self._make_client(system_data={}, metrics_raw=metrics_data)
        device = SolrNodeStats(client, store)
        device._collect()

        self.assertEqual(500, stored["query_handler_requests_total"])
        self.assertEqual(3, stored["query_handler_errors_total"])
        self.assertAlmostEqual(12.5, stored["query_handler_avg_latency_ms"])
        self.assertEqual(1000, stored["node_http_requests_total"])

    def test_prometheus_format_node_stats(self):
        store, stored = _make_metrics_store()
        prom_text = (
            "solr_metrics_core_query_requests_total 200\n"
            "solr_metrics_core_query_errors_total 1\n"
        )
        client = self._make_client(system_data={}, metrics_raw=prom_text)
        client.get_node_metrics.return_value = prom_text
        device = SolrNodeStats(client, store)
        device._collect()

        self.assertAlmostEqual(200.0, stored["query_handler_requests_total"])


# ---------------------------------------------------------------------------
# SolrCollectionStats
# ---------------------------------------------------------------------------

class TestSolrCollectionStats(unittest.TestCase):
    def test_num_docs_extracted_from_properties(self):
        store, stored = _make_metrics_store()

        props_resp = MagicMock()
        props_resp.ok = True
        props_resp.json.return_value = {
            "core-properties": {
                "my-coll_shard1_replica1": {"numDocs": 5000}
            }
        }
        luke_resp = MagicMock()
        luke_resp.ok = True
        luke_resp.json.return_value = {
            "index": {"numDocs": 5000, "deletedDocs": 50, "segmentCount": 3}
        }

        def _get_side(path):
            if "luke" in path:
                return luke_resp
            return props_resp

        client = MagicMock()
        client.get_cluster_status.return_value = {"collections": {"my-coll": {}}}
        client._get.side_effect = _get_side

        device = SolrCollectionStats(client, store, collections=["my-coll"])
        device._collect()

        self.assertEqual(5000, stored["num_docs"])

    def test_deleted_docs_extracted_from_luke(self):
        store, stored = _make_metrics_store()

        props_resp = MagicMock()
        props_resp.ok = True
        props_resp.json.return_value = {"core-properties": {}}

        luke_resp = MagicMock()
        luke_resp.ok = True
        luke_resp.json.return_value = {
            "index": {"numDocs": 100, "deletedDocs": 10, "segmentCount": 2}
        }

        def _get_side(path):
            if "luke" in path:
                return luke_resp
            return props_resp

        client = MagicMock()
        client.get_cluster_status.return_value = {"collections": {"test-coll": {}}}
        client._get.side_effect = _get_side

        device = SolrCollectionStats(client, store, collections=["test-coll"])
        device._collect()

        self.assertEqual(10, stored["num_deleted_docs"])
        self.assertEqual(2, stored["segment_count"])

    def test_luke_stats_on_error_no_crash(self):
        client = MagicMock()
        client.get_cluster_status.return_value = {"collections": {"coll": {}}}
        client._get.side_effect = Exception("connection refused")

        device = SolrCollectionStats(client, MagicMock(), collections=["coll"])
        device._collect()  # must not raise


# ---------------------------------------------------------------------------
# SolrQueryStats
# ---------------------------------------------------------------------------

class TestSolrQueryStats(unittest.TestCase):
    def _device(self, raw_metrics):
        store, stored = _make_metrics_store()
        client = MagicMock()
        client.get_node_metrics.return_value = raw_metrics
        return SolrQueryStats(client, store), stored

    def test_latency_percentiles_json(self):
        data = {"metrics": {"solr.core": {
            "QUERY./select.requestTimes.p_50": 8.0,
            "QUERY./select.requestTimes.p_99": 45.0,
            "QUERY./select.requestTimes.p_99_9": 120.0,
            "QUERY./select.requests": 1000,
            "QUERY./select.errors": 5,
            "CACHE.searcher.filterCache.hitratio": 0.94,
        }}}
        device, stored = self._device(data)
        device._collect()

        self.assertAlmostEqual(8.0, stored["query_latency_p50_ms"])
        self.assertAlmostEqual(45.0, stored["query_latency_p99_ms"])
        self.assertAlmostEqual(120.0, stored["query_latency_p999_ms"])
        self.assertEqual(1000, stored["query_requests_total"])
        self.assertEqual(5, stored["query_errors_total"])
        self.assertAlmostEqual(0.94, stored["query_cache_hit_ratio"])

    def test_alternate_p999_key(self):
        data = {"metrics": {"solr.core": {
            "QUERY./select.requestTimes.p_999": 200.0,
        }}}
        device, stored = self._device(data)
        device._collect()
        self.assertAlmostEqual(200.0, stored["query_latency_p999_ms"])

    def test_prometheus_latency(self):
        prom_text = (
            "solr_metrics_core_query_request_times_p50_ms 10.0\n"
            "solr_metrics_core_query_request_times_p99_ms 55.0\n"
            "solr_metrics_core_query_requests_total 2000\n"
        )
        device, stored = self._device(prom_text)
        device._collect()

        self.assertAlmostEqual(10.0, stored["query_latency_p50_ms"])
        self.assertAlmostEqual(55.0, stored["query_latency_p99_ms"])
        self.assertAlmostEqual(2000.0, stored["query_requests_total"])

    def test_missing_metrics_no_error(self):
        device, stored = self._device({})
        device._collect()
        self.assertEqual({}, stored)


# ---------------------------------------------------------------------------
# SolrIndexingStats
# ---------------------------------------------------------------------------

class TestSolrIndexingStats(unittest.TestCase):
    def _device(self, raw_metrics):
        store, stored = _make_metrics_store()
        client = MagicMock()
        client.get_node_metrics.return_value = raw_metrics
        return SolrIndexingStats(client, store), stored

    def test_indexing_stats_json(self):
        data = {"metrics": {"solr.core": {
            "UPDATE./update.requests": 500,
            "UPDATE./update.errors": 2,
            "UPDATE./update.requestTimes.mean": 3.5,
            "INDEX.merge.major.running": 0,
            "INDEX.merge.minor.running": 1,
        }}}
        device, stored = self._device(data)
        device._collect()

        self.assertEqual(500, stored["indexing_requests_total"])
        self.assertEqual(2, stored["indexing_errors_total"])
        self.assertAlmostEqual(3.5, stored["indexing_avg_time_ms"])
        self.assertEqual(0, stored["index_merge_major_running"])
        self.assertEqual(1, stored["index_merge_minor_running"])

    def test_prometheus_indexing_stats(self):
        prom_text = (
            "solr_metrics_core_update_requests_total 300\n"
            "solr_metrics_core_update_errors_total 0\n"
            "solr_metrics_core_index_merge_major_running 2\n"
        )
        device, stored = self._device(prom_text)
        device._collect()

        self.assertAlmostEqual(300.0, stored["indexing_requests_total"])
        self.assertAlmostEqual(0.0, stored["indexing_errors_total"])
        self.assertAlmostEqual(2.0, stored["index_merge_major_running"])

    def test_missing_core_section_no_error(self):
        device, stored = self._device({"metrics": {}})
        device._collect()
        self.assertEqual({}, stored)


# ---------------------------------------------------------------------------
# SolrCacheStats
# ---------------------------------------------------------------------------

class TestSolrCacheStats(unittest.TestCase):
    def _device(self, raw_metrics):
        store = MagicMock()
        stored = {}

        def _capture(name, value, unit, task="", operation_type="", meta_data=None):
            key = f"{name}:{(meta_data or {}).get('cache', '')}"
            stored[key] = value

        store.put_value_cluster_level = MagicMock(side_effect=_capture)
        client = MagicMock()
        client.get_node_metrics.return_value = raw_metrics
        return SolrCacheStats(client, store), stored

    def test_cache_stats_json(self):
        data = {"metrics": {"solr.core": {
            "CACHE.searcher.queryResultCache.hits": 8000,
            "CACHE.searcher.queryResultCache.inserts": 500,
            "CACHE.searcher.queryResultCache.evictions": 100,
            "CACHE.searcher.queryResultCache.ramBytesUsed": 1_000_000,
            "CACHE.searcher.queryResultCache.hitratio": 0.94,
            "CACHE.searcher.filterCache.hits": 5000,
            "CACHE.searcher.filterCache.inserts": 200,
            "CACHE.searcher.filterCache.evictions": 10,
            "CACHE.searcher.filterCache.ramBytesUsed": 500_000,
            "CACHE.searcher.filterCache.hitratio": 0.96,
        }}}
        device, stored = self._device(data)
        device._collect()

        self.assertEqual(8000, stored["cache_hits_total:queryResultCache"])
        self.assertEqual(500, stored["cache_inserts_total:queryResultCache"])
        self.assertEqual(100, stored["cache_evictions_total:queryResultCache"])
        self.assertEqual(1_000_000, stored["cache_memory_bytes:queryResultCache"])
        self.assertAlmostEqual(0.94, stored["cache_hit_ratio:queryResultCache"])
        self.assertEqual(5000, stored["cache_hits_total:filterCache"])
        self.assertAlmostEqual(0.96, stored["cache_hit_ratio:filterCache"])

    def test_prometheus_cache_stats(self):
        prom_text = (
            "solr_metrics_core_cache_hits_total 13000\n"
            "solr_metrics_core_cache_evictions_total 110\n"
        )
        device, stored = self._device(prom_text)
        device._collect()

        self.assertAlmostEqual(13000.0, stored["cache_hits_total:aggregate"])
        self.assertAlmostEqual(110.0, stored["cache_evictions_total:aggregate"])

    def test_empty_metrics_no_error(self):
        device, stored = self._device({})
        device._collect()
        self.assertEqual({}, stored)


# ---------------------------------------------------------------------------
# Polling thread lifecycle
# ---------------------------------------------------------------------------

class TestTelemetryPollingThread(unittest.TestCase):
    def test_start_and_stop(self):
        """Verify that the polling thread starts and stops cleanly."""
        client = MagicMock()
        client.get_node_metrics.return_value = {}
        client.get_cluster_status.return_value = {"collections": {}}

        collected = []
        metrics_store = MagicMock()
        metrics_store.put_value_cluster_level = MagicMock(
            side_effect=lambda **kw: collected.append(kw)
        )

        device = SolrJvmStats(client, metrics_store, sample_interval_s=0.05)
        device.on_benchmark_start()
        time.sleep(0.15)
        device.on_benchmark_stop()

        self.assertFalse(device._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
