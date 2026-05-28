---
title: Apache Solr Orbit
nav_order: 1
---

# Apache Solr Orbit

Apache Solr Orbit is a performance benchmarking tool for [Apache Solr](https://solr.apache.org) clusters.

Use Apache Solr Orbit to measure the performance of your Apache Solr clusters across a variety of workloads — from simple keyword queries to complex faceted search and aggregations.

## Getting started

- [Quickstart](quickstart.html) — install the tool and run your first benchmark in minutes
- [User Guide](user-guide/) — deeper guides on workloads, pipelines, and results
- [Reference](reference/) — complete CLI and workload format reference

## Key features

- **Multiple pipelines** — benchmark an existing cluster (`benchmark-only`), or let Apache Solr Orbit provision one via Docker (`docker`), direct installation (`from-distribution`), or source build (`from-sources`)
- **Flexible workloads** — load pre-built workloads from [apache/solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads) or create your own
- **Workload converter** — convert existing OpenSearch Benchmark workloads to Solr format with the `convert-workload` command
- **Telemetry** — collect JVM, node, and collection-level metrics from Solr during a run
- **Result storage** — results saved as JSON and CSV to `~/.solr-orbit/benchmarks/test-runs/`

## Source code

Apache Solr Orbit is hosted at [https://github.com/apache/solr-orbit](https://github.com/apache/solr-orbit).
