# launchr

launchr orchestrates [Apache Solr Orbit](https://github.com/apache/solr-orbit)
benchmarks over a matrix of Solr versions × workloads × hardware profiles ×
cluster configs, enriches each result with the metadata a trend graph needs, and
writes it to pluggable storage.

It is the piece that turns Solr Orbit from "a tool a human runs once" into a
continuous benchmark system. The companion tool that renders the results as a
website is `reportr`.

Tracking issue: [apache/solr-orbit#98](https://github.com/apache/solr-orbit/issues/98).

> **User documentation lives in the docs site**, not here:
> [Continuous Benchmarking](https://apache.github.io/solr-orbit/user-guide/continuous-benchmarking/)
> for the guide, and the
> [launchr Command Reference](https://apache.github.io/solr-orbit/reference/launchr-cli.html)
> for flags and options. This file keeps only the design notes that are useful when reading the
> source, and is deliberately not a second copy of the documentation.

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
