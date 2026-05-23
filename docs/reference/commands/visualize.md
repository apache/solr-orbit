---
title: visualize
parent: Command Reference
grand_parent: Reference
nav_order: 140
---

# visualize

Generates an interactive HTML visualization for a completed benchmark run. The output file can be opened in any web browser to explore metric trends, throughput charts, and latency distributions.

## Syntax

```bash
solr-orbit visualize --test-run-id ID [OPTIONS]
```

## Options

| Option | Short | Required | Default | Description |
|--------|-------|----------|---------|-------------|
| `--test-run-id` | `-tid` | Yes | — | ID of the completed test run to visualize (see `solr-orbit list test-runs`) |
| `--output-path` | | No | Test run directory | Path where the HTML report should be saved. Defaults to the run's own directory alongside `test_run.json` |

## Example

```bash
# List available runs to find the ID
solr-orbit list test-runs

# Generate a visualization
solr-orbit visualize --test-run-id 20240115T120000Z

# Save to a specific location
solr-orbit visualize \
  --test-run-id 20240115T120000Z \
  --output-path /reports/run-20240115.html
```

## Inline visualization during a run

You can also generate a visualization automatically at the end of a benchmark run using the `--visualize` and `--visualize-output-path` flags on the [`run`](run.html) command:

```bash
solr-orbit run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --visualize \
  --visualize-output-path /reports/latest.html
```

## See also

- [run](run.html)
- [list](list.html)
