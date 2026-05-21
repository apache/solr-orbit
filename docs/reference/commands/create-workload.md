---
title: create-workload
parent: Command Reference
grand_parent: Reference
nav_order: 35
---

# create-workload

Creates a new workload definition from data already indexed in a live Solr instance. Use this to capture a real dataset as a replayable workload corpus.

## Syntax

```bash
solr-benchmark create-workload --workload NAME --indices LIST --target-hosts HOSTS [OPTIONS]
```

## Options

| Option | Short | Required | Default | Description |
|--------|-------|----------|---------|-------------|
| `--workload` | `-w` | Yes | — | Name for the generated workload |
| `--indices` | `-i` | Yes | — | Comma-separated list of Solr collection (index) names to include |
| `--target-hosts` | `-t` | Yes | — | Comma-separated `host:port` pairs for the source Solr cluster |
| `--client-options` | `-c` | No | `timeout:60` | Comma-separated client options (e.g., `timeout:60`) |
| `--output-path` | | No | `./workloads` | Directory where the generated workload files will be written |
| `--custom-queries` | | No | — | Path to a JSON file containing custom queries to include in the workload (overrides the default `match_all` query) |
| `--number-of-docs` | | No | — | Per-index document count overrides in `index:count` format (e.g., `my_index:50000 other_index:10000`). The index name must also appear in `--indices` |
| `--sample-frequency` | | No | — | Per-index sampling frequency in `index:n` format. Every *n*th document is extracted. The index name must also appear in `--indices` |

## Examples

Create a workload from two collections on a local Solr instance:

```bash
solr-benchmark create-workload \
  --workload my_workload \
  --indices products,reviews \
  --target-hosts localhost:8983 \
  --output-path /workloads/my_workload
```

Create a workload extracting a fixed number of documents per collection:

```bash
solr-benchmark create-workload \
  --workload sales_workload \
  --indices orders,customers \
  --target-hosts solr-prod:8983 \
  --number-of-docs orders:100000 customers:50000 \
  --output-path /workloads/sales
```

## See also

- [Working with Workloads](../../user-guide/working-with-workloads/index.html)
- [generate-data](generate-data.html)
