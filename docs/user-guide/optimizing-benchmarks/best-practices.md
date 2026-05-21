---
title: Performance Testing Best Practices
parent: Optimizing Benchmarks
grand_parent: User Guide
nav_order: 20
---

# Performance Testing Best Practices

Following consistent methodology produces benchmark results you can trust and compare over time. This page summarizes the most important practices for running Apache Solr Benchmark.

## Use a dedicated, stable environment

Benchmark results are only meaningful when the environment is consistent across runs. Avoid:

- Running other workloads on the benchmark host or the Solr nodes during the test
- Sharing the Solr cluster with production traffic
- Running benchmarks on laptops or developer machines (thermal throttling, background processes)

Use dedicated hardware or fixed-size cloud instances, and keep the OS, JVM, and Solr version pinned.

## Always warm up before measuring

Cold runs produce misleading results because:
- The JVM has not JIT-compiled the hot code paths
- Solr's filter cache and query result cache are empty
- OS page cache may not contain index data

Use `warmup-iterations` or `warmup-time-period` in your test procedure to discard the first N operations from measurement:

```json
{
  "operation": "search",
  "clients": 4,
  "warmup-iterations": 500,
  "iterations": 2000
}
```

A warm-up of 100–500 iterations (or 30–60 seconds) is typical for query tasks. For indexing, allow at least one full merge cycle to complete before measuring.

## Run multiple iterations and aggregate

A single benchmark run can be influenced by transient noise (GC pause, OS scheduling, network blip). Run the workload three or more times and use `solr-benchmark aggregate` to combine the results:

```bash
solr-benchmark run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --test-iterations 3 \
  --aggregate true \
  --sleep-timer 60
```

The aggregated output includes the mean relative standard deviation (RSD). An RSD below 5% indicates good result stability.

## Tag your runs

Use `--user-tag` to attach metadata to each run. This makes it easy to filter results when comparing configurations:

```bash
solr-benchmark run \
  --workload nyc_taxis \
  --user-tag "heap:4g,gc:g1gc,version:9.10.1"
```

## Use --test-mode before committing to a full run

Before running a multi-hour benchmark, validate your workload with `--test-mode` (≤1,000 documents, abbreviated schedule). This catches configuration errors quickly without wasting time.

## Let the cluster reach steady state between runs

After indexing large datasets, Solr may continue background merging for minutes or even hours. Wait for merge activity to subside (check the Solr admin UI or the `solr-indexing-stats` telemetry output) before starting the query-focused portion of your benchmark.

## Capture telemetry alongside results

Enable at least `solr-jvm-stats` and `solr-node-stats` on every run:

```bash
solr-benchmark run \
  --workload nyc_taxis \
  --telemetry solr-jvm-stats,solr-node-stats
```

JVM GC pauses are a common explanation for latency spikes. Having telemetry data lets you correlate benchmark metrics with system-level events.

## Compare, don't just measure

A single number is hard to interpret. Use `solr-benchmark compare` to evaluate whether a configuration change improved or regressed performance:

```bash
solr-benchmark compare \
  --baseline 20260101_120000_abc12345 \
  --contender 20260220_143052_a34ff090
```

A negative diff in latency and a positive diff in throughput indicate improvement.

## Document your setup

For every benchmark, record:
- Solr version and configuration (number of shards, replicas, heap size)
- Hardware specs (CPU, RAM, disk type)
- Workload name, challenge, and key parameters
- Any non-default JVM flags or OS tuning

Use `--user-tag` to capture the key facts inside the result file itself.
