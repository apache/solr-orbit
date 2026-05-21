---
title: Running a Workload
parent: Working with Workloads
grand_parent: User Guide
nav_order: 9
---

# Running a Workload

## Listing available workloads

To see which named workloads are available in the configured workload repository:

```bash
solr-benchmark list workloads
```

This prints the name and description of each workload that Solr Benchmark can fetch and run
by name. Workloads are fetched from the repository configured under `[workloads]` in
`~/.solr-benchmark/benchmark.ini` (default:
[https://github.com/janhoy/solr-benchmark-workloads](https://github.com/janhoy/solr-benchmark-workloads)).

---

## Basic syntax

```bash
solr-benchmark run [--pipeline PIPELINE] [--target-hosts HOSTS] \
  [--workload WORKLOAD | --workload-path PATH] [OPTIONS]
```

---

## Using a named workload

Named workloads are fetched from
[https://github.com/janhoy/solr-benchmark-workloads](https://github.com/janhoy/solr-benchmark-workloads):

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis
```

---

## Using a local workload path

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path /path/to/my-workload
```

---

## Selecting a test procedure

A workload may define multiple test procedures. Use `--test-procedure` to select one:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --test-procedure bulk-only
```

If `--test-procedure` is omitted, Solr Benchmark runs the default test procedure defined
in `workload.json`.

---

## Running a subset of tasks

Use `--include-tasks` or `--exclude-tasks` to run only part of a workload's schedule. Both
flags accept a comma-separated list of task names.

Run only the indexing and commit tasks, skipping all search operations:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --include-tasks bulk-index,commit
```

Run the full workload but skip aggregation-heavy tasks:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --exclude-tasks passenger-count-agg,date-histogram
```

Task names correspond to the `name` field on each operation in the workload's schedule.
{: .note}

---

## Test mode

Pass `--test-mode` to run a shortened version of the workload (at most 1,000 documents) for
quick validation:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --test-mode
```

When `--test-mode` is active, Solr Benchmark uses a companion `-1k` corpus file (for
example, `data-1k.json.gz`) instead of the full dataset. See
[Creating Custom Workloads](creating-custom-workloads.html#test-mode-support) for instructions
on creating the companion file for your own workload.

---

## Targeting a multi-node cluster

Separate multiple hosts with commas:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts node1:8983,node2:8983,node3:8983 \
  --workload nyc_taxis
```

---

## Using the Docker pipeline

The `docker` pipeline pulls the official `solr` Docker image, starts a single-node cluster,
runs the workload, and stops the cluster when finished. No JDK is required.

```bash
solr-benchmark run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --test-mode
```

---

## Using the from-distribution pipeline

The `from-distribution` pipeline downloads a Solr release archive, installs it locally,
and starts a cluster. JDK 21 must be available on the host.

```bash
solr-benchmark run \
  --pipeline from-distribution \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --cluster-config 4gheap
```

---

## Customizing workload parameters

Override workload Jinja2 parameters at runtime with `--workload-params`:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload nyc_taxis \
  --workload-params "bulk_size:1000,search_clients:4"
```

Multiple parameters are separated by commas. See
[Fine-tuning Workloads](finetune-workloads.html) for a full list of tuning options.

---

## Error handling

By default, the run continues if individual operations fail. To abort on the first error:

```bash
solr-benchmark run --on-error abort ...
```

---

## Verifying results

After a successful run, check the console summary for error rates and throughput. To verify
that documents were actually indexed, open the Solr Admin UI collection overview:

```
http://localhost:8983/solr/#/~collections
```

Select the collection and confirm that the document count matches the expected number for
your workload. For `nyc_taxis` in `--test-mode`, you should see approximately 1,000
documents.

The full computed results for every run are stored in
`~/.solr-benchmark/benchmarks/test-runs/<run-id>/test_run.json`. To view the results for
the most recent run:

```bash
ls -t ~/.solr-benchmark/benchmarks/test-runs/ | head -1 | \
  xargs -I{} cat ~/.solr-benchmark/benchmarks/test-runs/{}/test_run.json | python3 -m json.tool
```
