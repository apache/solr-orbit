---
title: Choosing a Workload
parent: Understanding Workloads
grand_parent: User Guide
nav_order: 12
---

# Choosing a Workload

## Overview

The [solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads) repository offers pre-built workloads for performance testing Apache Solr clusters. Selecting a workload that mirrors your cluster's actual use cases streamlines the benchmarking process and reduces custom development overhead.

A practical example: a rideshare company can leverage the `nyc_taxis` workload instead of building a proprietary benchmark, because the taxi trip dataset closely resembles operational geospatial and time-series data.

{: .note }
> The Solr workload library is still growing. Only a subset of the original OpenSearch Benchmark workloads have been converted to Solr format so far. If a workload you need is not yet available, you can [convert an existing OpenSearch Benchmark workload](../../converter/) or [create a custom workload](../working-with-workloads/creating-custom-workloads.html).

## Selection criteria

When evaluating workloads, examine:

- **Cluster scale**: small clusters (1–10 nodes) suit development; medium clusters (11–50 nodes) approximate production environments.
- **Data compatibility**: review the example documents and the collection schema in the workload to compare field types with your actual data.
- **Query patterns**: inspect the operations defined in the workload to verify it exercises your typical query types (term queries, range queries, facets, etc.).

## Available workloads

### nyc_taxis

The `nyc_taxis` workload benchmarks typical search and analytics scenarios using ride data from yellow taxis in New York City in 2015. It evaluates:

- Range and term queries
- Geo-distance queries
- Date-range queries
- Faceted aggregations (histogram and date histogram)

The dataset contains around 165 million documents and is suitable for small to medium clusters. A `--test-mode` run uses a small document subset and completes in minutes.

**Example run:**

```bash
solr-orbit run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --test-mode
```

### geonames

The `geonames` workload benchmarks search and geospatial scenarios using geographic place-name data from the [GeoNames](https://www.geonames.org/) database. It evaluates:

- Full-text name search queries
- Geo-distance queries
- Faceted aggregations by country code and feature classification

The dataset contains around 11.4 million documents and is suitable for small clusters. A `--test-mode` run uses a small document subset and completes in minutes.

**Test procedures:**

| Procedure | Description |
|-----------|-------------|
| `append-no-conflicts` (default) | Indexes the full corpus, then runs search and faceting queries |
| `append-no-conflicts-index-only` | Indexing only, without query execution |

**Example run:**

```bash
solr-orbit run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload geonames \
  --test-mode
```

## Custom workloads

For specialized requirements, see:

- [Creating Custom Workloads](../working-with-workloads/creating-custom-workloads.html) — build a workload from scratch for your own data
- [Converter Tool](../../converter/) — convert an existing OpenSearch Benchmark workload to Solr format
