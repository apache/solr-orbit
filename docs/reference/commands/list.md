---
title: list
parent: Command Reference
grand_parent: Reference
nav_order: 80
---

# list

Lists available resources such as workloads and telemetry devices.

## Syntax

```bash
solr-orbit list [RESOURCE] [OPTIONS]
```

## Resources

| Resource | Description |
|----------|-------------|
| `workloads` | List workloads from the configured workloads repository |
| `telemetry` | List available telemetry device names |
| `pipelines` | List available pipeline names |
| `test-runs` | List past benchmark runs with their IDs, timestamps, and metadata |
| `aggregated-results` | List past aggregated results |
| `cluster-configs` | List available cluster configuration presets |

## Options

| Option | Description |
|--------|-------------|
| `--workload` | Workload name (used with `list workloads`) |
| `--workload-path` | Path to a local workload directory |
| `--workload-repository` | Git URL for the workloads repository |
| `--workload-revision` | Git revision of the workloads repository |
| `--limit` | Maximum number of entries to show (default: `10`; applies to `list test-runs`) |

## Examples

```bash
# List available workloads
solr-orbit list workloads

# List available telemetry devices
solr-orbit list telemetry

# List available pipelines
solr-orbit list pipelines

# List available cluster config presets
solr-orbit list cluster-configs

# List recent test runs (shows IDs for use with compare and aggregate)
solr-orbit list test-runs

# List the 20 most recent test runs
solr-orbit list test-runs --limit 20

# List aggregated results
solr-orbit list aggregated-results
```

To list the test procedures available in a workload, use `solr-orbit info`:

```bash
solr-orbit info --workload nyc_taxis
```

The `test-runs` output includes the test run ID, timestamp, workload name, test procedure, pipeline, and any user tags. Use the ID with `solr-orbit compare` to compare two runs.
