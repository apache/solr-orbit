---
title: compare
parent: Command Reference
grand_parent: Reference
nav_order: 20
---

# compare

Compares results from two benchmark runs.

## Syntax

```bash
solr-orbit compare --baseline BASELINE_ID --contender CONTENDER_ID
```

## Options

| Option | Description |
|--------|-------------|
| `--baseline` | Test execution ID of the baseline run |
| `--contender` | Test execution ID of the contender run |
| `--percentiles` | Comma-separated list of latency percentiles to report (e.g., `50,90,99,99.9`) |
| `--results-format` | Output format: `markdown` (default) or `csv` |
| `--results-numbers-align` | Column alignment in the output table: `right` (default), `left`, `center`, or `decimal` |
| `--results-file` | Write the comparison table to a file in addition to console output |
| `--show-in-results` | Which values to include: `available` (default), `all-percentiles`, or `all` |

## Example

```bash
solr-orbit compare \
  --baseline 20240101T120000Z \
  --contender 20240115T120000Z
```

The output shows the delta between baseline and contender for each metric:

```
| Metric               | Baseline | Contender | Diff   |
|----------------------|----------|-----------|--------|
| bulk-index (50th ms) | 14.2     | 12.3      | -13.4% |
| bulk-index (docs/s)  | 4200     | 4500      | +7.1%  |
| search (50th ms)     | 6.1      | 5.1       | -16.4% |
| search (ops/s)       | 105      | 120       | +14.3% |
```

Negative differences in latency and positive differences in throughput indicate improvement.
