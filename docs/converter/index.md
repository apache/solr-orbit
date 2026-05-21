---
title: Converter Tool
nav_order: 28
has_children: true
---

# Converter Tool

Apache Solr Benchmark includes a `convert-workload` command that translates OpenSearch Benchmark workloads into Apache Solr Benchmark format.

{: .note }
> The converter performs a **best-effort** translation. Most workloads require some manual review after conversion. Check the generated `CONVERTED.md` summary file for a list of items that may need attention.

## When to use the converter

Use `convert-workload` when you want to run an existing OpenSearch Benchmark workload against Apache Solr. Pre-built Solr workloads that need no conversion are available at [https://github.com/janhoy/solr-benchmark-workloads](https://github.com/janhoy/solr-benchmark-workloads).

## Quick example

```bash
solr-benchmark convert-workload \
  --workload-path /path/to/osb-workload \
  --output-path /path/to/solr-workload
```

The converted workload is ready to run with:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path /path/to/solr-workload
```
