# Example configurations

> The guide these accompany is
> [Continuous Benchmarking](https://apache.github.io/solr-orbit/user-guide/continuous-benchmarking/)
> in the docs site. This file covers only what to change in *these two files*; the concepts, the AWS
> setup and the publishing steps are documented there.

Configurations that are *not* meant to be used from a checkout as they stand.
They exist to be read, copied, and adapted — most naturally into whatever runs
your benchmarks on a schedule, where the job owns its own config.

The repository root keeps the two that *are* meant to work on a fresh
checkout: [`launchr.yaml`](../launchr.yaml) runs Solr in local Docker on your
own machine, and [`reportr.yaml`](../reportr.yaml) builds the site from what it
produced. Neither touches a cloud account. Those are the defaults `launchr run`
and `reportr build` pick up with no `--config` at all.

## What is here

### `launchr-ec2.yaml`

A real two-node SolrCloud on dedicated EC2: two `m7i.2xlarge` Solr nodes and a
driver of the same size, one standalone ZooKeeper, results written to S3.

```sh
launchr run      --config examples/launchr-ec2.yaml --test-mode
launchr teardown --config examples/launchr-ec2.yaml --dry-run
```

**This one spends money** — roughly $1.50/hour while a run is in flight, plus
EBS. Everything it creates is tagged `project=solr`, and `launchr teardown`
reclaims anything a crash leaves behind.

### `reportr-ec2.yaml`

The counterpart: reads those reports back out of S3 and publishes the static
site beside them.

```sh
reportr build --config examples/reportr-ec2.yaml --serve     # look at it first
reportr build --config examples/reportr-ec2.yaml --publish   # then put it live
```

## What to change before using either

Both files name a specific AWS account's resources, so neither will work
unedited anywhere else.

| Setting | Why it is yours, not ours |
|---|---|
| `storage.path` | An `s3://` bucket you own. |
| `storage.options.profile` | A credentials profile with read/write on that bucket, and nothing else. |
| `provisioning_profiles.*.options.aws_profile` | A *separate* profile with EC2 rights — see below. |
| `provisioning_profiles.*.options.region` | Must match the bucket's region, or every result crosses a region boundary. |
| `provisioning_profiles.*.options.extra_ssh_cidrs` | Stable ranges that should reach the cluster, e.g. an office or VPN pool. |
| `site.publish_to` | Where the site goes. Only meaningful if that prefix is world-readable. |

### Two AWS identities, deliberately

The results bucket and the EC2 fleet are reached with **different**
credentials, and conflating them is the mistake this layout exists to prevent.
The storage profile should have no power over EC2, and the provisioning
profile no standing power at all — ours holds only `sts:AssumeRole` into a role
that carries the EC2 rights.

Neither file contains a credential, and neither should: launchr rejects
anything in a config that looks like one. A profile name is a pointer, not a
secret.

### The SSH rule is a snapshot

By default launchr opens SSH and the Solr admin port to the public address of
whatever machine starts the run, detected at that moment. That is the right
default and also the fragile part — a public address can change mid-run, and
when it does the `/32` silently stops matching and an hours-long benchmark
dies at the transport layer with nothing wrong with it. `extra_ssh_cidrs`
names stable ranges to open alongside it:

```yaml
options:
  extra_ssh_cidrs:
    - 203.0.113.0/24      # office
    - 198.51.100.0/24     # VPN pool
```

## Reaching the machines while a run is in flight

launchr creates an ephemeral SSH key pair per session, writes the private key
to a `0600` file for the life of the run, and **deletes it at teardown** — so
this only works while a run is actually going.

```sh
# the key: one per session, under the system temp directory
ls -t "${TMPDIR:-/tmp}"/launchr-session-*/*.pem | head -1

# the driver's address: launchr logs it when it starts the benchmark
grep 'Running Solr Orbit on' <your launchr output>

ssh -i "$KEY" ec2-user@"$DRIVER"
```

Worth knowing once you are on the driver:

| What | Where |
|---|---|
| Live Solr Orbit log | `~/.solr-orbit/logs/benchmark.log` — fixed path, always the current cell |
| Finished run reports | `~/.solr-orbit/benchmarks/test-runs/<test-run-id>/test_run.json` |
| Corpus | `~/.solr-orbit/benchmarks/data/<workload>/` |
| Solr Orbit itself | `~/orbit-venv/bin/python` |

The Solr nodes are reached the same way, with the same key; `docker logs
launchr-solr` and `docker logs launchr-zk` are what you usually want there.
