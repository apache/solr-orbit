# launchr

launchr orchestrates [Apache Solr Orbit](https://github.com/apache/solr-orbit)
benchmarks over a matrix of Solr versions × workloads × hardware profiles ×
cluster configs, enriches each result with the metadata a trend graph needs, and
writes it to pluggable storage.

It is the piece that turns Solr Orbit from "a tool a human runs once" into a
continuous benchmark system. The companion tool that renders the results as a
website is `reportr`.

Tracking issue: [apache/solr-orbit#98](https://github.com/apache/solr-orbit/issues/98).

## Quick start

Docker is the only prerequisite beyond a Solr Orbit install.

```bash
# See what would run, without running it. Offline and instant.
launchr run --dry-run

# A fast smoke run: 1000 documents per corpus instead of the full dataset.
launchr run --versions 9.0.0,9.7.0,9.11.0 --workloads nyc_taxis --test-mode

# The real thing. The full nyc_taxis corpus is 165 million documents, so this
# takes hours per version and downloads tens of gigabytes the first time.
launchr run --versions 9.0.0,9.7.0,9.11.0 --workloads nyc_taxis
```

Results land under `~/.solr-orbit/benchmark-results/`:

```
~/.solr-orbit/benchmark-results/
├── runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json
├── runs/nyc_taxis/2026-10-15/run-d4e5f6/results.json
├── runs/nyc_taxis/2026-10-15/run-g7h8i9/results.json
└── summaries/2026-10-15-session-f00ba7.yaml
```

Three versions give three reports — and a chart with an actual slope rather than
a single dot.

## What a run does

For each provisioning group, infrastructure is created once and reused. Then for
each cell in the group:

1. **Deploy** the Solr version under test with the cell's cluster config.
2. **Health-check** it, reading `/solr/admin/info/system` for the exact commit
   that was built, the JVM, and the build timestamp.
3. **Resolve** where the version sits on the chart's x-axis.
4. **Run** `solr-orbit run --pipeline=benchmark-only` against it.
5. **Enrich** Solr Orbit's report with a `launchr` block and store it.
6. **Undeploy**, leaving no data for the next cell to inherit.

A cell that fails produces a report with `"status": "failed"` and its logs, and
does not stop the next cell. Infrastructure is torn down whatever happens.

## Commands

| Command | What it does |
|---------|--------------|
| `launchr run` | Walk the matrix |
| `launchr run --dry-run` | Print the plan and the exact `solr-orbit` command lines; run nothing |
| `launchr validate-config` | Print the resolved configuration and where each value came from |
| `launchr list profiles` | Configured provisioning profiles |
| `launchr list cluster-configs` | Configured cluster configs, with the environment each applies |
| `launchr list plugins` | Available provisioning strategies, install methods and storage backends |

`--solr-port PORT` overrides the port on every provisioning profile, for when the
default is taken by a Solr of your own:

```bash
launchr run --versions 9.11.0 --workloads nyc_taxis --solr-port 19983
```

## Configuration

`launchr.yaml` in the working directory, or `--config FILE`. Precedence is
**CLI flag > environment variable > `launchr.yaml` > built-in default**, and
`validate-config` shows which won:

```
storage.path = '~/.solr-orbit/benchmark-results'            <- launchr.yaml
solr_versions = ['9.11.0']                                  <- $SOLR_VERSIONS
benchmark.test_mode = True                                  <- CLI flag
registry = 'docker.io/library/solr'                         <- built-in default
```

| Setting | Flag | Environment variable |
|---------|------|----------------------|
| Solr versions | `--versions` | `SOLR_VERSIONS` |
| Workloads | `--workloads` | `LAUNCHR_WORKLOADS` |
| Provisioning profiles | `--provisioning` | `LAUNCHR_PROVISIONING` |
| Cluster configs | `--cluster-config` | `LAUNCHR_CLUSTER_CONFIG` |
| Storage backend | `--storage` | `LAUNCHR_STORAGE_BACKEND` |
| Storage path | `--storage-path` | `LAUNCHR_STORAGE_PATH` |
| Image repository | `--registry` | `LAUNCHR_REGISTRY` |

Credentials are never read from a config file. A key that looks like one is
rejected — launchr uses the ambient credential chain.

### Cluster configs

A cluster config mixes two mechanisms, and launchr sends each to the right
place:

| Key | Where it goes |
|-----|---------------|
| `heap: "4g"` | `SOLR_HEAP` on the Solr process |
| `gc: "G1GC"` | `GC_TUNE` — the same flags as Solr Orbit's `g1gc` mixin |
| `solr_opts` | `SOLR_OPTS` |
| `shards: 3` | workload parameter `num_shards` |
| `replicas: 2` | workload parameter `replication_factor` |

Shards and replicas are workload parameters because that is what the workloads
repository's shared `create_collection.json` operation reads. The exact
environment applied is recorded in every report as
`launchr.cluster_config.applied_env`, so a reader never has to guess what
`"G1GC"` meant on the day.

Note that launchr does **not** pass `--cluster-config` to Solr Orbit. Solr Orbit
only applies a cluster config on its own local pipelines; under
`benchmark-only` it would record the name without acting on it, which would put
a claim in the report that nothing honoured.

## The stored report

Solr Orbit's `test_run.json`, byte for byte, plus one `launchr` key — so
`solr-orbit compare` and `TestRun.from_dict()` still work on a stored report.
The added block carries what a chart needs and a benchmark cannot know about
itself:

```json
"launchr": {
  "schema_version": 1,
  "run_id": "run-a1b2c3",
  "session_id": "session-f00ba7",
  "status": "completed",
  "solr": {
    "version": "9.11.0",
    "commit": "abc1234def",
    "version_timestamp": "2026-10-04T00:00:00Z",
    "version_timestamp_source": "apache-releases",
    "version_kind": "release",
    "jvm": {"vendor": "Eclipse Adoptium", "version": "21.0.5"}
  },
  "infra": {"provisioning_profile": "local-docker", "provider": "local", "nodes": 1},
  "cluster_config": {"heap": "4g", "gc": "G1GC", "applied_env": {"SOLR_HEAP": "4g"}},
  "workload": {"name": "nyc_taxis", "revision": "0b99cd0"}
}
```

### Where the x-axis timestamp comes from

Graphs are plotted by **when the Solr version was created**, not when the
benchmark ran — so re-benchmarking an old release lands it in its correct
historical position. launchr never assumes a clone of `apache/solr` is
available, and tries in order:

1. `apache-releases` — the release date from
   `projects.apache.org/json/projects/solr.json`. Day precision, one HTTP call,
   authoritative for releases.
2. `info-system` — the build timestamp inside `solr-impl-version`, from the call
   launchr already makes to health-check the cluster. Second precision, needs no
   network beyond the cluster itself. Primary for nightlies and the universal
   fallback.

Which source answered is recorded as `version_timestamp_source`, because a
release date and a build timestamp are not the same clock.

## Local runs are for developing the system, not for publishing

On a laptop the load driver shares a machine with Solr, there is no CPU pinning
or page-cache control, and Docker Desktop adds a virtualisation layer. Reports
record `infra.provider: "local"` so these results can be labelled as what they
are.

## Extending it

Three plugin interfaces, each with a `Protocol` in a `base.py`:

- **`provisioning/`** — create infrastructure, run Solr Orbit on its load
  driver, destroy it. Where the benchmark executes is a property of the
  infrastructure, which is why it lives here rather than in a separate plugin
  type.
- **`install/`** — put one Solr version on provisioned infrastructure and take
  it off again.
- **`storage/`** — read and write reports, with writes refusing to overwrite,
  because stored reports are immutable.

Each is a plain registry dict today. They become Python entry points — so
out-of-tree plugins work — in the phase that adds a second implementation of
each.
