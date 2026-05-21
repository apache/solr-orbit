---
title: Metric Records
parent: Metrics Reference
grand_parent: Reference
nav_order: 2
---

# Metric Records

Apache Solr Benchmark stores metrics as individual JSON documents. When the
[filesystem metrics store](filesystem-metrics-store.html) is active (the default),
each document is appended as a single line to
`~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl`.

The following example shows a single `service_time` record produced during a bulk-index
operation on the `nyc_taxis` workload:

```json
{
  "@timestamp": 1691702842821,
  "relative-time-ms": 65.9,
  "test-run-id": "8c43ee4c-cb34-494b-81b2-181be244f832",
  "test-run-timestamp": "20230810T212711Z",
  "environment": "local",
  "workload": "nyc_taxis",
  "test_procedure": "append-no-conflicts",
  "cluster-config-instance": "external",
  "name": "service_time",
  "value": 42.3,
  "unit": "ms",
  "sample-type": "normal",
  "meta": {
    "collection": "nyc_taxis",
    "took": 13,
    "success": true,
    "success-count": 125,
    "error-count": 0
  },
  "task": "bulk-index",
  "operation": "bulk-index",
  "operation-type": "bulk"
}
```

## Field reference

| Field | Description |
|-------|-------------|
| `@timestamp` | The timestamp of when the sample was taken, in milliseconds since the Unix epoch. For request-related measurements this marks the moment Solr Benchmark issued the request. |
| `relative-time-ms` | The relative time since the start of the benchmark, in milliseconds. This is useful for aligning time-series data across multiple test runs because it is always measured from the same benchmark-internal zero point. |
| `test-run-id` | A UUID that uniquely identifies this invocation of the workload. Every metric record from a single run shares the same value. |
| `test-run-timestamp` | The timestamp of when the workload was invoked, always expressed in UTC (for example `20230810T212711Z`). |
| `environment` | The name of the benchmark environment, as set in the configuration. Different benchmark environments can be distinguished using this field when analyzing metrics from multiple setups. |
| `workload` | The name of the workload that produced this metric (for example `nyc_taxis` or `geonames`). |
| `test_procedure` | The name of the test procedure (challenge) that was executed within the workload. |
| `cluster-config-instance` | The name of the cluster configuration instance used during this run (for example `external`, `docker`, `defaults`). |
| `name` | The metric key that identifies what was measured. See [Metric Keys](metrics-reference.html) for the complete list. |
| `value` | The measured value. |
| `unit` | The unit of the measurement, such as `ms`, `bytes`, `ops/s`, or an empty string for dimensionless counts. |
| `sample-type` | Either `warmup` or `normal`. Only `normal` samples are included in the reported percentiles and summaries. Warmup samples are collected for priming the benchmark but excluded from results. |
| `task` | The name of the workload task that produced this sample (corresponds to an operation defined in the workload). |
| `operation` | The operation name within the task (often the same as `task`). |
| `operation-type` | The operation type as registered by the runner, for example `bulk`, `search`, `commit`, or `telemetry`. |
| `meta` | Supplementary context recorded alongside the measurement. Contents vary by operation type — see below. |

## The `meta` object

The `meta` object carries additional context that is specific to the type of operation that
produced the record. Common fields include:

| Field | Description |
|-------|-------------|
| `success` | `true` if the operation completed without an error; `false` if Solr returned an error or the request timed out. |
| `success-count` | For bulk operations, the number of documents successfully indexed in this batch. |
| `error-count` | For bulk operations, the number of documents that failed to index in this batch. |
| `collection` | The Solr collection name targeted by the operation. |
| `took` | The `QTime` value reported by Solr, in milliseconds. |
| `hits` | For search operations, the total number of matching documents reported by Solr. |
| `tag_*` | Any key–value pairs supplied via `--user-tag` are stored with a `tag_` prefix, for example `tag_intention: baseline`. |

Telemetry records (collected by background polling devices) carry additional node-level
context in `meta`, such as the Solr node name.
