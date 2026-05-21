---
title: Apache Solr Benchmark
nav_order: 1
---

# Apache Solr Benchmark

Apache Solr Benchmark is a performance benchmarking tool for [Apache Solr](https://solr.apache.org) clusters, derived from [OpenSearch Benchmark](https://github.com/opensearch-project/opensearch-benchmark).

Use Apache Solr Benchmark to measure the performance of your Apache Solr clusters across a variety of workloads — from simple keyword queries to complex faceted search and aggregations.

## Getting started

- [Quickstart](quickstart.html) — install the tool and run your first benchmark in minutes
- [User Guide](user-guide/) — deeper guides on workloads, pipelines, and results
- [Reference](reference/) — complete CLI and workload format reference

## Key features

- **Multiple pipelines** — benchmark an existing cluster (`benchmark-only`), or let Apache Solr Benchmark provision one via Docker (`docker`), direct installation (`from-distribution`), or source build (`from-sources`)
- **Flexible workloads** — load pre-built workloads from [janhoy/solr-benchmark-workloads](https://github.com/janhoy/solr-benchmark-workloads) or create your own
- **Workload converter** — convert existing OpenSearch Benchmark workloads to Solr format with the `convert-workload` command
- **Telemetry** — collect JVM, node, and collection-level metrics from Solr during a run
- **Result storage** — results saved as JSON and CSV to `~/.solr-benchmark/benchmarks/test-runs/`

## Source code

Apache Solr Benchmark is hosted at [https://github.com/janhoy/solr-benchmark](https://github.com/janhoy/solr-benchmark).
