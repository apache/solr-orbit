---
title: Command Flags
parent: Command Reference
grand_parent: Reference
nav_order: 150
---

# Command Flags

Complete reference of all `solr-orbit` command-line flags.

## Global flags

Accepted by all subcommands.

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Display help text for the current command and exit |
| `--offline` | — | Run without network access; disables workload repository fetching and update checks |
| `--version` | `-v` | Show version and exit |
| `--quiet` | — | Suppress console output (except errors) |

## run flags

### Workload selection

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--workload` | string | — | Named workload (fetched from workloads repository) |
| `--workload-path` | path | — | Local workload directory path |
| `--workload-repository` | string | `"default"` | Git URL for the workloads repository (the string `"default"` resolves to the URL configured in `benchmark.ini`) |
| `--workload-revision` | string | — | Git revision (branch, tag, or commit) of the workloads repository. If omitted, the branch is selected automatically based on `--distribution-version` (e.g., `10.0.0` → branch `10`); falls back to `main` if no matching branch exists. |
| `--workload-params` | string | — | Comma-separated `key:value` Jinja2 parameter overrides |
| `--test-procedure` | string | workload default | Test procedure name to run |
| `--include-tasks` | string | — | Comma-separated task names to run; all other tasks are skipped |
| `--exclude-tasks` | string | — | Comma-separated task names to skip |
| `--enable-assertions` | flag | off | Enable task-level assertions defined in the workload |

### Cluster and pipeline

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--pipeline` | string | (dynamic) | Pipeline to use: `benchmark-only`, `docker`, `from-distribution`, or `from-sources`. Defaults to `benchmark-only` when no provisioning flags are given |
| `--target-hosts` | string | — | Comma-separated `host:port` list |
| `--distribution-version` | string | — | Solr version for provisioning pipelines |
| `--cluster-config` | string | `defaults` | Cluster config preset for provisioning pipelines |

### Distributed load generation

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--worker-ips` | string | `localhost` | Comma-separated IP addresses of worker coordinator machines |

### Multiple-iteration aggregation

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--test-iterations` | integer | `1` | Number of times to repeat the workload |
| `--aggregate` | boolean | `true` | Aggregate results from all iterations |
| `--sleep-timer` | integer | `5` | Seconds to wait between iterations |
| `--cancel-on-error` | boolean | `false` | Abort remaining iterations on first error |

### Telemetry

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--telemetry` | string | — | Comma-separated telemetry device names |
| `--telemetry-params` | string | — | Telemetry device parameters |

### Result output

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--test-run-id` | string | auto-generated | Custom ID for this run; used with `compare` and `aggregate` |
| `--user-tag` | string | — | A single `key:value` metadata pair attached to every metric record in this run (e.g., `intention:baseline`) |
| `--results-format` | string | `markdown` | Summary table format: `markdown` or `csv` |
| `--results-numbers-align` | string | `right` | Column alignment: `right`, `left`, `center`, or `decimal` |
| `--results-file` | path | — | Write the summary table to this file |
| `--show-in-results` | string | `available` | Values to include: `available`, `all-percentiles`, or `all` |
| `--visualize` | flag | off | Generate an interactive HTML visualization after the run |
| `--visualize-output-path` | path | — | Path to write the HTML visualization file (defaults to the test run directory) |

### General

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--test-mode` | flag | off | Run with ≤1,000 documents for quick validation |
| `--on-error` | string | `continue` | Error strategy: `continue` or `abort` |
| `--client-options` | string | `timeout:60` | Comma-separated client options passed to the Solr client (short: `-c`) |
| `--kill-running-processes` | flag | off | Kill other running `solr-orbit` processes before starting (short: `-k`) |
| `--preserve-install` | flag | off | Keep the Solr installation after the run (provisioned pipelines only) |

### Provisioning

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--revision` | string | — | Source code revision for the `from-sources` pipeline |
| `--runtime-jdk` | integer | — | Major JDK version to use for provisioned Solr nodes (e.g., `21`) |
| `--solr-modules` | string | — | Comma-separated Solr modules to enable (e.g., `extraction`) |
| `--plugin-params` | string | — | Comma-separated `key:value` pairs passed to all configured plugins |
| `--cluster-config-params` | string | — | Comma-separated `key:value` variable overrides for the cluster config |
| `--cluster-config-repository` | string | — | Git URL for a custom cluster-config repository |
| `--cluster-config-revision` | string | — | Git revision of the cluster-config repository |
| `--distribution-repository` | string | `release` | Repository to download Solr from |

### Advanced load generation

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--grpc-target-hosts` | string | `localhost:9400` | gRPC endpoint(s) for worker coordinator communication |
| `--enable-worker-coordinator-profiling` | flag | off | Profile the worker coordinator process |
| `--latency-percentiles` | string | — | Comma-separated additional percentiles to report for latency (e.g., `50,90,99,99.9`) |
| `--throughput-percentiles` | string | — | Comma-separated additional percentiles to report for throughput |

### Load testing

These flags enable automated load-ramp and redline testing to find a cluster's performance limits.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--load-test-qps` | integer | — | Run a load test that ramps up to this target QPS value |
| `--redline-test` | integer? | `0` (off) | Run a redline test to find the maximum sustainable throughput. Use as a bare flag (`--redline-test`, implicitly 1000 QPS) or with an explicit QPS target (e.g. `--redline-test 5000`) |
| `--redline-scale-step` | integer | — | Number of clients to add per scale step |
| `--redline-scaledown-percentage` | float | — | Percentage of clients to remove when the error threshold is exceeded |
| `--redline-post-scaledown-sleep` | integer | — | Seconds to wait after a scale-down event before resuming |
| `--redline-max-clients` | integer | — | Maximum number of concurrent clients during a redline test |
| `--redline-max-cpu-usage` | float | — | CPU usage percentage at which to begin scaling back |
| `--redline-cpu-window-seconds` | integer | `30` | Window in seconds over which average CPU load is measured |
| `--redline-cpu-check-interval` | integer | `30` | Seconds between CPU usage checks |

## list flags

| Flag | Description |
|------|-------------|
| `--workload` | Workload name (used with `list workloads` to filter by workload) |
| `--workload-path` | Local workload directory |
| `--workload-repository` | Git URL for the workloads repository |
| `--workload-revision` | Git revision of the workloads repository |
| `--limit` | Maximum number of test-run results to show (default: `10`; applies to `list test-runs`) |

## info flags

| Flag | Description |
|------|-------------|
| `--workload` | Workload name |
| `--workload-path` | Local workload directory |
| `--workload-repository` | Git URL for the workloads repository |
| `--workload-revision` | Git revision of the workloads repository |
| `--workload-params` | Comma-separated `key:value` Jinja2 parameter overrides |
| `--test-procedure` | Specific test procedure to describe |
| `--include-tasks` | Comma-separated task names to display |
| `--exclude-tasks` | Comma-separated task names to hide |

## compare flags

| Flag | Description |
|------|-------------|
| `--baseline` | Test run ID of the baseline run (see `list test-runs`) |
| `--contender` | Test run ID of the contender run (see `list test-runs`) |
| `--results-format` | Output format: `markdown` (default) or `csv` |
| `--results-numbers-align` | Column alignment: `right` (default), `left`, `center`, or `decimal` |
| `--results-file` | Write the comparison table to a file |
| `--show-in-results` | Values to include: `available` (default), `all-percentiles`, or `all` |
| `--percentiles` | Comma-separated list of percentiles to include in the comparison |

## aggregate flags

| Flag | Description |
|------|-------------|
| `--test-runs` | Comma-separated test run IDs to aggregate |
| `--test-runs-id` | Custom ID for the aggregated result |
| `--results-file` | Path to write the aggregated results JSON |
| `--workload-repository` | Git URL for the workloads repository |

## download flags

Solr is pure Java — no OS- or architecture-specific variants exist.

| Flag | Description |
|------|-------------|
| `--distribution-version` | Solr version to download (e.g., `9.10.1`) |
| `--distribution-repository` | Source repository (default: `release`) |
| `--cluster-config` | Cluster configuration preset to apply |
| `--cluster-config-params` | Comma-separated `key:value` variable overrides for the cluster configuration |
| `--cluster-config-path` | Local path to a cluster configuration directory |
| `--cluster-config-repository` | Git URL for a cluster configuration repository |
| `--cluster-config-revision` | Git revision of the cluster-config repository to use |

## convert-workload flags

| Flag | Description |
|------|-------------|
| `--workload-path` | Path to the source (OpenSearch Benchmark format) workload directory |
| `--output-path` | Destination directory for the converted workload |
| `--force` | Overwrite the output directory if it already exists |
