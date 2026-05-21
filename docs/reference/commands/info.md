---
title: info
parent: Command Reference
grand_parent: Reference
nav_order: 70
---

# info

Shows detailed information about a workload.

## Syntax

```bash
solr-benchmark info --workload WORKLOAD [OPTIONS]
```

## Options

| Option | Description |
|--------|-------------|
| `--workload` | Workload name (fetched from the workloads repository) |
| `--workload-path` | Path to a local workload directory |
| `--workload-repository` | Git URL for the workloads repository |
| `--workload-revision` | Git revision of the workloads repository |
| `--workload-params` | Comma-separated `key:value` Jinja2 parameter overrides |
| `--test-procedure` | Show details for a specific test procedure |
| `--include-tasks` | Comma-separated list of task names to display (others are hidden) |
| `--exclude-tasks` | Comma-separated list of task names to hide from the output |

## Examples

```bash
# Show information about a named workload
solr-benchmark info --workload nyc_taxis

# Show information about a local workload
solr-benchmark info --workload-path /path/to/my-workload

# Show details for a specific test procedure
solr-benchmark info --workload nyc_taxis --test-procedure append-no-conflicts
```

The output includes:
- Workload description
- Available test procedures and their descriptions
- Corpora names and document counts
- Default parameters and their values
