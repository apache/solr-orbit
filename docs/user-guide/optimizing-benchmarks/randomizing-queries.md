---
title: Randomizing Queries
parent: Optimizing Benchmarks
grand_parent: User Guide
nav_order: 40
---

# Randomizing Queries

By default, a workload runs the same fixed queries on every iteration. This produces unrealistically optimistic latency numbers because Solr's filter cache and query result cache will be warm after the first pass — subsequent identical queries hit the cache and complete much faster than they would in production.

Randomizing queries generates varied parameter values across iterations, so each run exercises a realistic mix of cache hits and misses.

## How it works

Apache Solr Benchmark uses a **Zipf probability distribution** to model realistic cache behavior:

1. At benchmark startup, N value pairs are generated and stored in an indexed list.
2. For each operation, the benchmark probabilistically decides whether to reuse a stored pair (cache hit scenario) or generate a new random pair (cache miss scenario).
3. The **repeat frequency** (`rf`, 0.0–1.0) controls the maximum fraction of queries that reuse stored values.

With the default settings (`rf=0.3`, `N=5000`), 30% of queries reuse stored value pairs (likely cache hits) and 70% generate fresh random values (likely cache misses).

## Implementing randomized queries in a workload

Randomization requires a `workload.py` file in your workload directory. This file registers functions that generate random parameter values.

### Example: randomizing range query parameters

```python
import random

def random_fare_range(max_value):
    gte_cents = random.randrange(0, max_value * 100)
    lte_cents = random.randrange(gte_cents, max_value * 100)
    return {
        "gte": gte_cents / 100,
        "lte": lte_cents / 100,
    }

def fare_range_value_source():
    return random_fare_range(120.00)

def register(registry):
    registry.register_standard_value_source(
        "range",           # query type
        "fare_amount",     # field name
        fare_range_value_source,
    )
```

The `register` function is called once at startup. The `register_standard_value_source` call tells the benchmark: "when running a `range` query on the `fare_amount` field, use this function to generate parameter values."

### Example: randomizing non-range queries

For queries that are not range queries, use `register_query_randomization_info`:

```python
def register(registry):
    registry.register_query_randomization_info(
        "bbox",                # operation name in the workload
        "geo_bounding_box",    # Solr query type
        [["top_left"], ["bottom_right"]],  # parameter variants
        [],                    # optional parameters
    )
```

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--randomization-enabled` | `false` | Activate query randomization |
| `--randomization-repeat-frequency` | `0.3` | Fraction of queries that reuse stored value pairs (0.0–1.0) |
| `--randomization-n` | `5000` | Number of value pairs to generate at startup |
| `--randomization-alpha` | `1.0` | Zipf distribution alpha (≥ 0); higher values skew selection toward lower-indexed pairs |

## Enabling randomization at runtime

```bash
solr-benchmark run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --randomization-enabled true \
  --randomization-repeat-frequency 0.2 \
  --randomization-n 10000
```

## Choosing the right repeat frequency

| rf value | Interpretation |
|----------|---------------|
| `0.0` | Every query is unique — maximum cache miss rate |
| `0.3` | 30% reuse (default) — models typical mixed workloads |
| `1.0` | All queries reuse stored pairs — maximum cache hit rate |

Set `rf` to match your production cache hit ratio if you know it. If you don't know it, the default of `0.3` is a reasonable starting point.

## The Zipf distribution

The probability of selecting value pair *i* from the stored list follows the Zipf distribution: *P(i) ∝ 1/i^α*. This means:

- The first stored pair is selected most frequently
- Frequency drops off sharply for higher-indexed pairs
- `alpha=1.0` (default) gives the standard Zipf distribution
- Higher `alpha` increases the skew (more of the probability mass on the first few pairs)
- `alpha=0.0` makes all stored pairs equally likely

## See also

- [Fine-tuning workloads](../working-with-workloads/finetune-workloads.html)
- [Creating custom workloads](../working-with-workloads/creating-custom-workloads.html)
