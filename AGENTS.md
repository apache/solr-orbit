# AGENTS.md

This file provides guidance to AI coding agents working with this repository.

## Development Setup

Prerequisites: `pyenv`, JDK 21, Docker, `docker-compose`, `jq`

Optional: `pbzip2` (parallel bzip2 — install via `apt install pbzip2` or `brew install pbzip2`).
Without it, `.bz2` corpus decompression falls back to Python stdlib (slower).

```bash
make develop          # Install Python 3.10 via pyenv, create .venv, install all deps
source .venv/bin/activate  # Activate virtual environment
```

## Common Commands

```bash
make lint             # Run pylint on osbenchmark/, benchmarks/, scripts/, tests/, it/
make test             # Run unit tests (pytest tests/)
pytest tests/path/to/test_file.py::TestClass::test_method  # Run a single test
make it               # Run integration tests via tox (requires Java, Docker; ~30 min)
make it310            # Integration tests for Python 3.10 only
make benchmark        # Run performance benchmarks (pytest benchmarks/)
make build            # Build distribution wheel
make clean            # Remove build artifacts, caches, tox environments
```

## Code Style

- **Linter**: pylint with `pylint-quotes` plugin (`.pylintrc`)
- **String quotes**: Double quotes enforced
- **Max line length**: 180 characters
- **Max module lines**: 1000

## Architecture

Apache Solr Benchmark (ASB) is a **macrobenchmarking framework** for Apache Solr clusters, using an **actor-based concurrent execution model** via the [Thespian](https://thespianpy.com/) library.

### Entry Points

- `solr-benchmark` / `sb` → `osbenchmark/benchmark.py:main` — CLI for running benchmarks
- `solr-benchmarkd` / `sbd` → `osbenchmark/benchmarkd.py:main` — Daemon for distributed worker nodes

### Core Package (`osbenchmark/`)

**Orchestration layer:**
- `benchmark.py` — CLI arg parsing, subcommands: `run`, `list`, `info`, `generate`, `convert-workload`
- `test_run_orchestrator.py` — Pipeline execution: prepares, launches cluster, runs workload, publishes results
- `actor.py` — Thespian actor system setup for parallel/distributed execution
- `config.py` — Configuration loading and management

**Cluster management (`builder/`):**
- `solr_provisioner.py` — Download, install and launch Solr (from distribution, sources, or Docker)
- `provisioners/` — Generic node provisioning infrastructure
- `downloaders/` — Download Solr distributions
- `installers/` — Install Solr on provisioned nodes
- `launchers/` — Start/stop cluster nodes
- `executors/` — Execute remote commands on cluster nodes
- `configs/` — Jinja2 templates for cluster configuration

**Benchmark execution:**
- `workload/` — Load and manage workload definitions (test procedures, operations, schedules)
- `worker_coordinator/` — Coordinate distributed worker nodes; `driver.py` drives actual load
- `worker_coordinator/runner.py` — Solr operation runners (`SolrBulkIndex`, `SolrSearch`, `SolrCreateCollection`, etc.)
- `metrics.py` — Collect, store, and aggregate benchmark metrics (filesystem-backed; no external store)
- `telemetry.py` — Solr-specific telemetry devices (JVM, node, collection, query, indexing, cache stats)
- `publisher.py` — Publish and format benchmark results
- `result_writer.py` — Write results to local filesystem (JSON/CSV)

**Data and connectivity:**
- `client.py` — `SolrAdminClient` and `SolrClient` (HTTP via `requests`/`pysolr`; Collections API, `/select`, `/update`)
- `synthetic_data_generator/` — Generate synthetic test datasets
- `workload_generator/` — Generate workload definition files from existing Solr collections

**Workload conversion:**
- `conversion/workload_converter.py` — Convert an OpenSearch Benchmark workload directory to Solr format
- `conversion/detector.py` — Detect whether a workload uses OpenSearch-only operations/query DSL
- `conversion/query.py` — Translate OpenSearch Query DSL to Solr JSON Query DSL
- `conversion/schema.py` — Translate OpenSearch index mappings to Solr `managed-schema.xml`

**Utilities:**
- `utils/` — IO, process management, console output, network, version parsing, options handling
- `cloud_provider/` — Cloud provider integrations (AWS via boto3, GCP via google-auth)
- `visualizations/` — Result visualization

### Test Structure

- `tests/` — Unit tests mirroring `osbenchmark/` structure
- `it/` — Integration tests (spin up real Solr clusters via Docker/provisioning)
- `benchmarks/` — Performance benchmarks for ASB itself

### Workload System

Workloads are defined as JSON/YAML files with:
- **Operations**: individual actions (bulk indexing, search queries)
- **Test procedures**: sequences of operations with parameters and schedules
- **Corpora**: dataset files (compatible with OpenSearch Benchmark format)

Workloads must be in Solr format. Use `solr-benchmark convert-workload` to convert from
OpenSearch Benchmark format. Workloads can be loaded from a local path (`--workload-path`)
or from a git workload repository (`--workload-repository`).

### Pipeline Execution Flow

1. **Prepare** — Load workload, configure metrics store
2. **Build** (optional) — Download and provision Solr cluster
3. **Run** — Execute test procedure via worker coordinator and drivers
4. **Publish** — Store metrics, generate report

## Key Technologies

- **Python 3.10+** with `pysolr` (data ops), `requests` (HTTP admin), `psutil` (I/O metrics), `thespian` (actor model), `pytest` (tests), `tabulate` (console output)
- **Metrics store**: local filesystem — JSON/CSV result files at `~/.solr-benchmark/`, SQLite test-runs store
- **Docs**: Jekyll 4.x + just-the-docs gem in `docs/`; deployed to GitHub Pages via `.github/workflows/docs.yml`
