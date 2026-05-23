---
title: Summary Reports
parent: Understanding Results
grand_parent: User Guide
nav_order: 22
---

# Understanding the Summary Report

At the end of each test run, Apache Solr Orbit prints a summary report to the console and saves the results to disk. The report shows metrics such as throughput, latency, service time, and error rate for each task in the challenge.

## Console output

The summary table is printed after all tasks complete. The following is a real example from a `nyc_taxis` workload run in `--test-mode` against Apache Solr 9.10.1:

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
|                Min Throughput |         delete-collection |    10.8 |  ops/s |
|               Mean Throughput |         delete-collection |    10.8 |  ops/s |
|             Median Throughput |         delete-collection |    10.8 |  ops/s |
|                Max Throughput |         delete-collection |    10.8 |  ops/s |
|      100th percentile latency |         delete-collection | 88.6857 |     ms |
| 100th percentile service time |         delete-collection | 88.6857 |     ms |
|                    error rate |         delete-collection |       0 |      % |
|                Min Throughput |         create-collection |    1.16 |  ops/s |
|               Mean Throughput |         create-collection |    1.16 |  ops/s |
|             Median Throughput |         create-collection |    1.16 |  ops/s |
|                Max Throughput |         create-collection |    1.16 |  ops/s |
|      100th percentile latency |         create-collection | 865.011 |     ms |
| 100th percentile service time |         create-collection | 865.011 |     ms |
|                    error rate |         create-collection |       0 |      % |
|                Min Throughput |      check-cluster-health |   84.98 |  ops/s |
|               Mean Throughput |      check-cluster-health |   84.98 |  ops/s |
|             Median Throughput |      check-cluster-health |   84.98 |  ops/s |
|                Max Throughput |      check-cluster-health |   84.98 |  ops/s |
|      100th percentile latency |      check-cluster-health | 9.81933 |     ms |
| 100th percentile service time |      check-cluster-health | 9.81933 |     ms |
|                    error rate |      check-cluster-health |       0 |      % |
|                Min Throughput |                     index |  3860.9 | docs/s |
|               Mean Throughput |                     index |  3860.9 | docs/s |
|             Median Throughput |                     index |  3860.9 | docs/s |
|                Max Throughput |                     index |  3860.9 | docs/s |
|       50th percentile latency |                     index | 177.464 |     ms |
|      100th percentile latency |                     index | 204.121 |     ms |
|  50th percentile service time |                     index | 177.464 |     ms |
| 100th percentile service time |                     index | 204.121 |     ms |
|                    error rate |                     index |       0 |      % |
```

## Metrics explained

### Throughput

Throughput measures the rate at which operations were completed during the task. Apache Solr Orbit reports four values:

| Metric | Description |
|--------|-------------|
| Min Throughput | The lowest throughput observed across all measurement samples |
| Mean Throughput | The arithmetic mean throughput across all measurement samples |
| Median Throughput | The 50th-percentile throughput |
| Max Throughput | The highest throughput observed |

The unit depends on the task type:
- **`docs/s`** — documents per second, for indexing tasks
- **`ops/s`** — operations per second, for all other tasks (collection management, queries, etc.)

In the example above, the `index` task achieved ~3,861 docs/s. The `check-cluster-health` task ran at ~85 ops/s, and `create-collection` ran at 1.16 ops/s — which makes sense, since collection creation in SolrCloud involves ZooKeeper coordination and takes nearly a second.

### Latency

**Latency** is the total elapsed time from when the client submitted the request to when it received the complete response. This includes any time the request spent waiting in a queue before it was dispatched to the server, plus the server processing time.

Latency percentiles show the distribution of response times across all operations in the task:

- **50th percentile latency** — half of all requests completed within this time
- **100th percentile latency** — the slowest request observed (the worst case)

Higher percentiles (99th, 99.9th) appear in full runs; in `--test-mode` only the 50th and 100th are typically shown due to the small operation count.

### Service time

**Service time** is the time the server spent actively processing the request, excluding any client-side queuing wait. It is always ≤ latency.

When Apache Solr Orbit runs operations at maximum throughput (no `target-throughput` set), or when there is only one operation in flight at a time, latency and service time will be equal — as seen in the example above. The difference becomes visible under load when a schedule produces more requests than the cluster can immediately process.

### Error rate

The error rate is the fraction of operations that returned an error response, expressed as a percentage. An error rate of `0` means every operation succeeded. Any non-zero error rate should be investigated before treating the throughput and latency figures as valid.

## Result files

Results are saved to `~/.solr-orbit/benchmarks/test-runs/` after each run:

```
~/.solr-orbit/benchmarks/test-runs/
└── 20260220_143052_a34ff090/
    ├── test_run.json   ← complete metrics record (JSON)
    ├── results.csv     ← key metrics in CSV format
    └── summary.txt     ← the same table printed to the console
```

The directory name combines the run timestamp and a short unique ID. The `test_run.json` file contains all per-task metrics, workload metadata, cluster configuration, and environment information. See [Summary Report Format](../../reference/summary-report.html) for the full schema.

### Controlling result output

The following flags on the `run` command control how results are stored and displayed:

| Flag | Description |
|------|-------------|
| `--results-file` | Write the summary table to a specific file path in addition to the default location |
| `--results-format` | Output format: `markdown` (default) or `csv` |
| `--show-in-results` | Which values to include: `available` (default), `all-percentiles`, or `all` |
| `--user-tag` | Attach key:value metadata to the run, e.g. `--user-tag "baseline:true,heap:4g"` — useful for filtering results when comparing runs |

## Comparing runs

Use `solr-orbit compare` to diff two runs by their run IDs:

```bash
solr-orbit compare \
  --baseline 20260101_120000_abc12345 \
  --contender 20260220_143052_a34ff090
```

The output shows the delta for each metric, making it easy to spot regressions or improvements between configurations or Solr versions.

See [compare](../../reference/commands/compare.html) for full documentation.
