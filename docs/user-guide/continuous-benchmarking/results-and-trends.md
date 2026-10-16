---
title: Results and Trend Reports
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 40
---

# Results and Trend Reports

`reportr` turns a directory of stored reports into a static website: one chart per metric, one point per run, ordered along the version timeline. It runs no benchmarks and reads nothing but the result store.

## Building

```bash
reportr build                      # write ./site-output
reportr build --serve              # and serve it at http://127.0.0.1:8080
reportr build --out /srv/www       # write somewhere else
```

With no configuration, `reportr` reads the same store `launchr` writes to, so `reportr build` immediately after a run needs no arguments.

```bash
reportr metrics                    # which metric keys the stored reports can supply
```

Which percentiles exist depends on `--latency-percentiles` and on how many samples a run produced: a `--test-mode` run may offer `p50` and `p100` but no `p99`, because the 99th percentile of a hundred samples is a single observation.

## Reading the site

The site is one page per workload, with charts grouped by what each task measures.

**The x-axis is the version timeline, not the run date.** A benchmark of Solr 9.0 executed today appears where 9.0 was released. This is what makes the chart a history of Solr rather than a history of your cron job. Each point's tooltip names the source that placed it.

**Indexing tasks are charted on throughput; query tasks on service time.** A query held at a fixed target throughput is judged on latency, because its rate was dictated. A query pushed as hard as it will go is judged on throughput, because its latency is a consequence. Mixing the two on one axis compares things that are not comparable.

**`p50` and `p90` lead, `p99` follows.** The stock query tasks measure a hundred iterations, and the 99th percentile of a hundred samples moves run to run for reasons unrelated to Solr.

**Lifecycle tasks are excluded.** Creating and deleting a collection is setup, not a measurement.

Clicking a point opens the full enriched report behind it — the exact Solr commit, the infrastructure, the cluster config, and the workload revision.

{: .note }
Nothing is inferred. There is no automatic regression detection, and no marker appears unless something concrete changed: the workload's git revision moved, a task's recorded setup note changed, or a human wrote an annotation. A detector that cried wolf would be worse than no annotation at all.

## Configuring

`reportr` reads `reportr.yaml` from the current directory, or `--config`.

```yaml
storage:
  backend: s3
  path: "s3://my-bucket/benchmarks/v1"
  options:
    region: eu-north-1
    profile: solr-orbit

site:
  out: "./site-output"
  title: "Apache Solr Benchmarks"
  publish_to: "s3://my-bucket/public"

metrics:
  - throughput.mean
  - service_time.mean
  - service_time.p50
  - service_time.p90
  - service_time.p99
  - error_rate

workloads:
  nyc_taxis:
    description: >-
      165 million yellow-cab rides: bulk indexing of flat documents, then
      numeric range filters, date histogram facets and large sorted result sets.
    default_tasks: [index, match-all, range, date_histogram_facet]
    featured_tasks: [range, date_histogram_facet]

annotations:
  - version: "9.11.0"
    text: "Fixes SOLR-12345, a 30% regression in JSON range facets."
    url: "https://issues.apache.org/jira/browse/SOLR-12345"
```

A metric a report does not carry is skipped, so listing `p99` costs nothing on runs too short to have one.

### Per-workload presentation

Every key under `workloads:` is optional. A workload with no entry charts all its tasks and chooses its own defaults, so a new workload appears on the site without a configuration change.

| Key | Effect |
|-----|--------|
| `description` | Shown at the top of the workload's page. |
| `tasks` | Restricts the site to these tasks entirely. |
| `default_tasks` | The lines a shared chart opens with. |
| `featured_tasks` | Tasks that start with a chart of their own. |

A workload can also describe itself. Its `description` in `workload.json` travels with every result, and a `meta` block can nominate tasks — `reportr.chart: own`, `reportr.default: true`, and `reportr.note` to record how a task is set up. Anything in `reportr.yaml` overrides all of it: the workload suggests, whoever runs the site decides.

{: .important }
`reportr`'s precedence is **CLI flag > `reportr.yaml` > built-in default**. Unlike `launchr` there is no environment-variable layer and no `validate-config` subcommand. If you are templating both tools from the same automation, do not assume the `LAUNCHR_*` pattern has a counterpart here.

## Offline by design

The site makes no third-party requests. The charting library is vendored and the fonts are the reader's own, so the page works from a file server, inside a corporate network, and in a browser with everything blocked.

## Next

[Publishing the Site to S3](publishing-to-s3.html) covers putting it somewhere others can read.
