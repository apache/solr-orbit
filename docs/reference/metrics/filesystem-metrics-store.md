---
title: Filesystem Metrics Store
parent: Metrics Reference
grand_parent: Reference
nav_order: 1
---

# Filesystem Metrics Store

The filesystem metrics store is an opt-in extension of the default in-memory store.
It keeps all metric records in RAM and additionally streams each metric document to a
`metrics.jsonl` file on disk as the benchmark runs, making raw samples available for
offline analysis even after the process exits.

The default metrics store is **in-memory**. Enable the filesystem store explicitly when
you need access to individual raw samples after the run.

## Configuration

The store type is controlled by the `datastore.type` key under the `[reporting]` section in
`~/.solr-benchmark/benchmark.ini`:

```ini
[reporting]
# Default: in-memory (no disk writes for raw samples)
# Set to "filesystem" to also stream raw metric documents to metrics.jsonl
datastore.type = filesystem
```

## File layout

When the filesystem metrics store is active, the following structure is created under
`~/.solr-benchmark/` after a completed benchmark run:

```
~/.solr-benchmark/
└── benchmarks/
    └── test-runs/
        └── <run-id>/
            ├── test_run.json   # full run record with calculated results
            └── metrics.jsonl   # raw metric documents, one JSON object per line
```

`test_run.json` is written by the test-run store after every run regardless of which
metrics store is active.

### `test_run.json`

Contains the full computed results (percentiles, error rates, throughput summaries)
together with workload metadata and benchmark environment information.

### `metrics.jsonl`

Written incrementally during the run, one JSON object per line.
Lines are written with line buffering, so no data is lost if the process is killed after
the first measurement.

Example line:

```json
{"test-run-id":"abc123","environment":"local","workload":"nyc_taxis","test_procedure":"append-no-conflicts","name":"service_time","value":42.7,"unit":"ms","task":"index","operation-type":"bulk","sample-type":"normal","absolute-time-ms":1709123456789,"relative-time-ms":1234,"meta":{"success":true}}
```

## Inspecting raw metrics

### Using `jq`

List all distinct metric names recorded in a run:

```sh
jq -r '.name' ~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl | sort -u
```

Compute the median service time for a task:

```sh
jq 'select(.name=="service_time" and .task=="index") | .value' \
  ~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl \
  | sort -n | awk '{a[NR]=$0} END{print a[int(NR/2)]}'
```

### Using Python

```python
import json

with open("~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl") as f:
    docs = [json.loads(line) for line in f]

service_times = [d["value"] for d in docs if d["name"] == "service_time"]
print(f"Samples: {len(service_times)}, avg: {sum(service_times)/len(service_times):.2f} ms")
```

### Pretty-printing a single line

```sh
head -1 ~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl | python3 -m json.tool
```
