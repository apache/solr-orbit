---
title: A Local Trial Run
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 20
---

# A Local Trial Run

Before provisioning anything, run the whole loop on your own machine. It takes a few minutes, needs only Docker, and proves the pipeline end to end — which is the cheapest place to discover a misconfiguration.

## Prerequisites

A working Solr Orbit installation and a running Docker daemon. Nothing else; `launchr` starts and stops the Solr containers itself.

## 1. See the plan without running it

`--dry-run` is pure and offline. It expands the matrix, prints the groups, and shows the exact `solr-orbit` command line each cell would execute:

```bash
launchr run --versions 9.9.0,9.10.1,9.11.0 --workloads nyc_taxis --test-mode --dry-run
```

```
3 cell(s) in 1 provisioning group(s)

group local-docker (local/docker, 1 node(s))
  cell 1/3  nyc_taxis 9.9.0 [local-docker default-1s1r]
  cell 2/3  nyc_taxis 9.10.1 [local-docker default-1s1r]
  cell 3/3  nyc_taxis 9.11.0 [local-docker default-1s1r]
  teardown
```

Read the printed command lines. Everything `launchr` will ask of Solr Orbit is visible there, which makes this the fastest way to confirm a configuration change did what you meant.

## 2. Run the matrix

Drop `--dry-run`. `--test-mode` truncates every corpus to 1000 documents, turning hours into minutes:

```bash
launchr run --versions 9.9.0,9.10.1,9.11.0 --workloads nyc_taxis --test-mode
```

Each cell pulls its Solr image, starts a container, benchmarks it, stores the report and removes the container. The session ends with a summary naming every cell and its outcome.

## 3. Build and read the site

```bash
reportr build --serve
```

This reads every stored report, writes a static site to `./site-output`, and serves it at `http://127.0.0.1:8080`. Three versions give the chart a real trend line rather than a single point.

## Where things landed

```
~/.solr-orbit/benchmark-results/
├── runs/nyc_taxis/<date>/<run-id>/results.json
└── summaries/<date>-<session-id>.yaml
```

`launchr validate-config` prints the fully resolved configuration and, for each setting, where the value came from — a built-in default, the config file, an environment variable or a command-line flag. It is the quickest way to answer "why is it using *that*?".

{: .note }
Reports from a local run record `infra.provider: "local"`, because the load driver is sharing a machine — and a CPU — with Solr. That is a label, not a warning to ignore: these numbers are for developing the pipeline, not for publishing. [Performance Testing Best Practices](../optimizing-benchmarks/best-practices.html) explains why laptops make poor benchmark hosts.

## Next

With the loop working, [Configuring launchr](configuring-launchr.html) covers describing the matrix you actually want.