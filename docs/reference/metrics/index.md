---
title: Metrics Reference
parent: Reference
nav_order: 60
has_children: true
---

# Metrics

Apache Solr Benchmark stores all metrics collected during a benchmark run so that they can be
analyzed and compared across runs. This page describes the available storage options.

## Storing metrics

Metrics can be stored in two ways depending on your analysis requirements.

### In memory (default)

The default configuration keeps all metric records in RAM for the duration of the run.
Results are computed from this in-memory state and written to `test_run.json` when the run
completes. The raw individual samples are not persisted beyond the process lifetime, which
keeps disk usage minimal and avoids per-sample write overhead.

No configuration is required to use in-memory storage — it is the default. You can also
set it explicitly in `~/.solr-benchmark/benchmark.ini`:

```ini
[reporting]
datastore.type = in-memory
```

### Filesystem (opt-in)

The filesystem metrics store keeps all metric records in RAM (exactly like the in-memory
store) **and** also streams every raw metric document to a `metrics.jsonl` file on disk as
it arrives. This makes individual samples available for offline analysis even after the
benchmark process exits, at the cost of additional disk I/O during the run.

To opt in, add the following to `~/.solr-benchmark/benchmark.ini`:

```ini
[reporting]
datastore.type = filesystem
```

Files are written to:

```
~/.solr-benchmark/
└── benchmarks/
    └── test-runs/
        └── <run-id>/
            ├── test_run.json   # computed results (percentiles, error rates, …)
            └── metrics.jsonl   # raw metric documents, one JSON object per line
```

See [Filesystem Metrics Store](filesystem-metrics-store.html) for full configuration and
file layout details, including `jq` and Python examples for inspecting raw samples.

## Next steps

- [Filesystem Metrics Store](filesystem-metrics-store.html) — store configuration and file layout
- [Metric Records](metric-records.html) — structure of individual metric documents
- [Metric Keys](metrics-reference.html) — catalog of every metric key Solr Benchmark can record
