---
title: Glossary
nav_order: 100
---

# Glossary

## Core concepts

**Workload**
A workload describes a benchmarking scenario: the data to load and the operations to run. A workload is defined by a `workload.json` file plus associated data, operation, and configset files. See [Understanding Workloads](user-guide/understanding-workloads/).

**Test Procedure**
A specific sequence of operations within a workload. A workload can define multiple test procedures (e.g., `append-no-conflicts`, `bulk-update`). Each test procedure specifies which operations to run and their parameters. Select a test procedure with `--test-procedure` when running the benchmark.

**Pipeline**
A sequence of phases that a benchmark run executes. Built-in pipelines:
- `benchmark-only` — run against an existing cluster
- `docker` — spin up a Solr cluster via Docker then benchmark
- `from-distribution` — download and install Solr then benchmark
- `from-sources` — build Solr from source then benchmark

**Schedule**
Defines how an operation is executed: number of iterations, target throughput (operations per second), warmup iterations, and parallel client count.

**Operation**
A single benchmarking action, such as `bulk-index`, `search`, `commit`, or `optimize`. Operations are referenced from schedules in a test procedure.

**Corpora**
The dataset used by a workload. Corpora are defined in the workload and reference data files (typically gzip-compressed NDJSON).

## Apache Solr concepts

**Collection**
The Solr equivalent of an OpenSearch index. A collection is a logical grouping of documents, distributed across one or more shards. In OSB terminology: *index*.

**Configset**
A named set of Solr configuration files (`schema.xml`, `solrconfig.xml`) stored in ZooKeeper. Collections reference a configset by name.

**Shard Leader**
The primary replica of a shard responsible for accepting writes and coordinating replication. In OSB terminology: *primary shard*.

**NRT Replica**
A near-real-time replica that receives updates directly from the shard leader and participates in leader election.

**TLOG Replica**
A transaction-log replica that receives updates via replication from the shard leader and buffers changes in a transaction log.

**Pull Replica**
A read-only replica that only receives index segments from the shard leader, not transaction log entries.

**Facets**
Solr's aggregation mechanism for computing counts, statistics, and groupings over search results. In OSB terminology: *aggregations*.

## Terminology mapping

| OpenSearch Benchmark Term | Apache Solr Benchmark Canonical Term |
|---------------------------|--------------------------------------|
| index | collection |
| indices | collections |
| create-index | create-collection |
| delete-index | delete-collection |
| primary shard | shard leader |
| aggregation / aggregations | facet / facets |
| mapping | schema |
