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

"""Unit tests for osbenchmark/result_writer.py"""

import os
import tempfile
import unittest

from osbenchmark.result_writer import (
    LocalFilesystemResultWriter,
    create_writer,
)
from osbenchmark import exceptions


class TestLocalFilesystemResultWriter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.writer = LocalFilesystemResultWriter(results_path=self.tmpdir)

    def _run_id(self):
        return "2024-01-01T12-00-00"

    def _metadata(self):
        return {
            "run_id": self._run_id(),
            "workload": "test-workload",
            "challenge": "test-challenge",
            "solr_version": "9.7.0",
        }

    def _metrics(self):
        return [
            {
                "name": "throughput",
                "value": 1234.5,
                "unit": "docs/s",
                "task": "bulk-index",
                "operation_type": "bulk-index",
                "sample_type": "normal",
                "timestamp": 1234567890.0,
            },
            {
                "name": "latency_p99",
                "value": 42.0,
                "unit": "ms",
                "task": "search",
                "operation_type": "search",
                "sample_type": "warmup",
                "timestamp": 1234567891.0,
            },
        ]

    def test_lifecycle_creates_output_files(self):
        metadata = self._metadata()
        metrics = self._metrics()

        self.writer.open(metadata)
        self.writer.write(metrics)
        self.writer.close()

        run_dir = os.path.join(self.tmpdir, self._run_id())
        self.assertTrue(os.path.isdir(run_dir))
        # test_run.json is copied from the test-runs store (may not exist in unit test env)
        self.assertTrue(os.path.isfile(os.path.join(run_dir, "results.csv")))
        self.assertTrue(os.path.isfile(os.path.join(run_dir, "summary.txt")))
        # No custom results.json is generated (test_run.json is the canonical format)
        self.assertFalse(os.path.isfile(os.path.join(run_dir, "results.json")))

    def test_csv_output_contains_metrics(self):
        """CSV file contains at least one data row for each non-warmup metric."""
        metadata = self._metadata()
        metrics = self._metrics()

        self.writer.open(metadata)
        self.writer.write(metrics)
        self.writer.close()

        csv_path = os.path.join(self.tmpdir, self._run_id(), "results.csv")
        with open(csv_path) as f:
            content = f.read()

        # The throughput metric (sample_type: normal) should appear in CSV
        self.assertIn("throughput", content)

    def test_csv_output_skipped_when_no_metrics(self):
        self.writer.open(self._metadata())
        # No write() call
        self.writer.close()
        run_dir = os.path.join(self.tmpdir, self._run_id())
        # CSV is skipped when empty; no custom results.json is generated
        self.assertFalse(os.path.isfile(os.path.join(run_dir, "results.json")))
        self.assertFalse(os.path.isfile(os.path.join(run_dir, "results.csv")))

    def test_close_is_idempotent(self):
        self.writer.open(self._metadata())
        self.writer.close()
        # Second close should not raise
        self.writer.close()

    def test_summary_excludes_warmup(self):
        metadata = self._metadata()
        metrics = self._metrics()

        self.writer.open(metadata)
        self.writer.write(metrics)
        self.writer.close()

        with open(os.path.join(self.tmpdir, self._run_id(), "summary.txt")) as f:
            summary = f.read()

        self.assertIn("bulk-index", summary)
        # warmup metric should not appear in summary
        self.assertNotIn("warmup", summary)


class TestCreateWriter(unittest.TestCase):
    def test_create_local_filesystem_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = create_writer("local_filesystem", results_path=tmpdir)
            self.assertIsInstance(writer, LocalFilesystemResultWriter)

    def test_unknown_writer_raises(self):
        with self.assertRaises(exceptions.SystemSetupError):
            create_writer("nonexistent_writer", results_path="/tmp")


if __name__ == "__main__":
    unittest.main()
