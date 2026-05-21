---
title: Quickstart
nav_order: 2
---

# Apache Solr Benchmark quickstart

This page outlines how to quickly install Apache Solr Benchmark and run your first benchmark workload.

## Prerequisites

To perform the quickstart steps, you'll need the following:

- Git 2.3 or later
- Python 3.10 or later
- An active Apache Solr cluster, **or** Docker (to let Solr Benchmark start one for you)

## Set up a Solr cluster

If you don't already have a running Solr cluster, the easiest way to start one is with Docker:

```bash
docker run -d --name solr-benchmark -p 8983:8983 solr:9 solr-demo
```

Verify that Solr is running by opening [http://localhost:8983/solr/](http://localhost:8983/solr/) in your browser, or with:

```bash
curl http://localhost:8983/solr/admin/info/system?wt=json
```

With your cluster running, you can now install Apache Solr Benchmark.

## Installing Apache Solr Benchmark

{: .note }
Apache Solr Benchmark is not yet published on PyPI. Install it directly from the source repository.

Clone the repository and install in editable mode:

```bash
git clone https://github.com/janhoy/solr-benchmark.git
cd solr-benchmark
pip install -e .
```

After installation completes, verify that Solr Benchmark is running:

```bash
solr-benchmark --version
```

If successful, Solr Benchmark prints its version.

## Running your first benchmark

You can now run your first benchmark. The following example uses the built-in `nyc_taxis` workload.

### Understanding workload command flags

Benchmarks are run using the [`run`](reference/commands/run.html) command. Some commonly used flags:

For the full list of flags, see the [run command reference](reference/commands/run.html) and [command flags reference](reference/commands/command-flags.html).
{: .tip }

- `--pipeline=benchmark-only` — tells Solr Benchmark that you are providing your own Solr cluster; Solr Benchmark will not start or stop one.
- `--pipeline=docker` — tells Solr Benchmark to start a Solr cluster in Docker before the run and stop it afterwards.
- `--pipeline=from-distribution,` - tells Solr Benchmark to download and install Solr from a distribution.
- `--workload=nyc_taxis` — the name of the workload to run.
- `--target-hosts=localhost:8983` — the host and port of the Solr cluster to benchmark, if using `benchmark-only` pipeline.
- `--distribution-version=9.10.1` — the Solr version to use when provisioning a cluster.
- `--test-mode` — runs an abbreviated version of the workload (first 1,000 documents per task) for a quick sanity check. Metrics produced in test mode are not meaningful for production analysis.

### Running the workload

To run the `nyc_taxis` workload against an existing Solr cluster:

```bash
solr-benchmark run \
  --pipeline=benchmark-only \
  --target-hosts=localhost:8983 \
  --workload=nyc_taxis \
  --test-mode
```

To instead let Solr Benchmark start a Solr cluster for you using Docker:

```bash
solr-benchmark run \
  --pipeline=docker \
  --distribution-version=9.10.1 \
  --workload=nyc_taxis \
  --test-mode
```

When the `run` command executes, all tasks and operations in the `nyc_taxis` workload run sequentially.

### Validating the test

After the benchmark completes, verify it ran correctly:

- Check that a collection named `nyc_taxis` was created in your Solr cluster (visible in the Solr Admin UI at [http://localhost:8983/solr/](http://localhost:8983/solr/)).
- In test mode, only a subset of documents are indexed. For a full run (without `--test-mode`), compare the document count in the collection against the expected count in the workload's `workload.json` file.

### Understanding the results

Once the benchmark completes, Solr Benchmark prints a summary table to the console:

```
------------------------------------------------------
    _______             __   _____
   / ____(_)___  ____ _/ /  / ___/_________  ________
  / /_  / / __ \/ __ `/ /   \__ \/ ___/ __ \/ ___/ _ \
 / __/ / / / / / /_/ / /   ___/ / /__/ /_/ / /  /  __/
/_/   /_/_/ /_/\__,_/_/   /____/\___/\____/_/   \___/
------------------------------------------------------

|                        Metric |                      Task |   Value |   Unit |
|------------------------------:|--------------------------:|--------:|-------:|
|                Min Throughput |                     index | 3697.64 | docs/s |
|               Mean Throughput |                     index | 3697.64 | docs/s |
|             Median Throughput |                     index | 3697.64 | docs/s |
|                Max Throughput |                     index | 3697.64 | docs/s |
|       50th percentile latency |                     index | 197.368 |     ms |
|      100th percentile latency |                     index |  214.59 |     ms |
|  50th percentile service time |                     index | 197.368 |     ms |
| 100th percentile service time |                     index |  214.59 |     ms |
|                    error rate |                     index |       0 |      % |
|                Min Throughput |                 match-all |      18 |  ops/s |
|               Mean Throughput |                 match-all |      18 |  ops/s |
|             Median Throughput |                 match-all |      18 |  ops/s |
|                Max Throughput |                 match-all |      18 |  ops/s |
|      100th percentile latency |                 match-all | 67.3283 |     ms |
| 100th percentile service time |                 match-all | 10.5466 |     ms |
|                    error rate |                 match-all |       0 |      % |
|                Min Throughput |                     range |   35.23 |  ops/s |
|               Mean Throughput |                     range |   35.23 |  ops/s |
|             Median Throughput |                     range |   35.23 |  ops/s |
|                Max Throughput |                     range |   35.23 |  ops/s |
|      100th percentile latency |                     range | 38.3106 |     ms |
| 100th percentile service time |                     range | 9.70796 |     ms |
|                    error rate |                     range |       0 |      % |
|                Min Throughput |  asc_sort_passenger_count |   75.87 |  ops/s |
|               Mean Throughput |  asc_sort_passenger_count |   75.87 |  ops/s |
|             Median Throughput |  asc_sort_passenger_count |   75.87 |  ops/s |
|                Max Throughput |  asc_sort_passenger_count |   75.87 |  ops/s |
|      100th percentile latency |  asc_sort_passenger_count | 22.2872 |     ms |
| 100th percentile service time |  asc_sort_passenger_count | 8.95417 |     ms |
|                    error rate |  asc_sort_passenger_count |       0 |      % |
[...]

----------------------------------
[INFO] ✅ SUCCESS (took 38 seconds)
----------------------------------
```

Each task in the summary corresponds to a specific operation that was performed against the Solr cluster during the benchmark. Each task produces the following metrics:

- **Throughput** — the number of successful Solr operations completed per second (`ops/s`) or documents per second (`docs/s`) for indexing tasks.
- **Latency** — the total time from when the benchmark submitted the request until it received a complete response, including any time the operation spent waiting in the internal scheduling queue.
- **Service time** — the time from when the request was sent to Solr until the response was received, excluding scheduling queue wait time. When no target throughput is set, service time and latency are equal.
- **Error rate** — the percentage of operations that returned an error or timed out. A value of `0` means all operations completed successfully.

For more details on how the summary report is generated, see [Summary report](reference/summary-report.html).

The computed results are also saved to `~/.solr-benchmark/benchmarks/test-runs/<run-id>/test_run.json` for later comparison with [`solr-benchmark compare`](reference/commands/compare.html).

## Running Solr Benchmark on your own cluster

Now that you're familiar with running a benchmark, you can run Solr Benchmark against your own Solr cluster. Use the same `run` command and adjust the following settings:

- Replace `localhost:8983` with your cluster's host and port.
- Remove `--test-mode` to run the full workload rather than the abbreviated test.
- Use `--workload-params` to override workload parameters such as the number of clients or the target throughput.
- Use `--include-tasks` or `--exclude-tasks` to run only the operations you care about.

```bash
solr-benchmark run \
  --pipeline=benchmark-only \
  --target-hosts=<your-solr-host>:8983 \
  --workload=nyc_taxis
```

## Next steps

See the following resources to learn more about Apache Solr Benchmark:

- [User guide](user-guide/) — understand workloads, pipelines, challenges, and how to interpret results.
- [Converter tool](converter/) — convert an existing OpenSearch Benchmark workload to Solr format.
- [Command reference](reference/commands/) — complete CLI reference for all subcommands and flags.
- [Metrics reference](reference/metrics/) — understand what every metric key means and how raw samples are stored.
