---
title: Fine-tuning Workloads
parent: Working with Workloads
grand_parent: User Guide
nav_order: 12
---

# Fine-tuning Workloads

## Overriding parameters at runtime

Workloads can expose Jinja2 parameters that you override at runtime with `--workload-params`.

In `workload.json` (or an included operations file):

{% raw %}
```json
{
  "operation-type": "bulk-index",
  "bulk-size": {{ bulk_size | default(500) }}
}
```
{% endraw %}

Override at runtime:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload my-workload \
  --workload-params "bulk_size:1000"
```

Multiple parameters are separated by commas. Parameter values can be integers, floats,
booleans (`true`/`false`), or quoted strings:

```bash
# Integer and float
--workload-params "bulk_size:5000,target_throughput:25.5"

# Boolean
--workload-params "include_aggs:true,enable_warmup:false"

# String (use quotes around the whole value list if it contains spaces)
--workload-params "collection_name:my_collection,query_type:dismax"
```

The `default()` Jinja2 filter sets the value used when no override is provided. Omitting
`default()` makes the parameter mandatory — Solr Benchmark raises an error if it is not
supplied at run time.
{: .tip}

---

## Controlling throughput

Use `target-throughput` to cap the rate of an operation. The value is **operations per
second across all clients combined**:

```json
{
  "operation": "search",
  "target-throughput": 100,
  "clients": 4
}
```

In the example above, all four clients together issue 100 search requests per second (25
per client). If the operation is slower than the target, Solr Benchmark runs it as fast as
possible without throttling.

Setting `target-throughput` keeps service-time measurements independent of scheduling
overhead, which produces more reproducible and meaningful latency percentiles. Without a
throughput cap, clients run at full speed and the measured latency includes queueing effects
inside Solr.

See [Target throughput](../optimizing-benchmarks/target-throughput.html) for a detailed
explanation of how Solr Benchmark implements throughput control.
{: .note}

---

## Controlling warmup

Use `warmup-time-period` (seconds) or `warmup-iterations` to discard initial measurements
so that JVM JIT compilation and Solr cache warm-up do not skew results:

```json
{
  "operation": "search",
  "warmup-time-period": 60,
  "iterations": 500
}
```

```json
{
  "operation": "bulk-index",
  "warmup-iterations": 100,
  "clients": 8
}
```

Warmup traffic uses the same clients and parameters as the measured traffic — only the
metric recording is suppressed.

---

## Controlling concurrency

Use `clients` to set the number of parallel clients per operation:

```json
{
  "operation": "bulk-index",
  "clients": 8
}
```

Each client receives an equal partition of the corpus. Increasing `clients` can improve
throughput on systems with many CPU cores, but results in higher resource usage on both the
Solr Benchmark host and the Solr cluster.

---

## Controlling duration

Use `time-period` (seconds) to run an operation for a fixed duration instead of a fixed
number of iterations:

```json
{
  "operation": "search",
  "time-period": 120,
  "clients": 4
}
```

Use `iterations` when you need a precise number of samples for percentile calculations.
At least 1,000 iterations are recommended for stable 99th-percentile figures.

---

## Selecting a task subset

Use `--include-tasks` or `--exclude-tasks` to run only part of a schedule during a run:

```bash
# Run only the indexing task
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --include-tasks bulk-index,commit

# Skip slow aggregation tasks
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --exclude-tasks passenger-count-agg
```

This is particularly useful when iterating on a single operation type — for example, tuning
search query performance without waiting for indexing to complete on every run.

---

## Selecting a subset of documents

Use `number-of-docs` and `offset` in the corpus definition to benchmark on a subset of the
data without downloading the full corpus:

```json
{
  "source-file": "files/data.json.gz",
  "document-count": 165346692,
  "number-of-docs": 1000000,
  "offset": 0
}
```

---

## Replicating production characteristics

To produce benchmark results that reflect real-world Solr performance, tune the workload
parameters to match the load pattern of your production system:

- **Indexing throughput**: Adjust `clients` and `bulk-size` to match your production
  indexing rate. More clients increase parallelism; larger bulk size reduces per-request
  overhead.
- **Search rate**: Use `target-throughput` and `clients` to reproduce the number of
  concurrent search requests your cluster handles in production.
- **Read/write mix**: If production traffic is a mix of indexing and querying, consider
  using a `time-period`-based schedule with separate indexing and search tasks running
  back-to-back, rather than a strictly sequential index-then-query approach.
- **Data volume**: Run against a data corpus that matches the size and distribution of your
  production data. Results from a 1-million-document corpus may not accurately predict
  behavior at 100 million documents, where segment merges and cache behavior differ
  significantly.
- **Warmup**: Always include a warmup period (`warmup-time-period` or `warmup-iterations`)
  before recording measurements. Cold JVM and empty Solr caches can inflate latency
  numbers by 2–10× compared to steady-state.
