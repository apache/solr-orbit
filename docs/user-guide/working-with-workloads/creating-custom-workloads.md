---
title: Creating Custom Workloads
parent: Working with Workloads
grand_parent: User Guide
nav_order: 10
---

# Creating Custom Workloads

To create a workload tailored for your Solr data and queries, create a directory with the
structure described in [Anatomy of a Workload](../understanding-workloads/anatomy-of-a-workload.html).

## Minimal workload example

```
my-benchmark/
├── workload.json
├── configsets/
│   └── my_schema/
│       ├── schema.xml
│       └── solrconfig.xml
└── files/
    └── my_data.json.gz
```

**workload.json:**

```json
{
  "description": "My custom Solr benchmark",
  "collections": [
    {
      "name": "my_collection",
      "configset-path": "configsets/my_schema",
      "shards": 1,
      "nrt_replicas": 1
    }
  ],
  "corpora": [
    {
      "name": "my_data",
      "documents": [
        {
          "source-file": "files/my_data.json.gz",
          "document-count": 100000,
          "compressed-bytes": 50000000,
          "uncompressed-bytes": 200000000
        }
      ]
    }
  ],
  "schedule": [
    {
      "operation": {
        "operation-type": "bulk-index",
        "bulk-size": 500
      },
      "warmup-time-period": 60,
      "clients": 4
    },
    { "operation": "commit" },
    {
      "operation": {
        "name": "my-search",
        "operation-type": "search",
        "body": { "query": "*:*", "rows": 10 }
      },
      "clients": 1,
      "iterations": 100
    }
  ]
}
```

---

## Invoking your custom workload

Point Solr Benchmark at the workload directory with `--workload-path`:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path /path/to/my-benchmark
```

Use `--test-mode` to do a quick validation pass before running the full workload:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path /path/to/my-benchmark \
  --test-mode
```

---

## Preparing corpus data

Corpus data must be in gzip-compressed NDJSON (Newline-Delimited JSON) format, where each
line is a JSON document to index. Documents should include an `id` field matching your
Solr schema's unique key field.

```json
{"id": "1", "title": "My document", "timestamp": "2024-01-01T00:00:00Z"}
{"id": "2", "title": "Another document", "timestamp": "2024-01-02T00:00:00Z"}
```

Compress the file:

```bash
gzip my_data.json
```

---

## Test mode support

`--test-mode` reads only the first 1,000 documents instead of the full corpus. To support
it, create a companion `-1k` file alongside the main corpus:

```bash
# Create a 1,000-document companion file
zcat files/my_data.json.gz | head -n 1000 | gzip > files/my_data-1k.json.gz
```

Solr Benchmark automatically uses the `-1k` variant when `--test-mode` is passed — no
changes to `workload.json` are required. The `document-count` in the corpus definition
should reflect the **full** dataset; Solr Benchmark adjusts internally for test mode.

Test mode is not a substitute for a full run. Always verify results against the complete
corpus before drawing conclusions.
{: .note}

---

## Defining a configset

A configset directory must contain at minimum:
- `schema.xml` — field definitions and types
- `solrconfig.xml` — request handler and cache configuration

See the [Apache Solr Reference Guide: Configsets](https://solr.apache.org/guide/solr/latest/configuration-guide/configsets.html) for full documentation.

---

## Using Jinja2 parameters

Workload files are Jinja2 templates. Add parameters to allow runtime overrides:

{% raw %}
```json
{
  "operation-type": "bulk-index",
  "bulk-size": {{ bulk_size | default(500) }},
  "clients": {{ index_clients | default(4) }}
}
```
{% endraw %}

Then override at runtime:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path my-benchmark \
  --workload-params "bulk_size:1000,index_clients:8"
```

---

## Adding multiple test procedures

Replace the top-level `schedule` with a `test-procedures` array to define named test
procedures that can be selected at run time with `--test-procedure`:

```json
{
  "description": "My custom benchmark",
  "collections": [ ... ],
  "corpora": [ ... ],
  "test-procedures": [
    {
      "name": "index-only",
      "description": "Index all documents without running any queries.",
      "default": false,
      "schedule": [
        { "operation": { "operation-type": "bulk-index", "bulk-size": 5000 }, "clients": 8 },
        { "operation": "commit" }
      ]
    },
    {
      "name": "index-and-query",
      "description": "Index all documents then run a set of search queries.",
      "default": true,
      "schedule": [
        { "operation": { "operation-type": "bulk-index", "bulk-size": 5000 }, "clients": 8 },
        { "operation": "commit" },
        {
          "operation": {
            "name": "match-all",
            "operation-type": "search",
            "body": { "query": "*:*", "rows": 10 }
          },
          "iterations": 1000,
          "target-throughput": 50
        }
      ]
    }
  ]
}
```

Run a specific test procedure:

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload-path my-benchmark \
  --test-procedure index-only
```

The test procedure marked `"default": true` is used when `--test-procedure` is not
specified.

---

## Separating operations and test procedures

For large workloads, split operations and test procedures into separate files and reference
them from `workload.json` using the `benchmark.collect()` Jinja2 macro:

{% raw %}
```json
{
  "description": "My custom benchmark",
  "collections": [ ... ],
  "corpora": [ ... ],
  "operations": [
    {{ benchmark.collect(parts="operations/*.json") }}
  ],
  "test-procedures": [
    {{ benchmark.collect(parts="test_procedures/*.json") }}
  ]
}
```
{% endraw %}

The macro reads every `.json` file in the specified directory and inlines its contents.
Directory layout:

```
my-benchmark/
├── workload.json
├── operations/
│   ├── indexing.json         # bulk-index, commit operations
│   └── search.json           # match-all, range, aggregation operations
└── test_procedures/
    └── default.json          # append-no-conflicts test procedure
```

This pattern keeps `workload.json` readable regardless of how many operations the workload
defines.

---

## Splitting operations into separate files (simple include)

For simpler workloads where you only need one operations file and one test-procedures file,
use a Jinja2 {% raw %}`{% include %}`{% endraw %} statement:

{% raw %}
```json
{
  "operations": [
    {% include "operations/default.json" %}
  ],
  "test-procedures": [
    {% include "test_procedures/default.json" %}
  ]
}
```
{% endraw %}
