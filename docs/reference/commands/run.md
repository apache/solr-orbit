---
title: run
parent: Command Reference
grand_parent: Reference
nav_order: 90
---

# run

Runs a benchmark workload.

## Syntax

```bash
solr-orbit run [OPTIONS]
```

## Workload selection

| Option | Description |
|--------|-------------|
| `--workload` | Named workload from the workloads repository |
| `--workload-path` | Path to a local workload directory |
| `--workload-repository` | Git URL for the workloads repository (default: `"default"`, resolved from `benchmark.ini`) |
| `--workload-revision` | Git revision (branch, tag, or commit) of the workloads repository; optional, uses the repository's default branch if omitted |
| `--workload-params` | Override workload Jinja2 parameters (comma-separated `key:value` pairs) |
| `--test-procedure` | Test procedure to run (default: the workload's default test procedure) |
| `--include-tasks` | Comma-separated list of task names to run; all other tasks are skipped |
| `--exclude-tasks` | Comma-separated list of task names to skip |
| `--enable-assertions` | Enable task-level assertions defined in the workload |

## Cluster and pipeline

| Option | Description |
|--------|-------------|
| `--pipeline` | Pipeline to use: `benchmark-only`, `docker`, `from-distribution`, `from-sources`. If omitted, the pipeline is selected automatically (see below) |
| `--target-hosts` | Comma-separated list of Solr `host:port` targets |
| `--distribution-version` | Solr version (e.g., `9.10.1`) for `docker`/`from-distribution` pipelines |
| `--cluster-config` | Cluster configuration preset for `docker`/`from-distribution`/`from-sources` pipelines |

### Pipeline auto-selection

If `--pipeline` is omitted, Solr Orbit selects a pipeline automatically:

- `from-distribution` — when `--distribution-version` is specified
- `benchmark-only` — otherwise (connects to an already-running cluster)

## Distributed load generation

| Option | Description |
|--------|-------------|
| `--worker-ips` | Comma-separated IP addresses of worker coordinator machines for distributed load generation (default: `localhost`) |

## Multiple-iteration aggregation

| Option | Default | Description |
|--------|---------|-------------|
| `--test-iterations` | `1` | Number of times to repeat the workload |
| `--aggregate` | `true` | Aggregate results from all iterations |
| `--sleep-timer` | `5` | Seconds to wait between iterations |
| `--cancel-on-error` | `false` | Abort remaining iterations if any iteration fails |

## Telemetry

| Option | Description |
|--------|-------------|
| `--telemetry` | Comma-separated list of optional telemetry devices to enable (see [Telemetry reference](../telemetry.html)) |
| `--telemetry-params` | Key-value parameters for telemetry devices |

## Result output

| Option | Description |
|--------|-------------|
| `--test-run-id` | Custom unique ID for this run (auto-generated if omitted); used with `compare` |
| `--user-tag` | A single `key:value` metadata pair attached to every metric record in this run (e.g., `intention:baseline`) |
| `--results-format` | Output format: `markdown` (default) or `csv` |
| `--results-numbers-align` | Column alignment in the summary table: `right` (default), `left`, `center`, or `decimal` |
| `--results-file` | Write the summary table to a file in addition to the default location |
| `--show-in-results` | Which values to include in output: `available` (default), `all-percentiles`, or `all` |
| `--visualize` | Generate an interactive HTML visualization after the run |
| `--visualize-output-path` | Path to write the HTML visualization file |

## General

| Option | Description |
|--------|-------------|
| `--test-mode` | Run a shortened version of the workload (≤1,000 docs) for quick validation |
| `--on-error` | Error handling: `continue` (default), `abort` |
| `--client-options` / `-c` | Comma-separated client options (default: `timeout:60`) |
| `--kill-running-processes` / `-k` | Kill other running `solr-orbit` processes before starting |
| `--preserve-install` | Keep the Solr installation after the run (provisioned pipelines only) |

The `--quiet` flag is accepted by all subcommands; see [Command Flags](command-flags.html#global-flags).

## Workload parameter overrides

Workload files can contain Jinja2 template variables, for example:

```json
{
  "bulk-size": {{ bulk_size | default(500) }},
  "clients": {{ clients | default(4) }}
}
```

Override these at run time with `--workload-params` as a comma-separated list of `key:value` pairs:

```bash
solr-orbit run --workload-params "bulk_size:1000,clients:8" ...
```

Related parameter flags:

| Flag | Purpose |
|------|---------|
| `--workload-params` | Jinja2 variable overrides for the workload |
| `--cluster-config-params` | Variable overrides for the cluster configuration |
| `--plugin-params` | Parameters passed to all configured plugins |
| `--telemetry-params` | Parameters passed to telemetry devices |

## Examples

```bash
# Benchmark an existing cluster
solr-orbit run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --test-mode

# Docker pipeline with Solr 9.10.1
solr-orbit run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis

# Custom workload with parameter overrides
solr-orbit run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path /path/to/my-workload \
  --workload-params "bulk_size:1000,clients:8"

# With optional telemetry devices
solr-orbit run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --telemetry shard-stats,cluster-environment-info

# Run 3 iterations and aggregate results
solr-orbit run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --test-iterations 3 \
  --sleep-timer 10
```

## See also

- [Pipelines overview](../../user-guide/concepts.html#pipelines)
- [Cluster Config](../../cluster-config/)
- [Command Flags](command-flags.html)
