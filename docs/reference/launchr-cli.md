---
title: launchr Command Reference
parent: Reference
nav_order: 52
---

# launchr Command Reference

`launchr` runs a matrix of Solr Orbit benchmarks, provisioning and destroying infrastructure around each one and storing every result. For the concepts behind it, see [Continuous Benchmarking](../user-guide/continuous-benchmarking/).

```bash
launchr [-v | -q] <command> [options]
```

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help and exit. |
| `--version` | Print the version and exit. |
| `-v`, `--verbose` | Log at DEBUG level. AWS SDK logging is deliberately held at INFO, because its debug output contains credentials. |
| `-q`, `--quiet` | Log warnings and errors only. |

Every subcommand except `version` accepts `-c FILE`, `--config FILE` to name a configuration file. Without it, `launchr` reads `launchr.yaml` from the current directory, falling back to built-in defaults.

---

## run

Expands the configuration into matrix cells and executes them.

```bash
launchr run [--config FILE] [options]
```

### Options

| Option | Description |
|--------|-------------|
| `--versions VERSIONS` | Comma-separated Solr versions, e.g. `9.7.0,9.11.0`. Overrides `solr_versions`. |
| `--workloads WORKLOADS` | Comma-separated workload names. Overrides `workloads`. |
| `--provisioning PROFILES` | Comma-separated provisioning profile names. Overrides `defaults.provisioning`. |
| `--cluster-config CONFIGS` | Comma-separated cluster config names. Overrides `defaults.cluster_config`. |
| `--storage BACKEND` | Storage backend: `local` or `s3`. Inferred from an `s3://` storage path. |
| `--storage-path PATH` | Storage root — a directory, or `s3://bucket/prefix`. |
| `--registry REGISTRY` | Docker repository for released versions. |
| `--solr-port PORT` | Port for Solr to listen on, overriding every provisioning profile. Useful when the default is taken. |
| `--test-mode` | Truncate every corpus to 1000 documents. Minutes instead of hours; for smoke tests, never for publishable results. |
| `--branch BRANCH` | Override the inferred git branch for SNAPSHOT versions. |
| `--version-timestamp ISO8601` | Override the time-axis position for every version in this run. |
| `--dry-run` | Print the plan and the exact `solr-orbit` command lines; run nothing. |

### Examples

```bash
# See what would run, without running it. Offline and instant.
launchr run --versions 9.9.0,9.10.1,9.11.0 --workloads nyc_taxis --dry-run

# A fast smoke run against local Docker.
launchr run --versions 9.11.0 --workloads nyc_taxis --test-mode

# A full matrix from a configuration file.
launchr run --config examples/launchr-ec2.yaml
```

### See also

[Configuring launchr](../user-guide/continuous-benchmarking/configuring-launchr.html), [A Local Trial Run](../user-guide/continuous-benchmarking/a-local-trial-run.html)

---

## teardown

Reclaims infrastructure a run left behind. A session normally destroys its own resources, but a process killed outright never gets the chance.

```bash
launchr teardown [--config FILE] [options]
```

### Options

| Option | Description |
|--------|-------------|
| `--region REGION` | Region to sweep. Repeatable. Regions named by the ledger are swept as well. |
| `--aws-profile PROFILE` | AWS credentials profile to sweep with. Taken from the configured provisioning profiles when omitted. |
| `--stack STACK_ID` | Reclaim one stack only. |
| `--older-than DURATION` | Only touch stacks older than this, e.g. `30m`, `6h`, `2d`. |
| `--storage BACKEND`, `--storage-path PATH` | Where to read the infrastructure ledger. |
| `--dry-run` | Report what would be reclaimed; destroy nothing. |

### Examples

```bash
launchr teardown --dry-run                       # always look first
launchr teardown --older-than 6h                 # safe alongside a running benchmark
launchr teardown --stack session-a1b2c3-4d5e     # one stack
```

{: .warning }
Without `--older-than`, a run that is currently in progress looks exactly like a leak. In a scheduled sweep the flag is mandatory, and the window must exceed your longest run.

### See also

[Provider: AWS](../user-guide/continuous-benchmarking/provider-aws.html#teardown), [Scheduling Nightly Runs](../user-guide/continuous-benchmarking/scheduling-nightly-runs.html)

---

## validate-config

Resolves the configuration and prints every setting with the source it came from — a built-in default, the configuration file, an environment variable or a command-line flag.

```bash
launchr validate-config [--config FILE]
```

Validation is thorough: unknown keys, profiles naming strategies that do not exist, cluster configs with invalid garbage collectors, and anything resembling a credential all fail here. It runs offline and in seconds, which makes it the right pre-flight step for a scheduled job.

```bash
launchr validate-config --config /etc/solr-orbit/launchr.yaml
```

---

## list

Lists what the configuration defines, and what plugins are available.

```bash
launchr list [all | profiles | cluster-configs | plugins] [--config FILE]
```

```bash
launchr list plugins          # registered provisioning, install and storage backends
launchr list profiles         # provisioning profiles, with the defaults marked
launchr list cluster-configs  # cluster configs, and what each one actually applies
```

---

## version

```bash
launchr version
```
