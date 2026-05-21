---
title: Telemetry Devices
parent: Reference
nav_order: 45
---

# Telemetry Devices

Apache Solr Benchmark includes telemetry devices for collecting server-side metrics. Six devices are **always enabled** and collect metrics automatically without any flags. One additional device (`disk-io`) runs automatically on provisioned pipelines. Eight further devices can be enabled on demand with `--telemetry`.

Both Solr 9.x (JSON format) and Solr 10.x (Prometheus text format) are supported. Format detection is automatic via the HTTP `Content-Type` header.

---

## solr-jvm-stats

Collects JVM statistics from each Solr node via the Solr metrics API.

**Always active.** No `--telemetry` flag required.

**Metrics collected:**

| Metric | Unit | Description |
|--------|------|-------------|
| `jvm_heap_used_bytes` | bytes | JVM heap memory currently used |
| `jvm_heap_max_bytes` | bytes | Maximum JVM heap size |
| `jvm_gc_count` | count | Total GC collections across all collectors |
| `jvm_gc_time_ms` | ms | Total GC wall time across all collectors |
| `jvm_gc_young_count` | count | Young-generation GC collection count |
| `jvm_gc_young_time_ms` | ms | Young-generation GC wall time |
| `jvm_gc_old_count` | count | Old-generation GC collection count |
| `jvm_gc_old_time_ms` | ms | Old-generation GC wall time |
| `jvm_thread_count` | count | Current JVM thread count |
| `jvm_thread_peak_count` | count | Peak JVM thread count since startup |
| `jvm_buffer_pool_direct_bytes` | bytes | Direct byte buffer pool memory used |
| `jvm_buffer_pool_mapped_bytes` | bytes | Memory-mapped buffer pool memory used |

---

## solr-node-stats

Collects Solr node-level and OS statistics.

**Always active.** No `--telemetry` flag required.

**Metrics collected:**

| Metric | Unit | Description |
|--------|------|-------------|
| `cpu_usage_percent` | % | Process CPU load (0–100) |
| `os_memory_free_bytes` | bytes | Free physical OS memory |
| `node_file_descriptors_open` | count | Currently open file descriptors |
| `node_file_descriptors_max` | count | Maximum allowed file descriptors |
| `node_http_requests_total` | count | Total HTTP requests processed by Jetty |
| `query_handler_requests_total` | count | Total `/select` query handler requests |
| `query_handler_errors_total` | count | Total `/select` query handler errors |
| `query_handler_avg_latency_ms` | ms | Rolling average `/select` request latency |

---

## solr-collection-stats

Collects per-collection document count, segment count, and deleted doc count.

**Always active.** No `--telemetry` flag required.

**Metrics collected** (all tagged with `collection` metadata):

| Metric | Unit | Description |
|--------|------|-------------|
| `num_docs` | docs | Current document count |
| `num_deleted_docs` | docs | Number of deleted (soft-deleted) documents |
| `segment_count` | count | Number of Lucene segments |
| `index_size_bytes` | bytes | Total index size on disk |

**Notes:** Collection stats are polled every 30 seconds by default. Override with `--telemetry-params collection-stats-sample-interval:60`. Uses both the Collections API and the Luke request handler (`/admin/luke`) for full statistics.

---

## solr-query-stats

Collects query latency percentiles and filter cache hit ratio.

**Always active.** No `--telemetry` flag required.

**Metrics collected:**

| Metric | Unit | Description |
|--------|------|-------------|
| `query_latency_p50_ms` | ms | 50th percentile `/select` request latency |
| `query_latency_p99_ms` | ms | 99th percentile `/select` request latency |
| `query_latency_p999_ms` | ms | 99.9th percentile `/select` request latency |
| `query_requests_total` | count | Total `/select` handler request count |
| `query_errors_total` | count | Total `/select` handler error count |
| `query_cache_hit_ratio` | ratio | Filter cache hit ratio (0.0–1.0) |

---

## solr-indexing-stats

Collects update handler and merge metrics.

**Always active.** No `--telemetry` flag required.

**Metrics collected:**

| Metric | Unit | Description |
|--------|------|-------------|
| `indexing_requests_total` | count | Total `/update` handler requests |
| `indexing_errors_total` | count | Total `/update` handler errors |
| `indexing_avg_time_ms` | ms | Rolling average `/update` request time |
| `index_merge_major_running` | count | Currently running major merges |
| `index_merge_minor_running` | count | Currently running minor merges |

---

## solr-cache-stats

Collects hit/miss/eviction and memory statistics for the three primary Solr caches.

**Always active.** No `--telemetry` flag required.

**Metrics collected** (all tagged with `cache` metadata: `queryResultCache`, `filterCache`, `documentCache`):

| Metric | Unit | Description |
|--------|------|-------------|
| `cache_hits_total` | count | Cache hits since Solr start |
| `cache_inserts_total` | count | Cache inserts since Solr start |
| `cache_evictions_total` | count | Cache evictions since Solr start |
| `cache_memory_bytes` | bytes | RAM used by this cache |
| `cache_hit_ratio` | ratio | Hit ratio (0.0–1.0) |

---

## Always-on provisioned-pipeline device

The following device activates automatically when using the `docker` or `from-distribution` pipeline. It cannot be disabled and does not need to be listed in `--telemetry`.

### disk-io

Measures disk I/O consumed by the Solr process during the benchmark run.

**Pipeline:** `docker` or `from-distribution` (always active; not available on `benchmark-only`)

| Metric | Unit | Description |
|--------|------|-------------|
| `disk_io_read_bytes` | bytes | Bytes read by the Solr process |
| `disk_io_write_bytes` | bytes | Bytes written by the Solr process |

---

## Optional devices

Optional devices must be explicitly requested with `--telemetry <name>`. REST-based optional
devices work with all pipelines. JVM/process devices inject flags into `SOLR_OPTS` before Solr
starts and require the `docker` or `from-distribution` pipeline — they are silently skipped on
`benchmark-only`.

---

### segment-stats

Captures per-collection segment statistics via the Solr Luke request handler.

**Pipeline:** All pipelines
**Enable:** `--telemetry segment-stats`

Collected on benchmark stop. Results are written to `segment_stats.log` in the benchmark log directory.

| Metric (in log file) | Description |
|----------------------|-------------|
| `numDocs` | Current document count |
| `maxDoc` | Maximum doc ID (includes deleted docs) |
| `deletedDocs` | Number of soft-deleted documents |
| `segmentCount` | Number of Lucene segments |
| `sizeInBytes` | Total index size on disk |

---

### shard-stats

Polls CLUSTERSTATUS and Core STATUS for each shard leader and records per-shard metrics. Skipped silently on standalone (non-SolrCloud) Solr.

**Pipeline:** All pipelines
**Enable:** `--telemetry shard-stats`

| Metric | Unit | Description |
|--------|------|-------------|
| `shard_{name}_num_docs` | count | Document count for the named shard |
| `shard_{name}_size_bytes` | bytes | Index size for the named shard |

The default poll interval is 60 seconds. Override with `--telemetry-params shard-stats-sample-interval:30`.

---

### cluster-environment-info

Records Solr version, JVM version, and hardware info as run metadata. Called once at benchmark start.

**Pipeline:** All pipelines
**Enable:** `--telemetry cluster-environment-info`

| Metadata key | Description |
|--------------|-------------|
| `distribution_version` | Solr version string (e.g. `9.7.0`) |
| `jvm_version` | JVM version (e.g. `21.0.1`) |
| `jvm_vendor` | JVM vendor name (e.g. `OpenJDK 21`) |
| `cpu_logical_cores` | Number of logical CPU cores on the node |
| `cluster_node_count` | Number of live SolrCloud nodes |

---

### jfr

Enables Java Flight Recorder. Injects `-XX:StartFlightRecording=...` into `SOLR_OPTS`.

**Pipeline:** `docker` or `from-distribution` only
**Enable:** `--telemetry jfr`

The flight recording is written to `profile.jfr` in the benchmark log directory. Requires OpenJDK 11 or later. To use a custom recording template, pass `--telemetry-params recording-template:/path/to/template.jfc`.

---

### gc

Enables GC logging (Java 9+ `-Xlog:` format). Injects the GC log flags into `SOLR_OPTS`.

**Pipeline:** `docker` or `from-distribution` only
**Enable:** `--telemetry gc`

GC output is written to `gc.log` in the benchmark log directory. The default log configuration is `gc*=info,safepoint=info,age*=trace`. Override with `--telemetry-params gc-log-config:gc*=debug`.

---

### jit

Enables JIT compiler logging. Injects `-XX:+LogCompilation` and related flags into `SOLR_OPTS`.

**Pipeline:** `docker` or `from-distribution` only
**Enable:** `--telemetry jit`

JIT output is written to `jit.log` in the benchmark log directory.

---

### heapdump

Captures a heap dump (`jmap -dump`) from the Solr JVM when the benchmark finishes.

**Pipeline:** `docker` or `from-distribution` only
**Enable:** `--telemetry heapdump`

The heap dump is written to `heap_at_exit_{pid}.hprof` in the benchmark log directory. On Docker pipelines, `docker exec` is used automatically.

---

## Using multiple devices

The six always-on devices collect metrics automatically — no flags required:

```bash
# Always-on devices activate without any --telemetry flag:
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis
```

Add optional REST devices on any pipeline:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --telemetry segment-stats,shard-stats,cluster-environment-info
```

Add JVM profiling devices on provisioned pipelines:

```bash
solr-benchmark run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --telemetry gc,jfr
```

## Telemetry output location

Telemetry metrics are written to the metrics store alongside all other benchmark metrics. When using the filesystem store, they are recorded in `metrics.jsonl` in the test run directory (`~/.solr-benchmark/benchmarks/test-runs/<run-id>/`). See [Filesystem Metrics Store](metrics/filesystem-metrics-store.html) for the file format.
