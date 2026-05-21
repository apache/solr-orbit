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

import csv
import logging
import os
import shutil
from abc import ABC, abstractmethod

import tabulate as tabulate_lib

from osbenchmark import exceptions

logger = logging.getLogger(__name__)


class ResultWriter(ABC):
    """
    Abstract base class for all benchmark result output destinations.

    Contract:
    - open() is always called before the first write().
    - write() may be called zero or more times.
    - close() is always called exactly once, even if a previous method raised.
    - close() must be safe to call multiple times (idempotent).
    - Implementations must not suppress exceptions from open() or write().
    """

    @abstractmethod
    def open(self, run_metadata: dict) -> None:
        """
        Called once before any metrics are written.

        Args:
            run_metadata: dict with at minimum:
                - "run_id":     str  — unique run identifier (ISO timestamp)
                - "workload":   str  — workload name
                - "challenge":  str  — challenge name
                - "solr_version": str — detected Solr version string
        """

    @abstractmethod
    def write(self, metrics: list) -> None:
        """
        Write a batch of metric record dicts.

        Each record dict contains:
            - "name":           str   — metric name
            - "value":          float — numeric value
            - "unit":           str   — unit string
            - "task":           str   — operation name
            - "operation_type": str   — operation type
            - "sample_type":    str   — "normal" or "warmup"
            - "timestamp":      float — Unix epoch seconds
            - "meta":           dict  — optional extra labels
        """

    @abstractmethod
    def close(self) -> None:
        """Flush and close. Idempotent — safe to call multiple times."""


class LocalFilesystemResultWriter(ResultWriter):
    """
    Writes benchmark results to the local filesystem.

    Output layout:
        {results_path}/{run_id}/
            results.json   — all metrics as JSON array
            results.csv    — flattened CSV
            summary.txt    — markdown table (also printed to stdout)
    """

    def __init__(self, results_path: str):
        self._results_path = results_path
        self._run_dir = None
        self._run_metadata = None
        self._metrics = []
        self._opened = False

    def open(self, run_metadata: dict) -> None:
        self._run_metadata = run_metadata
        run_id = run_metadata.get("run_id", "unknown")
        timestamp = run_metadata.get("timestamp")

        # Create a descriptive folder name with timestamp
        # Format: YYYYMMDD_HHMMSS_<first8-of-uuid>
        # Example: 20260222_143052_7a82f1ea
        if timestamp and run_id != "unknown":
            from datetime import datetime
            # timestamp can be either a datetime object or Unix timestamp (float/int)
            if isinstance(timestamp, datetime):
                time_str = timestamp.strftime("%Y%m%d_%H%M%S")
            elif isinstance(timestamp, (int, float)):
                import time
                time_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(timestamp))
            else:
                # Unknown timestamp type, fall back to run_id only
                logger.warning("Unknown timestamp type: %s, using run_id only", type(timestamp))
                time_str = None

            if time_str:
                # Use first 8 chars of run_id for uniqueness
                run_id_short = run_id[:8] if len(run_id) >= 8 else run_id
                folder_name = f"{time_str}_{run_id_short}"
            else:
                folder_name = run_id
        else:
            # Fallback to just run_id if no timestamp
            folder_name = run_id

        self._run_dir = os.path.join(self._results_path, folder_name)
        os.makedirs(self._run_dir, exist_ok=True)
        self._metrics = []
        self._opened = True
        logger.info("Result writer opened, output dir: %s", self._run_dir)

    def write(self, metrics: list) -> None:
        self._metrics.extend(metrics)

    def close(self) -> None:
        if not self._opened:
            return
        self._opened = False
        if not self._metrics:
            logger.warning("No metrics to write — result files will be empty")

        self._copy_test_run_json()
        self._write_csv()
        summary = self._write_summary()
        print(summary)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _copy_test_run_json(self) -> None:
        """
        Copy test_run.json from the test-runs store to the results directory.
        This file is the complete canonical record of the benchmark run.
        """
        run_id = self._run_metadata.get("run_id", "unknown")
        if run_id == "unknown":
            logger.warning("No run_id available, cannot copy test_run.json")
            return

        # Determine test-runs directory from results path
        # results_path is like ~/.solr-benchmark/results
        # test-runs path is like ~/.solr-benchmark/benchmarks/test-runs/<run-id>/test_run.json
        benchmark_root = os.path.dirname(self._results_path)
        test_runs_dir = os.path.join(benchmark_root, "benchmarks", "test-runs")
        source_path = os.path.join(test_runs_dir, run_id, "test_run.json")
        dest_path = os.path.join(self._run_dir, "test_run.json")

        if os.path.exists(source_path):
            try:
                shutil.copy2(source_path, dest_path)
                logger.info("Copied test_run.json from %s to %s", source_path, dest_path)
            except Exception as e:
                logger.warning("Failed to copy test_run.json: %s", e)
        else:
            logger.warning("Source test_run.json not found at %s", source_path)

    def _write_csv(self) -> None:
        if not self._metrics:
            return
        path = os.path.join(self._run_dir, "results.csv")
        fieldnames = ["name", "value", "unit", "task", "operation_type", "sample_type", "timestamp"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self._metrics)
        logger.info("Wrote %s", path)

    def _write_summary(self) -> str:
        if not self._metrics:
            return "(no metrics recorded)"

        normal = [m for m in self._metrics if m.get("sample_type") != "warmup"]
        rows = [
            [m.get("task", ""), m.get("name", ""), m.get("value", ""), m.get("unit", "")]
            for m in normal
        ]
        table = tabulate_lib.tabulate(
            rows,
            headers=["Task", "Metric", "Value", "Unit"],
            tablefmt="pipe",
            numalign="right",
            stralign="left",
        )
        summary = f"\n## Benchmark Results\n\n{table}\n"
        path = os.path.join(self._run_dir, "summary.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(summary)
        logger.info("Wrote %s", path)
        return summary


# ------------------------------------------------------------------
# Registry and factory
# ------------------------------------------------------------------

WRITER_REGISTRY = {
    "local_filesystem": None,  # populated below to avoid forward reference
}


def create_writer(name: str, **kwargs) -> ResultWriter:
    """
    Instantiate a ResultWriter by registry name.

    Args:
        name:   Registry key (e.g. "local_filesystem").
        kwargs: Constructor arguments forwarded to the writer class.

    Raises:
        exceptions.SystemSetupError: if name is not registered.
    """
    registry = {
        "local_filesystem": LocalFilesystemResultWriter,
    }
    if name not in registry:
        raise exceptions.SystemSetupError(
            f"Unknown results_writer '{name}'. "
            f"Available: {', '.join(registry)}"
        )
    return registry[name](**kwargs)
