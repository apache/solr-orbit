---
title: Enabling Telemetry
parent: Understanding Results
grand_parent: User Guide
nav_order: 30
---

# Enabling Telemetry

Apache Solr Benchmark can collect server-side metrics from your Solr cluster during a benchmark
run using *telemetry devices*. Devices are split into two groups:

- **Always-enabled devices** — active on every run, no flag needed.
- **Optional devices** — enabled on demand with `--telemetry <name>`.

## Always-enabled devices

These six devices are active on every benchmark run:

| Device | Description |
|--------|-------------|
| `solr-jvm-stats` | JVM heap, GC pause times, GC counts, threads, buffer pools |
| `solr-node-stats` | CPU, OS memory, file descriptors, HTTP requests, query handler metrics |
| `solr-collection-stats` | Per-collection document counts, deleted docs, segment counts, index size |
| `solr-query-stats` | Query latency percentiles (p50/p99/p99.9), request counts, cache hit ratios |
| `solr-indexing-stats` | Indexing throughput, error counts, merge activity |
| `solr-cache-stats` | Per-cache hit/miss/eviction counts and memory usage |

## Optional telemetry devices

Enable optional devices by passing `--telemetry` with a comma-separated list of device names:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --telemetry segment-stats,shard-stats,cluster-environment-info
```

### Optional devices — all pipelines

REST-based devices that work with any pipeline, including `benchmark-only`:

| Device | Description |
|--------|-------------|
| `segment-stats` | Per-collection segment count, doc count, deleted doc count, and index size via the Luke API; written to `segment_stats.log` on benchmark stop |
| `shard-stats` | Per-shard document count and index size polled from CLUSTERSTATUS + Core STATUS; SolrCloud only — skipped silently on standalone Solr |
| `cluster-environment-info` | Records Solr version, JVM version, JVM vendor, and CPU core count as run metadata once at benchmark start |

### Optional devices — provisioned pipelines only

JVM and process devices that inject flags into `SOLR_OPTS` before Solr starts. Require the
`docker` or `from-distribution` pipeline. They are silently skipped on `benchmark-only`.

| Device | Description |
|--------|-------------|
| `jfr` | Java Flight Recorder — writes `profile.jfr` to the log directory (requires OpenJDK 11+) |
| `gc` | GC logging (`-Xlog:` format) — writes `gc.log` to the log directory |
| `jit` | JIT compiler logging — writes `jit.log` to the log directory |
| `heapdump` | Heap dump (`jmap -dump`) on benchmark stop — writes `heap_at_exit_{pid}.hprof` |
| `disk-io` | Disk I/O bytes read/written by the Solr process (always active on provisioned pipelines) |

**Note:** JVM devices (jfr, gc, jit, heapdump, disk-io) silently skip when pipeline is
`benchmark-only` — no warning is shown in the results.
{: .note}

## When to use optional devices

- **`segment-stats`** — Diagnose segment fragmentation. Run after bulk indexing to see whether
  force-merging improved segment count and deleted doc ratio.
- **`shard-stats`** — Verify document distribution across shards in a SolrCloud cluster. Useful
  for detecting hot shards or uneven distribution.
- **`cluster-environment-info`** — Audit metadata. Adds Solr version and JVM info to every run
  record so you can compare results across Solr versions.
- **`jfr`, `gc`, `jit`** — Profiling during provisioned benchmark runs. Use these when
  diagnosing JVM performance issues (GC pressure, JIT regressions, etc.).
- **`heapdump`** — Capture a heap snapshot on benchmark completion. Use for offline memory
  analysis with tools like Eclipse MAT or VisualVM.

## Telemetry output

Telemetry metrics are included in the `results.json` file alongside the workload operation
metrics. They are also printed as additional rows in the console summary table.

See [Telemetry Devices](../../reference/telemetry.html) for full device documentation, metric
names, and configuration options.

## Solr version compatibility

Both Solr 9.x and Solr 10.x expose metrics at `/solr/admin/metrics`. The response format
differs: Solr 9.x returns custom JSON, Solr 10.x returns Prometheus text format. Apache Solr
Benchmark auto-detects the format via the HTTP `Content-Type` header at runtime. No
configuration is required.
