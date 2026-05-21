---
title: Cluster Config
nav_order: 27
has_children: true
---

# Cluster Config

The `--cluster-config` flag selects a preset JVM and garbage collector configuration applied to Solr nodes provisioned by Apache Solr Benchmark.

{: .note }
> `--cluster-config` is only valid with provisioning pipelines: `docker`, `from-distribution`, and `from-sources`. It is **not** applicable to the `benchmark-only` pipeline, which connects to an already-running cluster without modifying it.

## Usage

```bash
solr-benchmark run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --cluster-config 4gheap
```

## How it works

Cluster configs are predefined sets of environment variables injected into the Solr startup environment:

| Variable | Description |
|----------|-------------|
| `SOLR_HEAP` | JVM heap size (e.g., `4g`) |
| `GC_TUNE` | JVM garbage collector arguments |
| `SOLR_OPTS` | Additional JVM options |

Apache Solr Benchmark applies these variables when starting a provisioned Solr node so you can benchmark different JVM configurations without modifying the Solr installation.

## Available configs

See [Available Configs](available-configs.html) for the full list of built-in configurations.

## Why use cluster configs?

Comparing the same workload across different JVM configurations helps you:

- Find the optimal heap size for your workload
- Compare G1GC vs Parallel GC performance
- Identify GC-related latency spikes via telemetry
