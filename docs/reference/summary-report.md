---
title: Summary Report Format
parent: Reference
nav_order: 40
---

# Summary Report Format

Apache Solr Benchmark saves results in JSON and CSV format to `~/.solr-benchmark/benchmarks/test-runs/<run-id>/`.

## JSON format

The `results.json` file contains an array of metric objects, one per recorded metric per task:

```json
[
  {
    "task": "bulk-index",
    "operation": "bulk-index",
    "throughput": {
      "mean": 4500.0,
      "unit": "docs/s"
    },
    "latency": {
      "50": 12.3,
      "90": 18.7,
      "99": 25.1,
      "99.9": 32.4,
      "unit": "ms"
    },
    "error_rate": 0.0,
    "duration": 120.5
  },
  {
    "task": "search",
    "operation": "search",
    "throughput": {
      "mean": 120.0,
      "unit": "ops/s"
    },
    "latency": {
      "50": 5.1,
      "90": 9.3,
      "99": 15.2,
      "99.9": 22.8,
      "unit": "ms"
    },
    "error_rate": 0.0,
    "duration": 20.1
  }
]
```

## CSV format

The `results.csv` file contains the same data in tabular form, with one row per metric per task. Column names match the JSON field names.

## Run metadata

Each run also produces a `test_run.json` file alongside the results:

```json
{
  "test_run_id": "20240115T120000Z",
  "workload": "nyc_taxis",
  "test_procedure": "append-no-conflicts",
  "pipeline": "benchmark-only",
  "target_hosts": ["localhost:8983"],
  "start_time": "2024-01-15T12:00:00Z",
  "end_time": "2024-01-15T12:05:00Z",
  "solr_version": "9.10.1"
}
```

## Metric definitions

| Field | Description |
|-------|-------------|
| `task` | Name of the schedule step |
| `operation` | Operation type (e.g., `bulk-index`, `search`) |
| `throughput.mean` | Mean throughput over the measurement period |
| `throughput.unit` | `docs/s` for indexing, `ops/s` for queries |
| `latency.50` … `latency.99.9` | Latency percentiles in milliseconds |
| `error_rate` | Fraction of operations that returned an error (0.0 to 1.0) |
| `duration` | Total task duration in seconds |
