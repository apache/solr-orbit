---
title: Anatomy of a Workload
parent: Understanding Workloads
grand_parent: User Guide
nav_order: 15
---

# Anatomy of a workload

A workload is a directory that describes a complete benchmark scenario: which Solr collection
to create, what data to index, and which operations to run. All workload files are processed
as [Jinja2](https://jinja.palletsprojects.com/) templates before being parsed as JSON, which
allows workload authors to parametrize any value and let users override it at run time.

A workload contains the following files and directories:

- [workload.json](#workloadjson) — the main descriptor: collections, corpora, and the default schedule.
- [configsets/](#configsets) — Solr configset directories, each containing `schema.xml` and `solrconfig.xml`.
- [files/](#filestxt) — compressed NDJSON data corpora.
- [operations/](#operations-and-test-procedures) — named operation definitions referenced from schedules.
- [test_procedures/](#operations-and-test-procedures) — named test procedures.

## Workload directory structure

```
my-workload/
├── workload.json                  # Main descriptor
├── operations/
│   └── default.json               # Named operation definitions
├── test_procedures/
│   └── default.json               # Named test procedures
├── files/
│   └── data.json.gz               # Corpus data (gzip-compressed NDJSON)
└── configsets/
    └── my-schema/
        ├── schema.xml
        └── solrconfig.xml
```

## workload.json

The following example shows all the essential elements of a `workload.json` file:

```json
{
  "description": "NYC taxi ride benchmark for Apache Solr",
  "collections": [
    {
      "name": "nyc_taxis",
      "configset-path": "configsets/nyc_taxis",
      "shards": 1,
      "nrt_replicas": 1
    }
  ],
  "corpora": [
    {
      "name": "nyc_taxis",
      "documents": [
        {
          "source-file": "files/data.json.gz",
          "document-count": 165346692,
          "compressed-bytes": 4917851637,
          "uncompressed-bytes": 74818096036
        }
      ]
    }
  ],
  "schedule": [
    {
      "operation": {
        "operation-type": "create-collection",
        "collection": "nyc_taxis"
      }
    },
    {
      "operation": {
        "operation-type": "bulk-index",
        "bulk-size": 5000
      },
      "warmup-time-period": 120,
      "clients": 8
    },
    {
      "operation": {
        "operation-type": "commit",
        "collection": "nyc_taxis"
      }
    },
    {
      "operation": {
        "name": "match-all",
        "operation-type": "search",
        "param-source": "solr-search-source",
        "collection": "nyc_taxis",
        "body": {
          "query": "*:*",
          "rows": 10
        }
      },
      "iterations": 1000,
      "target-throughput": 100
    }
  ]
}
```

A workload always includes the following elements:

- **`collections`** — defines the Solr collection or collections to create before benchmarking.
- **`corpora`** — defines the document datasets to index.
- **`schedule`** — defines the operations and the order in which they run. You can also define
  operations separately using the `operations` key and group them into named test procedures
  using `test-procedures`.

### `collections`

The `collections` element replaces the `indices` concept from OpenSearch Benchmark. Each entry
describes a Solr collection and the configset to use when creating it.

| Field | Type | Description |
| :---- | :---- | :---- |
| `name` | string | The name of the Solr collection. |
| `configset-path` | string | Path to a configset directory, relative to the workload root. The directory must contain at least `schema.xml` and `solrconfig.xml`. |
| `shards` | integer | Number of shards. Default: `1`. |
| `nrt_replicas` | integer | Number of NRT (near-real-time) replicas per shard. Default: `1`. |
| `tlog_replicas` | integer | Number of TLOG replicas per shard. Default: `0`. |
| `pull_replicas` | integer | Number of pull replicas per shard. Default: `0`. |

### `corpora`

The `corpora` element lists the datasets that Solr Benchmark downloads and indexes. Each corpus
entry names the dataset and lists one or more document files.

| Field | Type | Description |
| :---- | :---- | :---- |
| `name` | string | The name of the data corpus, used to match against a collection when indexing. |
| `source-file` | string | The relative path to the data file inside the workload directory. Must be a gzip-compressed NDJSON file (one JSON document per line). |
| `document-count` | integer | The number of documents in the source file. Solr Benchmark uses this to divide the corpus evenly among indexing clients. |
| `uncompressed-bytes` | integer | The decompressed size in bytes. Used to estimate required disk space. |
| `compressed-bytes` | integer | The compressed size in bytes. Used to estimate download time. |

### `schedule`

The `schedule` element lists the operations that run in order during the benchmark. The
following walkthrough describes how the example schedule above executes:

1. **`create-collection`** creates the `nyc_taxis` collection using the configset at
   `configsets/nyc_taxis`. The collection is empty after this step.

2. **`bulk-index`** indexes documents from the corpus into the collection.
   - The `clients` field (set to `8`) specifies how many concurrent indexing clients Solr
     Benchmark runs. Each client receives an equal share of the corpus.
   - The `warmup-time-period` field (set to `120`) tells Solr Benchmark to index for 120 seconds
     before starting to record metrics. Warmup traffic heats up JVM JIT compilation and caches
     so that measurements are not skewed by cold-start effects.
   - The `bulk-size` field (set to `5000`) controls how many documents are sent per HTTP request.

3. **`commit`** issues a hard commit so that all indexed documents become visible to queries.

4. **`search`** runs the `match-all` query repeatedly against the collection.
   - The `iterations` field (set to `1000`) controls how many times each client executes the
     query. To generate precise percentile figures in the summary report, run at least 1,000
     iterations.
   - The `target-throughput` field (set to `100`) defines the number of query requests per second
     across all clients combined. Solr Benchmark throttles requests to stay at this target, which
     keeps service-time measurements independent of scheduling overhead. See
     [Target throughput](../optimizing-benchmarks/target-throughput.html) for details.

### `operations` (optional)

Named operations can be defined in a top-level `"operations"` array and referenced by name
inside `schedule` entries. For complex workloads, operations are typically moved to a separate
`operations/default.json` file and included via a Jinja2 `{% raw %}{% include %}{% endraw %}` statement. This keeps
`workload.json` readable while allowing many operations to be defined and reused.

### `test-procedures` (optional)

Multiple named test procedures can be defined in a `test-procedures` array and
selected at run time with `--test-procedure=<name>`. For details see
[Choosing a workload](choosing-a-workload.html).

---

## Configsets

Instead of an `index.json` mapping file (as used by OpenSearch Benchmark), Solr workloads
provide a **configset** — a directory that Solr Benchmark uploads to the Solr cluster before
creating a collection.

A minimal configset directory contains:

```
configsets/
└── my-schema/
    ├── schema.xml
    └── solrconfig.xml
```

### Minimal `schema.xml`

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<schema name="my-schema" version="1.6">

  <field name="id"       type="string"   indexed="true" stored="true" required="true" multiValued="false"/>
  <field name="_version_" type="plong"   indexed="true" stored="false" docValues="true"/>
  <field name="title"    type="text_general" indexed="true" stored="true"/>

  <uniqueKey>id</uniqueKey>

  <fieldType name="string"       class="solr.StrField"      sortMissingLast="true"/>
  <fieldType name="plong"        class="solr.LongPointField" docValues="true"/>
  <fieldType name="text_general" class="solr.TextField" positionIncrementGap="100">
    <analyzer><tokenizer class="solr.StandardTokenizerFactory"/></analyzer>
  </fieldType>

</schema>
```

The `id` field is required by Solr as the unique key. The `_version_` field is required for
optimistic concurrency control in SolrCloud and must have `indexed="true"` and `docValues="true"`.
{: .important}

### Minimal `solrconfig.xml`

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <luceneMatchVersion>9.0.0</luceneMatchVersion>

  <requestHandler name="/select" class="solr.SearchHandler">
    <lst name="defaults">
      <str name="echoParams">explicit</str>
      <int name="rows">10</int>
    </lst>
  </requestHandler>

  <requestHandler name="/update" class="solr.UpdateRequestHandler"/>

</config>
```

---

## files.txt

When a workload's corpus files are hosted on a remote server, the `files.txt` file lists the
files that belong to the corpus, one per line. Solr Benchmark downloads each listed file from
the configured `base_url` before the benchmark starts.

```
data.json.gz
```

For local workloads (where files already exist on disk), `files.txt` is optional.

---

## operations/ and test_procedures/

To keep `workload.json` readable for large workloads, operations and test procedures are
typically split into separate directories.

### `operations/default.json`

Defines the full set of named operations that test procedures can reference. The following
example shows a realistic set of Solr Benchmark operations from an `nyc_taxis`-style workload:

```json
[
  {
    "name": "index",
    "operation-type": "bulk-index",
    "bulk-size": {% raw %}{{ bulk_size | default(5000) }}{% endraw %}
  },
  {
    "name": "commit",
    "operation-type": "commit",
    "collection": "nyc_taxis"
  },
  {
    "name": "match-all",
    "operation-type": "search",
    "param-source": "solr-search-source",
    "collection": "nyc_taxis",
    "body": {
      "query": "*:*",
      "rows": 10
    }
  },
  {
    "name": "range",
    "operation-type": "search",
    "param-source": "solr-search-source",
    "collection": "nyc_taxis",
    "body": {
      "query": "total_amount:[5 TO 15}",
      "rows": 10
    }
  },
  {
    "name": "asc-sort-passenger-count",
    "operation-type": "search",
    "param-source": "solr-search-source",
    "collection": "nyc_taxis",
    "body": {
      "query": "*:*",
      "sort": "passenger_count asc",
      "rows": 10
    }
  },
  {
    "name": "passenger-count-agg",
    "operation-type": "search",
    "param-source": "solr-search-source",
    "collection": "nyc_taxis",
    "body": {
      "query": "*:*",
      "rows": 0,
      "facet": {
        "passengers": {
          "type": "terms",
          "field": "passenger_count",
          "limit": 10
        }
      }
    }
  }
]
```

### `test_procedures/default.json`

Defines the order in which operations run. A test procedure is a named sequence of operations
with its own schedule. The following example shows a default test procedure for the `nyc_taxis` workload:

```json
[
  {
    "name": "append-no-conflicts",
    "description": "Index all documents, then run a set of search queries.",
    "schedule": [
      {
        "operation": "delete-collection"
      },
      {
        "operation": "create-collection"
      },
      {
        "operation": "index",
        "warmup-time-period": {% raw %}{{ warmup_time_period | default(240) }}{% endraw %},
        "clients": {% raw %}{{ bulk_indexing_clients | default(8) }}{% endraw %}
      },
      {
        "operation": "commit"
      },
      {
        "operation": "match-all",
        "warmup-iterations": 50,
        "iterations": 500,
        "target-throughput": {% raw %}{{ target_throughput | default(20) }}{% endraw %}
      },
      {
        "operation": "range",
        "warmup-iterations": 50,
        "iterations": 200,
        "target-throughput": {% raw %}{{ target_throughput | default(10) }}{% endraw %}
      },
      {
        "operation": "passenger-count-agg",
        "warmup-iterations": 50,
        "iterations": 200,
        "target-throughput": {% raw %}{{ target_throughput | default(5) }}{% endraw %}
      }
    ]
  }
]
```

---

## Jinja2 templating

All workload files are rendered as [Jinja2](https://jinja.palletsprojects.com/) templates
before being parsed as JSON. This lets workload authors expose tunable parameters with default
values:

```json
{
  "operation-type": "bulk-index",
  "bulk-size": {% raw %}{{ bulk_size | default(5000) }}{% endraw %}
}
```

Override any parameter at run time with the `--workload-params` flag:

```bash
solr-benchmark run \
  --workload=nyc_taxis \
  --pipeline=benchmark-only \
  --workload-params="bulk_size:10000,bulk_indexing_clients:4"
```

Multiple parameters are separated by commas. Parameter values can be integers, floats,
booleans, or strings.

The `default()` Jinja2 filter sets the value used when no override is provided. To make a
parameter mandatory (no default), omit the filter — Solr Benchmark raises a clear error if
the parameter is missing.
{: .tip}

---

## Next steps

- [Choosing a workload](choosing-a-workload.html) — browse the available workloads and select
  one that matches your use case.
- [Creating custom workloads](../working-with-workloads/creating-custom-workloads.html) — write
  your own workload from scratch.
