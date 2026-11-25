# reportr

reportr reads the enriched JSON reports that [`launchr`](../launchr/README.md)
writes and emits a **static** benchmark trends site: per-workload data files
plus a single-page app that charts them. No backend, no database, nothing to
operate — the output is HTML, CSS, JS and JSON behind any file server.

Tracking issue: [apache/solr-orbit#99](https://github.com/apache/solr-orbit/issues/99).

> **User documentation lives in the docs site**, not here:
> [Continuous Benchmarking](https://apache.github.io/solr-orbit/user-guide/continuous-benchmarking/)
> for the guide, and the
> [reportr Command Reference](https://apache.github.io/solr-orbit/reference/reportr-cli.html)
> for flags and options. This file keeps only the design notes that are useful when reading the
> source, and is deliberately not a second copy of the documentation.

## What the site shows

**The x-axis is the version timeline, not the run date.** A point sits at the
date the Solr version was created, so re-benchmarking an old release lands it in
its correct historical position rather than at the right-hand edge.

**Charts are grouped by what the task does.** Indexing tasks are judged on
throughput, queries on service time — the same split OpenSearch's published
dashboards make, where the query dashboards filter to `service_time`. Collection
setup and teardown are classified as lifecycle and left out by default: a
`create-collection` latency says nothing about Solr's speed, and charting it
buries the operations that do.

**Only a readable number of series opens by default** — every indexing task and
the first few queries. A workload with a dozen queries would otherwise open as a
dozen overlapping lines. The rest are one click away in the task picker. A
workload that knows better says so, either in its own metadata or in
`reportr.yaml`, and that curated list wins.

**Any task can have a chart of its own.** Tracking something specific — JSON
range facets, say — means reading one task over time, not finding its colour in
a shared chart. Clicking a task's chip gives it its own block, inside the
section for the kind of work it is, with a `#anchor` you can link to. The tasks
a workload lists in `featured_tasks` are simply the ones already switched on;
the balance is the workload's to strike, because every one of them is another
chart on the page.

**A query is charted on what it was driven for.** Solr Orbit records each task's
target throughput with the result, so reportr can tell a query held at three
requests a second from one pushed as hard as it would go. The first says nothing
through its throughput — that number is the rate that was asked for — so it is
read on latency. The second is read on queries per second, and leads its
section. A report written before Solr Orbit recorded the schedule falls back to
latency, which is meaningful either way.

**Nothing on a chart is inferred to be a regression.** What a step means is a
judgement, and a detector that cried wolf would be worse than no annotation, so
markers come from three places that all know something the numbers do not: the
workload revision changed, a task's own `reportr.note` changed (a workload
editing the note saying which facet implementation a query uses is the workload
saying the thing it measures is no longer quite the same thing), or somebody
wrote a release note in `reportr.yaml`:

```yaml
annotations:
  - version: "9.11.0"
    text: "Fixes SOLR-12345, a 30% regression in JSON range facets."
    url: "https://issues.apache.org/jira/browse/SOLR-12345"
    task: range          # optional; default every chart
```

A version nothing was benchmarked at is skipped rather than placed at a guess.

**Query charts lead with p50 and p90.** The stock query tasks measure 100
iterations after warmup, and the 99th percentile of 100 samples is a single
observation that moves run to run for reasons unrelated to Solr. p99 is still
charted when a run carries it, because the tail is what users feel — it is just
not the headline.

**One chart per unit.** Indexing throughput is `docs/s` and a query's is `ops/s`;
on a shared axis the smaller one is flattened against zero.

**Colour encodes whatever varies.** Comparing environments, colour is the line —
one version kind, branch, profile and cluster config, so the site never silently
compares a 3-node EC2 result against a laptop run. Comparing operations within
one environment, colour is the task.

**The Solr version is labelled on the axis**, not on every dot: each release
sits at one date, and every line crossing that date ran that release. Upright
chips under the date axis name the release, because laid flat a version string
is wider than the gap between two of them. They thin out when releases crowd
together and come back as you zoom in.

**Each workload page says what the workload is.** The description comes from the
workload itself — Solr Orbit carries `workload.json`'s `description` into every
result — so reportr needs to know nothing about any particular workload.

**Click any point** for the full report behind it: the exact commit, JVM,
hardware, heap, GC, shard layout, workload revision and per-operation metrics.
Reports are copied into the site rather than linked, so it is self-contained and
needs no bucket exposure.

**Zooming** works three ways: drag a box across a chart, shift-scroll over it,
or drag the slider beneath it. Box zoom is armed from the start, so there is no
tool to press first, and a click without a drag still opens the point's report.
Plain scrolling belongs to the page. The site is static and cannot re-slice the
data the way a live dashboard can, so zoom is how a reader narrows in — which is
why the page carries a "How to read and drive these charts" panel saying all of
this. It stays collapsed until opened, then remembers.

Runs are labelled honestly. A test-mode run says it indexed 1000 documents; a
local run says the load driver shared a machine with Solr and is development
data, not a published result.

## No third-party requests

Apache ECharts is vendored at `site/vendor/echarts.min.js` (Apache-2.0), and the
fonts are system stacks. The published page loads nothing from anyone else — no
CDN, no webfont, no analytics. A test asserts it.

## Not in this phase

Incremental builds with a state file, the retention policy that thins old data,
curated annotations, the cross-workload dashboard, and deployment to
`nightlies.apache.org`. The site is rebuilt from scratch each time, which is
fast enough until there are thousands of runs.

S3 storage *is* implemented: `reportr` reads reports from, and publishes the site
to, either a local directory or a bucket, through the same storage backends
`launchr` uses.
