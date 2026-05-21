---
title: Metric Keys
parent: Metrics Reference
grand_parent: Reference
nav_order: 3
---

# Metric Keys

This page lists every metric key that Apache Solr Benchmark can record. Metric keys appear
in the `name` field of [metric records](metric-records.html).

Metrics fall into two broad groups:

- **Task-level metrics** — recorded once per operation sample, tied to a specific workload task
- **Telemetry metrics** — recorded by background polling devices throughout the run, independent of any task

---

## Task-level metrics

### `latency`

The time period between submitting a request and receiving the complete response, in
milliseconds. Latency includes any time the operation spent waiting in Solr Benchmark's
internal scheduling queue before being sent to the Solr cluster.

When the workload is not rate-limited (no target throughput), latency and service time are
equal. When a target throughput is configured and demand exceeds capacity, latency grows
while service time stays constant.

### `service_time`

The time period between sending a request to Solr and receiving the corresponding response,
in milliseconds. Unlike latency, service time excludes any time the operation spent waiting
in the client-side scheduling queue.

### `processing_time`

The time period from when Solr Benchmark starts processing the operation (including
client-side serialization, parameter setup, and response parsing) to when it receives the
complete response from Solr, in milliseconds. Processing time includes all client-side
overhead and is always greater than or equal to service time.

### `throughput`

The number of operations that Solr Benchmark completed within a unit of time, expressed
as operations per second (`ops/s`). For bulk-indexing tasks the unit may instead be
`docs/s` or `MB/s` depending on workload configuration.

---

## Disk I/O metrics

### `disk_io_write_bytes`

The number of bytes written to disk during the benchmark. On Linux, only bytes written by
the Solr Benchmark process are counted. On macOS, the total is system-wide and may include
writes from other processes.

### `disk_io_read_bytes`

The number of bytes read from disk during the benchmark.

---

## JVM metrics (SolrJvmStats)

Collected every 5 seconds from the Solr `/admin/metrics?group=jvm` endpoint. Both Solr 9.x
(JSON) and Solr 10.x (Prometheus) response formats are handled automatically.

### `jvm_heap_used_bytes`

The amount of JVM heap memory currently in use, in bytes.

### `jvm_heap_max_bytes`

The maximum JVM heap size configured for the Solr process, in bytes.

### `jvm_gc_count`

The cumulative total number of garbage-collection events across all collectors (young and
old generation combined).

### `jvm_gc_time_ms`

The cumulative total time spent in garbage collection across all collectors, in milliseconds.

### `jvm_gc_young_count`

The cumulative number of young-generation (minor) garbage-collection events. The specific
collector name (G1 Young Generation, ParNew, and so on) varies with the JVM configuration.

### `jvm_gc_young_time_ms`

The cumulative time spent in young-generation garbage collection, in milliseconds.

### `jvm_gc_old_count`

The cumulative number of old-generation (major) garbage-collection events.

### `jvm_gc_old_time_ms`

The cumulative time spent in old-generation garbage collection, in milliseconds.

### `jvm_thread_count`

The current number of live JVM threads in the Solr process.

### `jvm_thread_peak_count`

The peak number of live JVM threads since the Solr process started.

### `jvm_buffer_pool_direct_bytes`

The amount of memory used by the JVM direct byte-buffer pool, in bytes. Solr uses direct
buffers extensively for network I/O and memory-mapped file access.

### `jvm_buffer_pool_mapped_bytes`

The amount of memory used by the JVM memory-mapped buffer pool, in bytes.

---

## Node metrics (SolrNodeStats)

Collected from `/api/node/system` and `/admin/metrics` endpoints. Both Solr 9.x (JSON) and
Solr 10.x (Prometheus) response formats are handled automatically.

### `cpu_usage_percent`

The CPU usage of the Solr process (or, where `processCpuLoad` is not available, the
system-wide CPU load), expressed as a percentage from 0 to 100.

### `os_memory_free_bytes`

The amount of free physical memory available to the operating system, in bytes, as reported
by the JVM OS management bean.

### `node_file_descriptors_open`

The current number of open file descriptors held by the Solr process.

### `node_file_descriptors_max`

The maximum number of file descriptors the Solr process is allowed to open (the system
limit).

### `node_http_requests_total`

The cumulative total number of HTTP requests handled by Solr's embedded Jetty server since
startup.

### `query_handler_requests_total`

The cumulative total number of requests handled by the `/select` query handler.

### `query_handler_errors_total`

The cumulative total number of errors returned by the `/select` query handler.

### `query_handler_avg_latency_ms`

The rolling mean (exponentially weighted moving average) of request latency for the
`/select` query handler, in milliseconds. This reflects Solr's internal view of query
latency, independent of network round-trip time.

---

## Collection metrics (SolrCollectionStats)

Collected every 30 seconds per collection. Data is fetched from the collection
`core-properties` API and the Luke request handler.

### `num_docs`

The total number of live (non-deleted) documents in the collection, summed across all
shards.

### `index_size_bytes`

The on-disk size of the collection index (heap usage of the index, as reported by Solr),
in bytes. Summed across all shards.

### `segment_count`

The total number of Lucene segments open in the collection's searcher, summed across all
shards. A high segment count relative to the document count typically indicates that a
merge is needed.

### `num_deleted_docs`

The total number of deleted (but not yet merged away) documents in the collection. These
documents consume disk space until a merge removes them.

---

## Query statistics (SolrQueryStats)

Collected from the `/admin/metrics` endpoint. Telemetry device `SolrQueryStats` must be
enabled via `--telemetry solr-query-stats`.

### `query_latency_p50_ms`

The 50th-percentile (median) rolling query latency for the `/select` handler, in
milliseconds, as reported by Solr's internal timer.

### `query_latency_p99_ms`

The 99th-percentile rolling query latency, in milliseconds.

### `query_latency_p999_ms`

The 99.9th-percentile rolling query latency, in milliseconds.

### `query_requests_total`

Alias of [`query_handler_requests_total`](#query_handler_requests_total) — cumulative total
requests to the `/select` handler.

### `query_errors_total`

Alias of [`query_handler_errors_total`](#query_handler_errors_total) — cumulative total
errors from the `/select` handler.

### `query_cache_hit_ratio`

The hit ratio (0.0–1.0) of the Solr filter cache (`filterCache`). A value of 1.0 means
all filter queries were served from cache; 0.0 means all required a full disk read.

---

## Indexing statistics (SolrIndexingStats)

Collected from the `/admin/metrics` endpoint. Telemetry device `SolrIndexingStats` must be
enabled via `--telemetry solr-indexing-stats`.

### `indexing_requests_total`

The cumulative total number of requests handled by the `/update` handler (documents sent
to Solr for indexing).

### `indexing_errors_total`

The cumulative total number of errors returned by the `/update` handler.

### `indexing_avg_time_ms`

The rolling mean request time for the `/update` handler, in milliseconds, as reported by
Solr's internal timer.

### `index_merge_major_running`

The current number of major Lucene segment merges in progress. Major merges combine many
segments and are typically I/O intensive.

### `index_merge_minor_running`

The current number of minor Lucene segment merges in progress.

---

## Cache statistics (SolrCacheStats)

Collected from the `/admin/metrics` endpoint per cache. Telemetry device `SolrCacheStats`
must be enabled via `--telemetry solr-cache-stats`. Statistics are reported separately for
three caches: `queryResultCache`, `filterCache`, and `documentCache`. Each record carries a
`cache` field in its `meta` object identifying which cache it belongs to.

### `cache_hits_total`

Cumulative total number of cache lookups that found a cached entry.

### `cache_inserts_total`

Cumulative total number of entries inserted into the cache (roughly equal to the number of
cache misses).

### `cache_evictions_total`

Cumulative total number of entries evicted from the cache to make room for new entries.
High eviction rates suggest the cache is undersized relative to the working set.

### `cache_memory_bytes`

The amount of RAM currently used by the cache, in bytes.

### `cache_hit_ratio`

The ratio of cache hits to total lookups (0.0–1.0). Equivalent to
`cache_hits_total / (cache_hits_total + cache_inserts_total)`.

---

## Derived metrics

The following values are not stored as raw records but are computed from raw samples by
Solr Benchmark when generating the results report.

### `error_rate`

The fraction of operations that resulted in an error (Solr returned a 4xx/5xx response, or
the request timed out). Computed as:

```
error_rate = error_count / (error_count + success_count)
```

A value of `0.0` means all operations succeeded.
