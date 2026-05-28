---
title: FAQ
nav_order: 101
---

# Frequently Asked Questions

**What is Apache Solr Orbit?**
Apache Solr Orbit is a macro-benchmarking framework for [Apache Solr](https://solr.apache.org) clusters. It is a fork of OpenSearch Benchmark, adapted to work with Solr instead of OpenSearch.

**What Solr versions are supported?**
Apache Solr Orbit supports Solr 9.x and Solr 10.x. Some metrics collection endpoints differ between versions and are detected automatically at runtime.

**Where can I find pre-built workloads?**
Pre-built workloads for Apache Solr Orbit are available at [https://github.com/apache/solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads).

**How do I convert an OpenSearch Benchmark workload?**
Use the `convert-workload` command:

```bash
solr-orbit convert-workload \
  --workload-path /path/to/osb-workload \
  --output-path /path/to/solr-workload
```

See [Converter Tool](converter/) for details on what gets converted automatically.

**Can I benchmark a multi-node Solr cluster?**
Yes. Pass multiple hosts to `--target-hosts`, separated by commas:

```bash
solr-orbit run --target-hosts node1:8983,node2:8983,node3:8983 ...
```

**What pipelines are available?**
See [Pipelines](user-guide/concepts.html#pipelines) in the Concepts page.

**How do I run in test mode?**
Pass `--test-mode` to limit the workload to a small subset of documents (at most 1,000) for quick validation:

```bash
solr-orbit run --test-mode ...
```

**Where are results stored?**
Results from individual benchmark runs are stored in `~/.solr-orbit/benchmarks/test-runs/<run-id>/`. Aggregated results (from the `aggregate` command or multi-iteration runs) go to `~/.solr-orbit/benchmarks/aggregated_results/<id>/`.

**Does Apache Solr Orbit support distributed (multi-machine) benchmarking?**
Yes. Use the daemon mode (`solr-orbitd`) on worker nodes and the coordinator on the driver node. See [Working with Workloads](user-guide/working-with-workloads/) for details.

**What is `--cluster-config` for?**
The `--cluster-config` flag selects a preset JVM/GC configuration for provisioned Solr nodes (used with `docker`, `from-distribution`, and `from-sources` pipelines). It is not applicable to the `benchmark-only` pipeline. See [Cluster Config](cluster-config/) for available presets.
