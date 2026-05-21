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

import collections
import datetime
import os
import tempfile
import unittest.mock as mock
import uuid
from unittest import TestCase
from collections import namedtuple

from osbenchmark import config, metrics, workload, exceptions
from osbenchmark.metrics import GlobalStatsCalculator
from osbenchmark.workload import Task, Operation, TestProcedure, Workload

AWS_ACCESS_KEY_ID_LENGTH = 12
AWS_SECRET_ACCESS_KEY_LENGTH = 40
AWS_SESSION_TOKEN_LENGTH = 752

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


class ExtractUserTagsTests(TestCase):
    def test_no_tags_returns_empty_dict(self):
        cfg = config.Config()
        self.assertEqual(0, len(metrics.extract_user_tags_from_config(cfg)))

    def test_missing_comma_raises_error(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "test_run", "user.tag", "invalid")
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            metrics.extract_user_tags_from_config(cfg)
        self.assertEqual("User tag keys and values have to separated by a ':'. Invalid value [invalid]", ctx.exception.args[0])

    def test_missing_value_raises_error(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "test_run", "user.tag", "invalid1,invalid2")
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            metrics.extract_user_tags_from_config(cfg)
        self.assertEqual("User tag keys and values have to separated by a ':'. Invalid value [invalid1,invalid2]", ctx.exception.args[0])

    def test_extracts_proper_user_tags(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "test_run", "user.tag", "os:Linux,cpu:ARM")
        self.assertDictEqual({"os": "Linux", "cpu": "ARM"}, metrics.extract_user_tags_from_config(cfg))


class InMemoryMetricsStoreTests(TestCase):
    TEST_RUN_TIMESTAMP = datetime.datetime(2016, 1, 31)
    TEST_RUN_ID = "6ebc6e53-ee20-4b0c-99b4-09697987e9f4"

    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest")
        self.cfg.add(config.Scope.application, "workload", "params", {})
        self.metrics_store = metrics.InMemoryMetricsStore(self.cfg, clock=StaticClock)

    def tearDown(self):
        del self.metrics_store
        del self.cfg

    def test_get_one(self):
        duration = StaticClock.NOW
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("service_time", 500, "ms", relative_time=duration-400, task="task1")
        self.metrics_store.put_value_cluster_level("service_time", 600, "ms", relative_time=duration, task="task1")
        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB", relative_time=duration-300)

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        actual_duration = self.metrics_store.get_one("service_time", task="task1", mapper=lambda doc: doc["relative-time-ms"],
                                                         sort_key="relative-time-ms", sort_reverse=True)

        self.assertEqual(duration * 1000, actual_duration)

    def test_get_one_no_hits(self):
        duration = StaticClock.NOW
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB", relative_time=duration-300)

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        actual_duration = self.metrics_store.get_one("service_time", task="task1", mapper=lambda doc: doc["relative-time-ms"],
                                                     sort_key="relative-time-ms", sort_reverse=True)

        self.assertIsNone(actual_duration)

    def test_get_value(self):
        throughput = 5000
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("indexing_throughput", 1, "docs/s", sample_type=metrics.SampleType.Warmup)
        self.metrics_store.put_value_cluster_level("indexing_throughput", throughput, "docs/s")
        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB")

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertEqual(1, self.metrics_store.get_one("indexing_throughput", sample_type=metrics.SampleType.Warmup))
        self.assertEqual(throughput, self.metrics_store.get_one("indexing_throughput", sample_type=metrics.SampleType.Normal))

    @mock.patch("osbenchmark.utils.console.warn")
    @mock.patch("psutil.virtual_memory")
    def test_out_of_memory(self, virt_mem, console_warn):
        vmem = namedtuple('vmem', ("available", "total"))
        virt_mem.return_value = vmem(250, 1000)
        throughput = 5000
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("indexing_throughput", 1, "docs/s", sample_type=metrics.SampleType.Warmup)
        self.metrics_store.put_value_cluster_level("indexing_throughput", throughput, "docs/s")
        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB")
        console_warn.assert_has_calls([ mock.call(
            "Memory threshold exceeded by in-memory metrics store, not adding additional entries",
            logger=mock.ANY) ])
        self.metrics_store.to_externalizable(clear=True)
        console_warn.assert_has_calls([ mock.call(
            "Memory threshold exceeded by in-memory metrics store, skipping summary generation for current operation",
            logger=mock.ANY) ])
        self.metrics_store.close()

    def test_get_percentile(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        for i in range(1, 1001):
            self.metrics_store.put_value_cluster_level("query_latency", float(i), "ms")

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assert_equal_percentiles("query_latency", [100.0], {100.0: 1000.0})
        self.assert_equal_percentiles("query_latency", [99.0], {99.0: 990.0})
        self.assert_equal_percentiles("query_latency", [99.9], {99.9: 999.0})
        self.assert_equal_percentiles("query_latency", [0.0], {0.0: 1.0})

        self.assert_equal_percentiles("query_latency", [99, 99.9, 100], {99: 990.0, 99.9: 999.0, 100: 1000.0})

    def test_get_mean(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        for i in range(1, 100):
            self.metrics_store.put_value_cluster_level("query_latency", float(i), "ms")

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertAlmostEqual(50, self.metrics_store.get_mean("query_latency"))

    def test_get_median(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        for i in range(1, 1001):
            self.metrics_store.put_value_cluster_level("query_latency", float(i), "ms")

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertAlmostEqual(500.5, self.metrics_store.get_median("query_latency"))

    def assert_equal_percentiles(self, name, percentiles, expected_percentiles):
        actual_percentiles = self.metrics_store.get_percentiles(name, percentiles=percentiles)
        self.assertEqual(len(expected_percentiles), len(actual_percentiles))
        for percentile, actual_percentile_value in actual_percentiles.items():
            self.assertAlmostEqual(expected_percentiles[percentile], actual_percentile_value, places=1,
                                   msg=str(percentile) + "th percentile differs")

    def test_filter_percentiles_by_sample_size(self):
        test_percentiles = [
            0,
            0.0001,
            0.001,
            0.01,
            0.1,
            4,
            10,
            10.01,
            25,
            45,
            46.001,
            50,
            75,
            80.1,
            90,
            98.9,
            98.91,
            98.999,
            99,
            99.9,
            99.99,
            99.999,
            99.9999,
            100]
        sample_size_to_result_map = {
            1: [100],
            2: [50, 100],
            4: [25, 50, 75, 100],
            10: [0, 10, 25, 50, 75, 90, 100],
            99: [0, 10, 25, 50, 75, 90, 100],
            100: [0, 4, 10, 25, 45, 50, 75, 90, 99, 100],
            1000: [0, 0.1, 4, 10, 25, 45, 50, 75, 80.1, 90, 98.9, 99, 99.9, 100],
            10000: [0, 0.01, 0.1, 4, 10, 10.01, 25, 45, 50, 75, 80.1, 90, 98.9, 98.91, 99, 99.9, 99.99, 100],
            100000: [0, 0.001, 0.01, 0.1, 4, 10, 10.01, 25, 45, 46.001, 50, 75,
                     80.1, 90, 98.9, 98.91, 98.999, 99, 99.9, 99.99, 99.999, 100],
            1000000: [0, 0.0001, 0.001, 0.01, 0.1, 4, 10, 10.01, 25, 45, 46.001, 50, 75,
                      80.1, 90, 98.9, 98.91, 98.999, 99, 99.9, 99.99, 99.999, 99.9999, 100]
        } # 100,000 corresponds to 0.001% which is the order of magnitude we round to,
        # so at higher orders (>=1M samples) all values are permitted
        for sample_size, expected_results in sample_size_to_result_map.items():
            filtered = metrics.filter_percentiles_by_sample_size(sample_size, test_percentiles)
            self.assertEqual(len(filtered), len(expected_results))
            for res, exp in zip(filtered, expected_results):
                self.assertEqual(res, exp)

    def test_externalize_and_bulk_add(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB")

        self.assertEqual(1, len(self.metrics_store.docs))
        memento = self.metrics_store.to_externalizable()

        self.metrics_store.close()
        del self.metrics_store

        self.metrics_store = metrics.InMemoryMetricsStore(self.cfg, clock=StaticClock)
        self.assertEqual(0, len(self.metrics_store.docs))

        self.metrics_store.bulk_add(memento)
        self.assertEqual(1, len(self.metrics_store.docs))
        self.assertEqual(1000, self.metrics_store.get_one("final_index_size"))

    def test_meta_data_per_document(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "cluster-name", "test")

        self.metrics_store.put_value_cluster_level("final_index_size", 1000, "GB", meta_data={
            "fs-block-size-bytes": 512
        })
        self.metrics_store.put_value_cluster_level("final_bytes_written", 1, "TB", meta_data={
            "io-batch-size-kb": 4
        })

        self.assertEqual(2, len(self.metrics_store.docs))
        self.assertEqual({
            "cluster-name": "test",
            "fs-block-size-bytes": 512
        }, self.metrics_store.docs[0]["meta"])

        self.assertEqual({
            "cluster-name": "test",
            "io-batch-size-kb": 4
        }, self.metrics_store.docs[1]["meta"])

    def test_get_error_rate_zero_without_samples(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertEqual(0.0, self.metrics_store.get_error_rate("term-query", sample_type=metrics.SampleType.Normal))

    def test_get_error_rate_by_sample_type(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Warmup,
                                                   meta_data={"success": False})
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": True})

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertEqual(1.0, self.metrics_store.get_error_rate("term-query", sample_type=metrics.SampleType.Warmup))
        self.assertEqual(0.0, self.metrics_store.get_error_rate("term-query", sample_type=metrics.SampleType.Normal))

    def test_get_error_rate_mixed(self):
        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": True})
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": True})
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": False})
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": True})
        self.metrics_store.put_value_cluster_level("service_time", 3.0, "ms", task="term-query", sample_type=metrics.SampleType.Normal,
                                                   meta_data={"success": True})

        self.metrics_store.close()

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-no-conflicts", "defaults")

        self.assertEqual(0.0, self.metrics_store.get_error_rate("term-query", sample_type=metrics.SampleType.Warmup))
        self.assertEqual(0.2, self.metrics_store.get_error_rate("term-query", sample_type=metrics.SampleType.Normal))


class FileTestRunStoreTests(TestCase):
    TEST_RUN_TIMESTAMP = datetime.datetime(2016, 1, 31)
    TEST_RUN_ID = "6ebc6e53-ee20-4b0c-99b4-09697987e9f4"

    class DictHolder:
        def __init__(self, d):
            self.d = d

        def as_dict(self):
            return self.d

    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "node", "root.dir", os.path.join(tempfile.gettempdir(), str(uuid.uuid4())))
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest-env")
        self.cfg.add(config.Scope.application, "system", "list.test_runs.max_results", 100)
        self.cfg.add(config.Scope.application, "system", "time.start", FileTestRunStoreTests.TEST_RUN_TIMESTAMP)
        self.cfg.add(
            config.Scope.application, "system", "test_run.id",
            FileTestRunStoreTests.TEST_RUN_ID)
        self.test_run_store = metrics.FileTestRunStore(self.cfg)

    def test_test_run_not_found(self):
        with self.assertRaisesRegex(exceptions.NotFound, r"No test run with test run id \[.*\]"):
            # did not store anything yet
            self.test_run_store.find_by_test_run_id(FileTestRunStoreTests.TEST_RUN_ID)

    def test_store_test_run(self):
        schedule = [
            workload.Task("index #1", workload.Operation("index", workload.OperationType.Bulk))
        ]

        t = workload.Workload(name="unittest",
                        collections=[workload.Collection(name="tests")],
                        test_procedures=[workload.TestProcedure(name="index", default=True, schedule=schedule)])

        test_run = metrics.TestRun(
            benchmark_version="0.4.4", benchmark_revision="123abc", environment_name="unittest",
                            test_run_id=FileTestRunStoreTests.TEST_RUN_ID,
                            test_run_timestamp=FileTestRunStoreTests.TEST_RUN_TIMESTAMP,
                            pipeline="from-sources", user_tags={"os": "Linux"}, workload=t, workload_params={"clients": 12},
                            test_procedure=t.default_test_procedure,
                            cluster_config="4gheap",
                            cluster_config_params=None,
                            plugin_params=None,
                            workload_revision="abc1",
                            cluster_config_revision="abc12333",
                            distribution_version="5.0.0",
                            distribution_flavor="default", revision="aaaeeef",
                            results=FileTestRunStoreTests.DictHolder(
                                {
                                    "young_gc_time": 100,
                                    "old_gc_time": 5,
                                    "op_metrics": [
                                        {
                                            "task": "index #1",
                                            "operation": "index",
                                            "throughput": {
                                                "min": 1000,
                                                "median": 1250,
                                                "max": 1500,
                                                "unit": "docs/s"
                                            }
                                        }
                                    ]
                                })
                            )

        self.test_run_store.store_test_run(test_run)

        retrieved_test_run = self.test_run_store.find_by_test_run_id(
            test_run_id=FileTestRunStoreTests.TEST_RUN_ID)
        self.assertEqual(test_run.test_run_id, retrieved_test_run.test_run_id)
        self.assertEqual(test_run.test_run_timestamp, retrieved_test_run.test_run_timestamp)
        self.assertEqual(1, len(self.test_run_store.list()))


class StatsCalculatorTests(TestCase):
    def test_calculate_global_stats(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "system", "env.name", "unittest")
        cfg.add(config.Scope.application, "system", "time.start", datetime.datetime.now())
        cfg.add(config.Scope.application, "system", "test_run.id", "6ebc6e53-ee20-4b0c-99b4-09697987e9f4")
        cfg.add(config.Scope.application, "reporting", "datastore.type", "in-memory")
        cfg.add(config.Scope.application, "builder", "cluster_config.names", ["unittest_cluster_config"])
        cfg.add(config.Scope.application, "builder", "cluster_config.params", {})
        cfg.add(config.Scope.application, "builder", "plugin.params", {})
        cfg.add(config.Scope.application, "test_run", "user.tag", "")
        cfg.add(config.Scope.application, "test_run", "pipeline", "from-sources")
        cfg.add(config.Scope.application, "workload", "params", {})

        index1 = workload.Task(name="index #1", operation=workload.Operation(
            name="index",
            operation_type=workload.OperationType.Bulk,
            params=None))
        index2 = workload.Task(name="index #2", operation=workload.Operation(
            name="index",
            operation_type=workload.OperationType.Bulk,
            params=None))
        test_procedure = workload.TestProcedure(name="unittest", schedule=[index1, index2], default=True)
        t = workload.Workload("unittest", "unittest-workload", test_procedures=[test_procedure])

        store = metrics.metrics_store(cfg, read_only=False, workload=t, test_procedure=test_procedure)

        store.put_value_cluster_level("throughput", 500, unit="docs/s", task="index #1", operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("throughput", 1000, unit="docs/s", task="index #1", operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("throughput", 1000, unit="docs/s", task="index #1", operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("throughput", 2000, unit="docs/s", task="index #1", operation_type=workload.OperationType.Bulk)

        store.put_value_cluster_level("latency", 2800, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk,
                                      sample_type=metrics.SampleType.Warmup)
        store.put_value_cluster_level("latency", 200, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("latency", 220, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("latency", 225, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk)

        store.put_value_cluster_level("service_time", 250, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk,
                                      sample_type=metrics.SampleType.Warmup, meta_data={"success": False}, relative_time=536)
        store.put_value_cluster_level("service_time", 190, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk,
                                      meta_data={"success": True}, relative_time=595)
        store.put_value_cluster_level("service_time", 200, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk,
                                      meta_data={"success": False}, relative_time=709)
        store.put_value_cluster_level("service_time", 210, unit="ms", task="index #1", operation_type=workload.OperationType.Bulk,
                                      meta_data={"success": True}, relative_time=653)

        # only warmup samples
        store.put_value_cluster_level("throughput", 500, unit="docs/s", task="index #2",
                                      sample_type=metrics.SampleType.Warmup, operation_type=workload.OperationType.Bulk)
        store.put_value_cluster_level("latency", 2800, unit="ms", task="index #2", operation_type=workload.OperationType.Bulk,
                                      sample_type=metrics.SampleType.Warmup)
        store.put_value_cluster_level("service_time", 250, unit="ms", task="index #2", operation_type=workload.OperationType.Bulk,
                                      sample_type=metrics.SampleType.Warmup, relative_time=600)

        store.put_doc(doc={
            "name": "ml_processing_time",
            "job": "benchmark_ml_job_1",
            "min": 2.2,
            "mean": 12.3,
            "median": 17.2,
            "max": 36.0,
            "unit": "ms"
        }, level=metrics.MetaInfoScope.cluster)

        stats = metrics.calculate_results(store, metrics.create_test_run(cfg, t, test_procedure))

        del store

        opm = stats.metrics("index #1")
        self.assertEqual(collections.OrderedDict(
            [("min", 500), ("mean", 1125), ("median", 1000), ("max", 2000), ("unit", "docs/s")]), opm["throughput"])
        self.assertEqual(collections.OrderedDict(
            [("50_0", 220), ("100_0", 225), ("mean", 215), ("unit", "ms")]), opm["latency"])
        self.assertEqual(collections.OrderedDict(
            [("50_0", 200), ("100_0", 210), ("mean", 200), ("unit", "ms")]), opm["service_time"])
        self.assertAlmostEqual(0.3333333333333333, opm["error_rate"])
        self.assertEqual(709*1000, opm["duration"])

        opm2 = stats.metrics("index #2")
        self.assertEqual(collections.OrderedDict(
            [("min", None), ("mean", None), ("median", None), ("max", None), ("unit", "docs/s")]), opm2["throughput"])

        self.assertEqual(1, len(stats.ml_processing_time))
        self.assertEqual("benchmark_ml_job_1", stats.ml_processing_time[0]["job"])
        self.assertEqual(2.2, stats.ml_processing_time[0]["min"])
        self.assertEqual(12.3, stats.ml_processing_time[0]["mean"])
        self.assertEqual(17.2, stats.ml_processing_time[0]["median"])
        self.assertEqual(36.0, stats.ml_processing_time[0]["max"])
        self.assertEqual("ms", stats.ml_processing_time[0]["unit"])
        self.assertEqual(600*1000, opm2["duration"])

    def test_calculate_system_stats(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "system", "env.name", "unittest")
        cfg.add(config.Scope.application, "system", "time.start", datetime.datetime.now())
        cfg.add(config.Scope.application, "system", "test_run.id", "6ebc6e53-ee20-4b0c-99b4-09697987e9f4")
        cfg.add(config.Scope.application, "reporting", "datastore.type", "in-memory")
        cfg.add(config.Scope.application, "builder", "cluster_config.names", ["unittest_cluster_config"])
        cfg.add(config.Scope.application, "builder", "cluster_config.params", {})
        cfg.add(config.Scope.application, "builder", "plugin.params", {})
        cfg.add(config.Scope.application, "test_run", "user.tag", "")
        cfg.add(config.Scope.application, "test_run", "pipeline", "from-sources")
        cfg.add(config.Scope.application, "workload", "params", {})

        index = workload.Task(name="index #1", operation=workload.Operation(
            name="index",
            operation_type=workload.OperationType.Bulk,
            params=None))
        test_procedure = workload.TestProcedure(name="unittest", schedule=[index], default=True)
        t = workload.Workload("unittest", "unittest-workload", test_procedures=[test_procedure])

        store = metrics.metrics_store(cfg, read_only=False, workload=t, test_procedure=test_procedure)
        store.add_meta_info(metrics.MetaInfoScope.node, "benchmark-node-0", "node_name", "benchmark-node-0")

        store.put_value_node_level("benchmark-node-0", "final_index_size_bytes", 2048, unit="bytes")
        # ensure this value will be filtered as it does not belong to our node
        store.put_value_node_level("benchmark-node-1", "final_index_size_bytes", 4096, unit="bytes")

        stats = metrics.calculate_system_results(store, "benchmark-node-0")

        del store

        self.assertEqual([
            {
                "node": "benchmark-node-0",
                "name": "index_size",
                "value": 2048,
                "unit": "bytes"
            }
        ], stats.node_metrics)


def select(l, name, operation=None, job=None, node=None):
    for item in l:
        if item["name"] == name and item.get("operation") == operation and item.get("node") == node and item.get("job") == job:
            return item
    return None


class GlobalStatsCalculatorTests(TestCase):
    TEST_RUN_TIMESTAMP = datetime.datetime(2016, 1, 31)
    TEST_RUN_ID = "fb26018b-428d-4528-b36b-cf8c54a303ec"

    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest")
        self.cfg.add(config.Scope.application, "workload", "params", {})
        self.metrics_store = metrics.InMemoryMetricsStore(self.cfg, clock=StaticClock)

    def tearDown(self):
        del self.metrics_store
        del self.cfg

    def test_add_administrative_task_with_error_rate_in_results(self):
        op = Operation(name='delete-index', operation_type='DeleteIndex', params={'include-in-reporting': False})
        task = Task('delete-index', operation=op, schedule='deterministic')
        test_procedure = TestProcedure(name='append-fast-with-conflicts', schedule=[task], meta_data={})

        self.metrics_store.open(InMemoryMetricsStoreTests.TEST_RUN_ID, InMemoryMetricsStoreTests.TEST_RUN_TIMESTAMP,
                                "test", "append-fast-with-conflicts", "defaults", create=True)
        self.metrics_store.put_doc(doc={"@timestamp": 1595896761994,
                                        "relative-time-ms": 283.382,
                                        "test-run-id": "fb26018b-428d-4528-b36b-cf8c54a303ec",
                                        "test-run-timestamp": "20200728T003905Z", "environment": "local",
                                        "workload": "geonames", "test_procedure": "append-fast-with-conflicts",
                                        "cluster-config-instance": "defaults", "name": "service_time", "value": 72.67997100007051,
                                        "unit": "ms", "sample-type": "normal",
                                        "meta": {"source_revision": "7f634e9f44834fbc12724506cc1da681b0c3b1e3",
                                                 "distribution_version": "7.6.0", "distribution_flavor": "oss",
                                                 "success": False}, "task": "delete-index", "operation": "delete-index",
                                        "operation-type": "DeleteIndex"})

        result = GlobalStatsCalculator(store=self.metrics_store, workload=Workload(name='geonames', meta_data={}),
                                       test_procedure=test_procedure)()
        assert "delete-index" in [op_metric.get('task') for op_metric in result.op_metrics]


class GlobalStatsTests(TestCase):
    def test_as_flat_list(self):
        d = {
            "op_metrics": [
                {
                    "task": "index #1",
                    "operation": "index",
                    "throughput": {
                        "min": 450,
                        "mean": 450,
                        "median": 450,
                        "max": 452,
                        "unit": "docs/s"
                    },
                    "latency": {
                        "50": 340,
                        "100": 376,
                    },
                    "service_time": {
                        "50": 341,
                        "100": 376
                    },
                    "error_rate": 0.0,
                    "meta": {
                        "clients": 8,
                        "phase": "idx"
                    }
                },
                {
                    "task": "search #2",
                    "operation": "search",
                    "throughput": {
                        "min": 9,
                        "mean": 10,
                        "median": 10,
                        "max": 12,
                        "unit": "ops/s"
                    },
                    "latency": {
                        "50": 99,
                        "100": 111,
                    },
                    "service_time": {
                        "50": 98,
                        "100": 110
                    },
                    "error_rate": 0.1
                }
            ],
            "ml_processing_time": [
                {
                    "job": "job_1",
                    "min": 3.3,
                    "mean": 5.2,
                    "median": 5.8,
                    "max": 12.34
                },
                {
                    "job": "job_2",
                    "min": 3.55,
                    "mean": 4.2,
                    "median": 4.9,
                    "max": 9.4
                },
            ],
            "young_gc_time": 68,
            "young_gc_count": 7,
            "old_gc_time": 0,
            "old_gc_count": 0,
            "merge_time": 3702,
            "merge_time_per_shard": {
                "min": 40,
                "median": 3702,
                "max": 3900,
                "unit": "ms"
            },
            "merge_count": 2,
            "refresh_time": 596,
            "refresh_time_per_shard": {
                "min": 48,
                "median": 89,
                "max": 204,
                "unit": "ms"
            },
            "refresh_count": 10,
            "flush_time": None,
            "flush_time_per_shard": {},
            "flush_count": 0
        }

        s = metrics.GlobalStats(d)
        metric_list = s.as_flat_list()
        self.assertEqual({
            "name": "throughput",
            "task": "index #1",
            "operation": "index",
            "value": {
                "min": 450,
                "mean": 450,
                "median": 450,
                "max": 452,
                "unit": "docs/s"
            },
            "meta": {
                "clients": 8,
                "phase": "idx"
            }
        }, select(metric_list, "throughput", operation="index"))

        self.assertEqual({
            "name": "service_time",
            "task": "index #1",
            "operation": "index",
            "value": {
                "50": 341,
                "100": 376
            },
            "meta": {
                "clients": 8,
                "phase": "idx"
            }
        }, select(metric_list, "service_time", operation="index"))

        self.assertEqual({
            "name": "latency",
            "task": "index #1",
            "operation": "index",
            "value": {
                "50": 340,
                "100": 376
            },
            "meta": {
                "clients": 8,
                "phase": "idx"
            }
        }, select(metric_list, "latency", operation="index"))

        self.assertEqual({
            "name": "error_rate",
            "task": "index #1",
            "operation": "index",
            "value": {
                "single": 0.0
            },
            "meta": {
                "clients": 8,
                "phase": "idx"
            }
        }, select(metric_list, "error_rate", operation="index"))

        self.assertEqual({
            "name": "throughput",
            "task": "search #2",
            "operation": "search",
            "value": {
                "min": 9,
                "mean": 10,
                "median": 10,
                "max": 12,
                "unit": "ops/s"
            }
        }, select(metric_list, "throughput", operation="search"))

        self.assertEqual({
            "name": "service_time",
            "task": "search #2",
            "operation": "search",
            "value": {
                "50": 98,
                "100": 110
            }
        }, select(metric_list, "service_time", operation="search"))

        self.assertEqual({
            "name": "latency",
            "task": "search #2",
            "operation": "search",
            "value": {
                "50": 99,
                "100": 111
            }
        }, select(metric_list, "latency", operation="search"))

        self.assertEqual({
            "name": "error_rate",
            "task": "search #2",
            "operation": "search",
            "value": {
                "single": 0.1
            }
        }, select(metric_list, "error_rate", operation="search"))

        self.assertEqual({
            "name": "ml_processing_time",
            "job": "job_1",
            "value": {
                "min": 3.3,
                "mean": 5.2,
                "median": 5.8,
                "max": 12.34
            }
        }, select(metric_list, "ml_processing_time", job="job_1"))

        self.assertEqual({
            "name": "ml_processing_time",
            "job": "job_2",
            "value": {
                "min": 3.55,
                "mean": 4.2,
                "median": 4.9,
                "max": 9.4
            }
        }, select(metric_list, "ml_processing_time", job="job_2"))

        self.assertEqual({
            "name": "young_gc_time",
            "value": {
                "single": 68
            }
        }, select(metric_list, "young_gc_time"))
        self.assertEqual({
            "name": "young_gc_count",
            "value": {
                "single": 7
            }
        }, select(metric_list, "young_gc_count"))

        self.assertEqual({
            "name": "old_gc_time",
            "value": {
                "single": 0
            }
        }, select(metric_list, "old_gc_time"))
        self.assertEqual({
            "name": "old_gc_count",
            "value": {
                "single": 0
            }
        }, select(metric_list, "old_gc_count"))

        self.assertEqual({
            "name": "merge_time",
            "value": {
                "single": 3702
            }
        }, select(metric_list, "merge_time"))

        self.assertEqual({
            "name": "merge_time_per_shard",
            "value": {
                "min": 40,
                "median": 3702,
                "max": 3900,
                "unit": "ms"
            }
        }, select(metric_list, "merge_time_per_shard"))

        self.assertEqual({
            "name": "merge_count",
            "value": {
                "single": 2
            }
        }, select(metric_list, "merge_count"))

        self.assertEqual({
            "name": "refresh_time",
            "value": {
                "single": 596
            }
        }, select(metric_list, "refresh_time"))

        self.assertEqual({
            "name": "refresh_time_per_shard",
            "value": {
                "min": 48,
                "median": 89,
                "max": 204,
                "unit": "ms"
            }
        }, select(metric_list, "refresh_time_per_shard"))

        self.assertEqual({
            "name": "refresh_count",
            "value": {
                "single": 10
            }
        }, select(metric_list, "refresh_count"))

        self.assertIsNone(select(metric_list, "flush_time"))
        self.assertIsNone(select(metric_list, "flush_time_per_shard"))
        self.assertEqual({
            "name": "flush_count",
            "value": {
                "single": 0
            }
        }, select(metric_list, "flush_count"))


class SystemStatsTests(TestCase):
    def test_as_flat_list(self):
        d = {
            "node_metrics": [
                {
                    "node": "benchmark-node-0",
                    "name": "startup_time",
                    "value": 3.4
                },
                {
                    "node": "benchmark-node-1",
                    "name": "startup_time",
                    "value": 4.2
                },
                {
                    "node": "benchmark-node-0",
                    "name": "index_size",
                    "value": 300 * 1024 * 1024
                },
                {
                    "node": "benchmark-node-1",
                    "name": "index_size",
                    "value": 302 * 1024 * 1024
                },
                {
                    "node": "benchmark-node-0",
                    "name": "bytes_written",
                    "value": 817 * 1024 * 1024
                },
                {
                    "node": "benchmark-node-1",
                    "name": "bytes_written",
                    "value": 833 * 1024 * 1024
                },
            ],
        }

        s = metrics.SystemStats(d)
        metric_list = s.as_flat_list()

        self.assertEqual({
            "node": "benchmark-node-0",
            "name": "startup_time",
            "value": {
                "single": 3.4
            }
        }, select(metric_list, "startup_time", node="benchmark-node-0"))

        self.assertEqual({
            "node": "benchmark-node-1",
            "name": "startup_time",
            "value": {
                "single": 4.2
            }
        }, select(metric_list, "startup_time", node="benchmark-node-1"))

        self.assertEqual({
            "node": "benchmark-node-0",
            "name": "index_size",
            "value": {
                "single": 300 * 1024 * 1024
            }
        }, select(metric_list, "index_size", node="benchmark-node-0"))

        self.assertEqual({
            "node": "benchmark-node-1",
            "name": "index_size",
            "value": {
                "single": 302 * 1024 * 1024
            }
        }, select(metric_list, "index_size", node="benchmark-node-1"))

        self.assertEqual({
            "node": "benchmark-node-0",
            "name": "bytes_written",
            "value": {
                "single": 817 * 1024 * 1024
            }
        }, select(metric_list, "bytes_written", node="benchmark-node-0"))

        self.assertEqual({
            "node": "benchmark-node-1",
            "name": "bytes_written",
            "value": {
                "single": 833 * 1024 * 1024
            }
        }, select(metric_list, "bytes_written", node="benchmark-node-1"))
