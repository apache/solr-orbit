---
title: Concepts
parent: User Guide
nav_order: 3
---

# Concepts

## Workloads

A *workload* is the central concept in Apache Solr Orbit. It defines:

- The **data** to load (corpora — compressed NDJSON files)
- The **collections** to create and configure
- The **operations** to run (bulk indexing, search queries, commits, etc.)
- The **test procedures** that sequence those operations

Workloads are defined in a `workload.json` file. Pre-built workloads for Apache Solr are at [https://github.com/apache/solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads).

## Test Procedures

A *test procedure* is a named configuration within a workload that specifies a particular benchmark scenario. A workload can have multiple test procedures; you select one with `--test-procedure` when running the benchmark.

## Pipelines

A *pipeline* is a sequence of high-level phases that a benchmark run executes:

| Pipeline | Description |
|----------|-------------|
| `benchmark-only` | Run against an existing Solr cluster; no provisioning |
| `docker` | Start a Solr cluster via Docker, then benchmark, then tear down |
| `from-distribution` | Download and install Solr, benchmark, tear down |
| `from-sources` | Build Solr from source, install, benchmark, tear down |

## Collections

A *collection* is a logical grouping of documents distributed across shards. Collections are defined in the workload's `"collections"` array and are created before benchmarking begins.

## Replicas

Each shard in a collection can have multiple replicas. Apache Solr supports three replica types:

**Shard Leader** — The primary replica of a shard, responsible for accepting writes and coordinating replication.

**NRT Replica** — A near-real-time replica that receives updates directly from the shard leader and participates in leader election.

**TLOG Replica** — A transaction-log replica that receives updates via replication from the shard leader and buffers changes in a transaction log.

**Pull Replica** — A read-only replica that only receives index segments from the shard leader, not transaction log entries.

## Configsets

A *configset* is a named set of Solr configuration files (primarily `schema.xml` and `solrconfig.xml`) stored in ZooKeeper. Every collection references a configset. Supply a custom configset in your workload's `configset-path`. See the [Apache Solr Reference Guide](https://solr.apache.org/guide/solr/latest/configuration-guide/configsets.html) for more information.

## Operations

*Operations* are the individual benchmarking actions. Built-in operations include:

| Operation | Description |
|-----------|-------------|
| `bulk-index` | Index a batch of documents from a corpus |
| `search` | Execute a Solr query |
| `commit` | Issue a hard (or soft) commit to Solr |
| `optimize` | Issue an optimize (force-merge) command |
| `wait-for-merges` | Wait until all background merge operations finish |
| `paginated-search` | Cursor-paginated search using `cursorMark` |
| `create-collection` | Create a Solr collection |
| `delete-collection` | Delete a Solr collection |
| `raw-request` | Execute an arbitrary Solr Admin API request |

## Schedules

A *schedule* controls how an operation executes: number of iterations, target throughput (ops/s), warmup iterations, and parallel client count.

## Corpora

*Corpora* are the datasets used by workloads. Each corpus references one or more data files (gzip-compressed NDJSON). Apache Solr Orbit downloads corpora from the workload repository or a configured data URL.

## Facets

*Facets* are Solr's aggregation mechanism for computing counts, statistics, and groupings over search results.

---

## Metrics

At the end of each benchmark run, Apache Solr Orbit prints a summary table and saves it to disk. The table covers these metrics for every task in the challenge:

| Metric | Description |
|--------|-------------|
| Throughput | Operations completed per second |
| Service time | Round-trip time from client request to client receipt of response |
| Latency | Service time plus any queue waiting time (differs from service time only when `target-throughput` is set) |
| Error rate | Fraction of operations that returned an error |

### How Apache Solr Orbit defines service time and latency

These terms are often used interchangeably in the industry but have distinct meanings in Apache Solr Orbit:

| Metric | Common definition | Apache Solr Orbit definition |
|--------|------------------|----------------------------------|
| **Service time** | Server processing time, excluding network | Time from when the HTTP client sends the request to when it receives the full response — *including* network latency, load balancer overhead, and serialization/deserialization |
| **Latency** | Service time plus network latency | Service time *plus* any time the request spent waiting in a local queue before being dispatched — only non-zero when `target-throughput` is configured |

### Processing time

Processing time measures the overhead that Apache Solr Orbit adds during a request — for example, setting up the request context or dispatching to the client library. It is distinct from and excluded from service time measurements. This value is useful for understanding the benchmarking tool's own footprint.

### Service time

Service time is measured from the moment the HTTP client sends the request until the moment it receives the complete response. It includes:

- Network round-trip time
- Load balancer overhead (if any)
- Server processing time
- Serialization and deserialization on both ends

### Latency

Latency is service time plus any time the request spent waiting in a local queue *before* being sent. A queue only builds up when you set `target-throughput` on a task and the cluster cannot keep up with the requested rate. In that case, subsequent requests must wait for an earlier request to complete, adding queue time to the total latency.

When no `target-throughput` is set — or when the cluster can handle every request as fast as they arrive — latency equals service time.

### Throughput

Throughput is the rate at which Apache Solr Orbit *issues* requests, assuming that responses are returned instantaneously. It is not a measure of how many requests completed; it is a measure of how quickly requests were dispatched.

### The two benchmark modes

**Pure throughput mode** (`target-throughput` not set): Requests are issued as fast as possible — each client sends one request, waits for the response, then sends the next. Latency equals service time.

**Throughput-throttled mode** (`target-throughput` set): Requests are issued at a target rate (in ops/s). If you set a rate higher than the cluster can sustain, requests pile up in the local queue and latency grows. Set `target-throughput` to a value you know is achievable; see [Target throughput](optimizing-benchmarks/target-throughput.html) for practical guidance.
