---
title: Configuring launchr
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 30
---

# Configuring launchr

`launchr` reads `launchr.yaml` from the current directory, or the file named by `--config`. With no file at all it falls back to built-in defaults that run one Solr container locally — enough for [a trial run](a-local-trial-run.html), and not enough for anything else.

The repository ships two examples: `launchr.yaml` at the root works on a fresh checkout, and `examples/launchr-ec2.yaml` describes a cloud matrix and must be edited before use.

## Precedence

Four layers, most specific first:

```
command-line flag  >  environment variable  >  launchr.yaml  >  built-in default
```

Only settings that have a command-line flag also have an environment variable:

| Setting | Variable |
|---------|----------|
| `solr_versions` | `SOLR_VERSIONS` |
| `workloads` | `LAUNCHR_WORKLOADS` |
| `defaults.provisioning` | `LAUNCHR_PROVISIONING` |
| `defaults.cluster_config` | `LAUNCHR_CLUSTER_CONFIG` |
| `storage.backend` | `LAUNCHR_STORAGE_BACKEND` |
| `storage.path` | `LAUNCHR_STORAGE_PATH` |
| `registry` | `LAUNCHR_REGISTRY` |

`launchr validate-config` resolves everything and shows where each value came from:

```
storage.backend = 's3'                          <- launchr.yaml
storage.path = 's3://solr-orbit/public/v1'      <- launchr.yaml
solr_versions = ['9.11.0']                      <- CLI flag
benchmark.client_timeout = 7200                 <- built-in default
```

In a scheduled job, run it as a pre-flight step. A bad configuration then fails in seconds rather than after an hour of provisioning.

## Versions and images

```yaml
solr_versions: ["9.7.0", "9.11.0", "10.0.0", "11.0.0-SNAPSHOT"]

registry: "docker.io/library/solr"
nightly_registry: "docker.io/apache/solr-nightly"
```

A version containing `SNAPSHOT` is pulled from `nightly_registry`, everything else from `registry`. Snapshot tags track their branch, so `11.0.0-SNAPSHOT` means "whatever main is today" and needs bumping when the branch version does.

## Storage

```yaml
storage:
  backend: s3                              # local | s3
  path: "s3://my-bucket/benchmarks/v1"
  options:
    region: eu-north-1
    profile: solr-orbit                    # a named AWS profile, not a credential
```

An `s3://` path selects the S3 backend on its own; stating a `backend` that contradicts the path is an error rather than a silent preference. With `backend: local`, `path` defaults to `~/.solr-orbit/benchmark-results` and honours `BENCHMARK_HOME`.

## Provisioning profiles

A profile describes what infrastructure to create and how to put Solr on it.

```yaml
provisioning_profiles:
  local-docker:
    provisioning: local                    # creates nothing; uses this machine
    install_method: docker                 # one container, embedded ZooKeeper
    nodes: 1
    port: 8983
```

| `provisioning` | What it does |
|----------------|--------------|
| `local` | Uses this machine. Creates and destroys nothing. |
| `preconfigured` | Benchmarks a cluster you started yourself, named by `solr_url`. |
| `ec2` | Creates EC2 instances and destroys them afterwards — see [Provider: AWS](provider-aws.html). |

| `install_method` | What it does |
|------------------|--------------|
| `docker` | One container on this machine, with embedded ZooKeeper. |
| `docker-ssh` | One container per remote node, with a standalone ZooKeeper. |
| `none` | Deploys nothing; the cluster already exists. |

Profiles that differ only in `nodes` share one provisioning group, created at the largest node count.

## Cluster configs

```yaml
cluster_configs:
  2shard-1replica:
    heap: "8g"
    gc: "G1GC"                             # G1GC | ParallelGC | ZGC | SerialGC | Shenandoah
    solr_opts: ""
    shards: 2
    replicas: 1
```

`heap`, `gc` and `solr_opts` become environment on the Solr process; `shards` and `replicas` become the `num_shards` and `replication_factor` workload parameters that the workload's create-collection operation reads.

{: .important }
This block is not Solr Orbit's [`--cluster-config`](../../cluster-config/). See [How Continuous Benchmarking Works](overview.html#cluster-configuration) for why the preset catalogue does not apply in this mode.

## Defaults and workloads

```yaml
defaults:
  provisioning: ["ec2-2node"]
  cluster_config: ["2shard-1replica"]

workloads:
  - name: nyc_taxis
    # test_procedures: ["default"]         # omitted -> the workload's own default
    # workload_params: {use_zstd: true}
```

Listing more than one profile or cluster config multiplies the matrix — which is how you compare two shard counts or two heap sizes in a single session, on the same hardware.

## Benchmark settings

```yaml
benchmark:
  iterations: 1
  aggregate: false
  test_mode: false
  workload_repository: default
  client_timeout: 7200
  user_tags:
    intention: nightly
```

`client_timeout` is the socket read timeout for the driver's HTTP calls to Solr, in seconds. It must exceed the longest *single* operation a workload performs, which is normally `optimize`: a force-merge of a large index is one HTTP request that runs for minutes.

`use_zstd: true` is applied to every workload automatically on a full-corpus run, because the compressed corpora decompress far faster in zstd than bz2. It is withheld under `--test-mode`, where only the bz2 variant of the truncated corpus is published.

## Solr Orbit's own configuration

```yaml
orbit_config:
  workloads:
    default.url: https://github.com/my-org/my-solr-workloads
```

On a remote driver, `launchr` writes Solr Orbit's `benchmark.ini` before the first run, merging these overrides on top of Solr Orbit's bundled defaults. That is what lets a remote run be configured from `launchr.yaml` alone — a different workloads repository, say — rather than requiring someone to edit a file on a machine that will be destroyed in an hour. See [Configuring](../install-and-configure/configuring.html) for the file's own sections.

`launchr` already sets `reporting.datastore.type` to `filesystem` there, so raw per-sample metrics are written beside the report instead of being discarded with the instance.

{: .note }
This never touches a local run. Rewriting your own `~/.solr-orbit/benchmark.ini` would be an unwelcome surprise.

## Credentials

No credential belongs in `launchr.yaml`, and a key that looks like one is rejected when the file loads. Values such as `profile` name a credential held elsewhere; the credential itself comes from the ambient chain — environment, shared credentials file, instance role, or OIDC.

{: .warning }
`launchr -v` raises logging to DEBUG but deliberately holds `botocore` at INFO, because its debug output includes the body of every API response — and an AssumeRole response body is a temporary access key and secret in plain text.
