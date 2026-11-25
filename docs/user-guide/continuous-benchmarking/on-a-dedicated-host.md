---
title: Running on a Dedicated Host
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 50
---

# Running on a Dedicated Host

A laptop is a poor home for a recurring benchmark: it sleeps, its address changes, and its disk is not sized for corpora. Moving the pipeline to a machine that stays up is the step before automating it.

This page covers what differs from an ordinary installation. For prerequisites and the install itself, see [Installing](../install-and-configure/installing.html).

## What the host needs

The host runs `launchr` and `reportr` — the orchestration — and, depending on the provisioning profile, possibly nothing else:

| Profile | What the host does | What it needs |
|---------|--------------------|---------------|
| `local` | Runs Solr *and* the load driver itself | Docker, and enough CPU for both |
| `ec2` | Creates instances and drives them over SSH | Outbound HTTPS and SSH; no Docker |

With a cloud profile the host is a controller: it needs very little CPU, but it must stay reachable for the length of a run, because the benchmark is driven over an SSH connection it holds open.

## Relocating the data directory

By default everything lives under `~/.solr-orbit`: configuration, the corpora cache, test runs, logs, and `launchr`'s result store. On a shared or long-lived host that is rarely the right disk.

`BENCHMARK_HOME` moves all of it:

```bash
export BENCHMARK_HOME=/srv/solr-orbit
```

```
/srv/solr-orbit/.solr-orbit/
├── benchmark.ini                 # configuration
├── logs/benchmark.log            # the current run's log
├── benchmarks/data/              # corpora cache
├── benchmarks/test-runs/         # per-run reports
└── benchmark-results/            # launchr's result store
```

It is read when configuration loads, not frozen at import, so setting it in the unit file or shell profile of whatever runs the benchmark is enough. Set it consistently: a cron job that lacks it will silently build a second, empty history under the service account's home.

## Disk planning

Corpora dominate, and they persist between runs by design — re-downloading 80 GB nightly would be absurd.

| What | Size |
|------|------|
| `nyc_taxis` compressed archive | ~4.8 GB |
| `nyc_taxis` decompressed | ~80 GB |
| Both, as cached | ~85 GB per workload |
| One stored report | a few hundred KB |
| Raw metrics, with the filesystem store | tens to hundreds of MB per run |

Budget roughly 100 GB per large workload, plus steady growth from the result store. The reports themselves are small; it is the corpora that need the disk.

{: .note }
[Installing](../install-and-configure/installing.html) recommends `pbzip2` to speed up decompression, and on a host you control that advice holds. It does not transfer to a cloud driver: Amazon Linux 2023 packages neither `pbzip2` nor `lbzip2`, and the answer there is the zstd corpus variant instead, which `launchr` requests automatically.

## Log rotation

`~/.solr-orbit/logs/benchmark.log` is a fixed path that always holds the current run. Nothing truncates it. On a nightly schedule it grows without bound, so give it a rotation rule:

```
/srv/solr-orbit/.solr-orbit/logs/benchmark.log {
    weekly
    rotate 8
    compress
    missingok
    copytruncate
}
```

`copytruncate` matters: a run may hold the file open across the rotation. Logging itself is configured in `~/.solr-orbit/logging.json` — see [Configuring](../install-and-configure/configuring.html).

## Keeping the host comparable

A benchmark host's value is that it does not change. Pin what you can and record the rest:

- Keep the OS, JVM and Solr Orbit version fixed between runs, and treat upgrading any of them as an event worth annotating on the chart.
- Run nothing else on the machine. A nightly backup overlapping the benchmark window is indistinguishable from a Solr regression.
- If the host is ever rebuilt, say so in the site's annotations. A step in the trend that comes from new hardware is not a step in Solr.

## Next

[Scheduling Nightly Runs](scheduling-nightly-runs.html) puts the pipeline on a timer.
