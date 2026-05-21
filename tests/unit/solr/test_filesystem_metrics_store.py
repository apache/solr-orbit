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

"""Unit tests for FilesystemMetricsStore in osbenchmark/metrics.py"""

import datetime
import json
import os
import tempfile
import unittest

from osbenchmark import config, metrics


class StaticClock:
    NOW = 1453362707

    @staticmethod
    def now():
        return StaticClock.NOW

    @staticmethod
    def stop_watch():
        return StaticStopWatch()


class StaticStopWatch:
    def start(self):
        pass

    def stop(self):
        pass

    def split_time(self):
        return 0

    def total_time(self):
        return 0


TEST_RUN_TIMESTAMP = datetime.datetime(2016, 1, 31)
TEST_RUN_ID = "test-fs-metrics-store-01"


def _make_cfg(root_dir):
    """Return a minimal Config object pointing at a temp directory."""
    cfg = config.Config()
    cfg.add(config.Scope.application, "system", "env.name", "unittest")
    cfg.add(config.Scope.application, "workload", "params", {})
    cfg.add(config.Scope.application, "node", "root.dir", root_dir)
    return cfg


class FilesystemMetricsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp_dir)
        self.store = metrics.FilesystemMetricsStore(self.cfg, clock=StaticClock)

    def tearDown(self):
        if self.store._metrics_file is not None:
            self.store._metrics_file.close()
        del self.store
        del self.cfg

    # ------------------------------------------------------------------
    # str()
    # ------------------------------------------------------------------

    def test_str(self):
        self.assertEqual("filesystem metrics store", str(self.store))

    # ------------------------------------------------------------------
    # metrics.jsonl is created on open(create=True)
    # ------------------------------------------------------------------

    def test_file_created_on_create(self):
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=True)
        expected = os.path.join(self.tmp_dir, "test-runs", TEST_RUN_ID, "metrics.jsonl")
        self.assertTrue(os.path.isfile(expected), f"Expected {expected} to exist")
        self.store.close()

    def test_file_not_created_on_read_only_open(self):
        # open without create=True should NOT create the file
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=False)
        expected = os.path.join(self.tmp_dir, "test-runs", TEST_RUN_ID, "metrics.jsonl")
        self.assertFalse(os.path.isfile(expected))
        self.store.close()

    # ------------------------------------------------------------------
    # Metric documents are written to disk
    # ------------------------------------------------------------------

    def test_metrics_written_to_jsonl(self):
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=True)
        self.store.put_value_cluster_level("service_time", 500, "ms", task="task1")
        self.store.put_value_cluster_level("service_time", 600, "ms", task="task1")
        self.store.put_value_cluster_level("final_index_size", 1000, "GB")
        self.store.close()

        metrics_path = os.path.join(self.tmp_dir, "test-runs", TEST_RUN_ID, "metrics.jsonl")
        with open(metrics_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        self.assertEqual(3, len(lines), "Expected 3 metric lines in metrics.jsonl")
        for line in lines:
            doc = json.loads(line)
            self.assertIn("name", doc)
            self.assertIn("value", doc)

    def test_metric_names_in_file(self):
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=True)
        self.store.put_value_cluster_level("throughput", 1234.5, "ops/s", task="index")
        self.store.put_value_cluster_level("latency", 42.0, "ms", task="search")
        self.store.close()

        metrics_path = os.path.join(self.tmp_dir, "test-runs", TEST_RUN_ID, "metrics.jsonl")
        with open(metrics_path, encoding="utf-8") as f:
            docs = [json.loads(l) for l in f if l.strip()]

        names = {d["name"] for d in docs}
        self.assertIn("throughput", names)
        self.assertIn("latency", names)

    # ------------------------------------------------------------------
    # In-memory queries still work
    # ------------------------------------------------------------------

    def test_in_memory_queries_still_work(self):
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=True)
        self.store.put_value_cluster_level("service_time", 100, "ms", task="t1")
        self.store.put_value_cluster_level("service_time", 200, "ms", task="t1")
        self.store.put_value_cluster_level("service_time", 300, "ms", task="t1")
        self.store.close()

        # Re-open read-only and query
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=False)
        percentiles = self.store.get_percentiles("service_time", task="t1", percentiles=[50, 100])
        self.assertIn(50, percentiles)
        self.assertIn(100, percentiles)
        self.assertEqual(300, percentiles[100])

    # ------------------------------------------------------------------
    # close() closes the file handle
    # ------------------------------------------------------------------

    def test_close_releases_file_handle(self):
        self.store.open(TEST_RUN_ID, TEST_RUN_TIMESTAMP, "test", "challenge", "defaults", create=True)
        self.assertIsNotNone(self.store._metrics_file)
        self.store.close()
        self.assertIsNone(self.store._metrics_file)

    # ------------------------------------------------------------------
    # metrics_store() factory — default and explicit configuration
    # ------------------------------------------------------------------

    def test_factory_returns_in_memory_store_by_default(self):
        cfg = _make_cfg(self.tmp_dir)
        cfg.add(config.Scope.application, "system", "test_run.id", TEST_RUN_ID)
        cfg.add(config.Scope.application, "system", "time.start", TEST_RUN_TIMESTAMP)
        cfg.add(config.Scope.application, "builder", "cluster_config.names", "defaults")

        store = metrics.metrics_store(cfg, read_only=False, workload="test", test_procedure="challenge")
        try:
            self.assertIsInstance(store, metrics.InMemoryMetricsStore)
            self.assertNotIsInstance(store, metrics.FilesystemMetricsStore)
        finally:
            store.close()

    def test_factory_returns_filesystem_store_when_configured(self):
        cfg = _make_cfg(self.tmp_dir)
        cfg.add(config.Scope.application, "system", "test_run.id", TEST_RUN_ID + "-fs")
        cfg.add(config.Scope.application, "system", "time.start", TEST_RUN_TIMESTAMP)
        cfg.add(config.Scope.application, "builder", "cluster_config.names", "defaults")
        cfg.add(config.Scope.application, "reporting", "datastore.type", "filesystem")

        store = metrics.metrics_store(cfg, read_only=False, workload="test", test_procedure="challenge")
        try:
            self.assertIsInstance(store, metrics.FilesystemMetricsStore)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
