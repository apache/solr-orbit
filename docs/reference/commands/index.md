---
title: Command Reference
parent: Reference
nav_order: 50
has_children: true
---

# Command Reference

Reference documentation for all `solr-benchmark` subcommands and their flags.

| Command | Description |
|---------|-------------|
| [aggregate](aggregate.html) | Combine results from multiple benchmark runs |
| [compare](compare.html) | Compare two benchmark runs side by side |
| [convert-workload](../../converter/) | Convert an OpenSearch Benchmark workload to Solr format |
| [create-workload](create-workload.html) | Create a workload definition from an existing Solr collection |
| [download](download.html) | Download a Solr distribution without running a benchmark |
| [generate-data](generate-data.html) | Generate synthetic data from an index schema or custom module |
| [info](info.html) | Show detailed information about a workload |
| [install](install.html) | Install a Solr node locally (for manual lifecycle control) |
| [list](list.html) | List available workloads, telemetry, pipelines, or past runs |
| [run](run.html) | Run a benchmark workload |
| [start](start.html) | Start a locally installed Solr node |
| [stop](stop.html) | Stop a locally installed Solr node |
| [visualize](visualize.html) | Generate an HTML visualization for a completed run |

## Daemon

The `solr-benchmarkd` binary manages worker daemon processes for distributed load generation. See [solr-benchmarkd](benchmarkd.html) for the full reference.

## Common options

The following flags are accepted by every `solr-benchmark` subcommand.

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Display help text for the current command and exit |
| `--offline` | — | Run without network access; disables workload repository fetching and any update checks |
