---
title: aggregate
parent: Command Reference
grand_parent: Reference
nav_order: 10
---

# aggregate

Combines results from multiple benchmark runs into a single aggregated result. This is useful when you want statistical confidence in your benchmark numbers — running a workload three or more times and aggregating the results reduces the influence of any single outlier run.

## Two modes of aggregation

### Automatic aggregation (via `run`)

Pass `--test-iterations` and `--aggregate` directly to the `run` command to execute the workload multiple times and aggregate automatically:

```bash
solr-orbit run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --test-iterations 3 \
  --aggregate true \
  --sleep-timer 30
```

| Flag | Description | Default |
|------|-------------|---------|
| `--test-iterations` | Number of times to run the workload | `1` |
| `--aggregate` | Aggregate results after all iterations | `true` |
| `--sleep-timer` | Seconds to wait between runs | `5` |
| `--cancel-on-error` | Stop all remaining iterations on first error | `false` |

### Manual aggregation

Run benchmarks separately, then combine specific runs by their test run IDs:

```bash
# First, list recent test runs to get IDs
solr-orbit list test-runs

# Then aggregate the runs you want
solr-orbit aggregate \
  --test-runs 20260101T120000Z,20260102T120000Z,20260103T120000Z
```

## Syntax

```bash
solr-orbit aggregate --test-runs ID1,ID2[,...] [OPTIONS]
```

## Options

| Option | Description |
|--------|-------------|
| `--test-runs` | Comma-separated list of test run IDs to aggregate |
| `--test-runs-id` | Custom ID for the aggregated result (auto-generated if omitted) |
| `--results-file` | Path to write the aggregated results JSON |

## Output

The aggregated result includes additional statistical fields compared to a single run:

```json
{
  "task": "index",
  "throughput": {
    "overall_min": 3820.5,
    "mean": 4105.3,
    "median": 4098.7,
    "overall_max": 4390.1,
    "unit": "docs/s",
    "mean_rsd": 3.8
  }
}
```

| Field | Description |
|-------|-------------|
| `overall_min` | True minimum value across all runs |
| `mean` | Arithmetic mean across all runs |
| `median` | Median value across all runs |
| `overall_max` | True maximum value across all runs |
| `mean_rsd` | Mean relative standard deviation (%) — lower is better; indicates how consistent the runs were |

Aggregated results are saved to `~/.solr-orbit/benchmarks/aggregated_results/<aggregated-id>/`.

## See also

- [compare](compare.html) — compare two individual runs
- [list](list.html) — list test runs and their IDs
- [Understanding Results](../../user-guide/understanding-results/)
