---
title: Installing
parent: Install and Configure
grand_parent: User Guide
nav_order: 5
---

# Installing Apache Solr Orbit

You can install Apache Solr Orbit directly on a host running Linux or macOS. This page
provides general hardware considerations and step-by-step installation instructions.

## Choosing appropriate hardware

When selecting a host, consider which workloads you want to run. To see a list of available
benchmark workloads, visit the
[solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads) repository on
GitHub. Make sure that the Solr Orbit host has enough free storage space to store the
compressed data corpus and the fully decompressed data once benchmarking begins.

Use the following table to estimate the minimum free space required (compressed + uncompressed):

| Workload name | Document count | Compressed size | Uncompressed size |
| :----: | :----: | :----: | :----: |
| geonames | 11,396,503 | 252.9 MB | 3.3 GB |
| nyc_taxis | 165,346,692 | 4.5 GB | 74.3 GB |

Your Solr Orbit host should use solid-state drives (SSDs) for storage. Spinning-disk hard
drives introduce performance bottlenecks that make benchmark results unreliable.
{: .tip}

## Prerequisites

Before installing Solr Orbit, ensure the following software is available on your host:

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager. Installs a
  suitable Python (3.12 or later) automatically if one is not already present.
- **Git 2.3 or later** — required to fetch workloads from a remote repository.
- **Docker** — required for the `--pipeline=docker` pipeline, which starts a Solr cluster
  automatically before the run.
- **JDK 21** — required for the `--pipeline=from-distribution` pipeline, which downloads and
  installs a Solr release locally.
- **pbzip2** *(optional)* — parallel bzip2 decompressor for faster decompression of `.bz2`
  corpora. Install via `apt install pbzip2` or `brew install pbzip2`. If absent, Solr Orbit
  falls back to Python's standard `bz2` library automatically (slower but fully functional).

### Checking software dependencies

uv manages Python versions for you — there is no need for a system Python or pyenv.
It downloads Python 3.12 automatically the first time you sync the project.
{: .tip}

- Check that `uv` is installed:

  ```bash
  uv --version
  ```

  If not, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`
  or `brew install uv`. See the
  [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)
  for other options.

- Check that Git 2.3 or later is installed:

  ```bash
  git --version
  ```

## Installing on Linux and macOS

Apache Solr Orbit is not yet published on PyPI. Install it directly from the source
repository.
{: .note}

Clone the repository and sync the project:

```bash
git clone https://github.com/apache/solr-orbit.git
cd solr-orbit
uv sync
```

This creates a virtual environment in `.venv`, installs Solr Orbit in editable mode
along with all its dependencies (pinned via `uv.lock`), and downloads Python 3.12 if
it is not already available.

After the installation completes, verify it is working:

```bash
uv run solr-orbit --version
```

To use `solr-orbit` without the `uv run` prefix, activate the virtual environment:

```bash
source .venv/bin/activate
solr-orbit --version
```

### Developer install

To also install development and test dependencies:

```bash
uv sync --extra develop
```

### Upgrading

To pick up the latest changes, pull from the repository and re-sync:

```bash
cd solr-orbit
git pull
uv sync
```

## Starting a Solr cluster for benchmarking

Solr Orbit can start and stop a Solr cluster for you as part of a benchmark run using two
built-in pipelines:

- `--pipeline=docker` — pulls the official `solr` Docker image and starts a single-node Solr
  cluster before the run. No JDK is required.
- `--pipeline=from-distribution` — downloads a Solr release archive, installs it locally, and
  starts a cluster. JDK 21 must be available on the host.

If you already have a running Solr cluster, use `--pipeline=benchmark-only` and point Solr
Benchmark at it with `--target-hosts`.

See the [run command reference](../../../reference/commands/run.html) for the full list of
pipeline options and flags.

## Directory structure

After running Solr Orbit for the first time, all related files are stored under
`~/.solr-orbit/`:

```
~/.solr-orbit/
├── benchmark.ini
├── benchmarks/
│   ├── data/
│   │   └── nyc_taxis/
│   ├── distributions/          # populated by --pipeline=from-distribution
│   │   └── solr-9.10.1.tgz
│   ├── test-runs/
│   │   └── <run-id>/
│   │       └── test_run.json
│   └── workloads/
│       └── default/
│           └── nyc_taxis/
├── logging.json
└── logs/
    └── benchmark.log
```

- **`benchmark.ini`** — main configuration file. See [Configuring](configuring.html).
- **`benchmarks/data/`** — downloaded and decompressed workload data corpora.
- **`benchmarks/distributions/`** — cached Solr release archives (only present when using the
  `from-distribution` pipeline).
- **`benchmarks/test-runs/`** — one subdirectory per run, each containing `test_run.json` with
  the computed results for that run.
- **`benchmarks/workloads/`** — cached workload definitions fetched from the workload repository.
- **`logging.json`** — logging configuration. See [Logging](configuring.html#logging).
- **`logs/`** — benchmark run logs, useful for diagnosing errors.

## Next steps

- [Configuring](configuring.html) — customize `benchmark.ini` for your environment.
- [Running workloads](../working-with-workloads/running-workloads.html) — run your first full benchmark.
