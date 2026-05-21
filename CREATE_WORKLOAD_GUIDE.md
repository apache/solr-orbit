# Create Workload Guide

This guide explains how to create a Solr Benchmark workload.

## Option 1: Write a workload from scratch

A workload is a JSON file with the following structure:

```json
{
  "name": "my-workload",
  "description": "Benchmark description",
  "collections": [
    {
      "name": "my-collection",
      "configset": "my-configset",
      "configset-path": "/path/to/configset/dir",
      "num-shards": 1,
      "replication-factor": 1
    }
  ],
  "challenges": [
    {
      "name": "default",
      "description": "Default challenge",
      "schedule": [
        {"operation": {"operation-type": "delete-collection", "ignore-missing": true}},
        {"operation": {"operation-type": "create-collection"}},
        {"operation": {"operation-type": "bulk-index", "bulk-size": 500}},
        {"operation": {"operation-type": "search", "q": "*:*", "rows": 10}},
        {"operation": {"operation-type": "optimize"}},
        {"operation": {"operation-type": "delete-collection"}}
      ]
    }
  ]
}
```

Run the workload with:

```bash
solr-benchmark run \
  --pipeline=benchmark-only \
  --workload-path=/path/to/workload.json \
  --target-host="localhost:8983"
```

## Option 2: Migrate an existing OSB workload

If you have a workload written for OpenSearch Benchmark, use the migration
utility to translate it to Solr format:

```bash
python -m osbenchmark.tools.migrate_workload \
  --input osb-workload.json \
  --output solr-workload.json
```

The tool will:
- Rename `indices` → `collections`
- Translate `bulk` → `bulk-index`, `force-merge` → `optimize`,
  `create-index` → `create-collection`, `delete-index` → `delete-collection`
- Rename the `index` operation parameter → `collection`
- Mark unsupported operations with a `_migration_todo` note — **no operation
  is ever silently dropped**

Review the output file and resolve any `_migration_todo` items before running.

## Supported operation types

| Operation type | Description |
|---|---|
| `bulk-index` | Index documents from an NDJSON corpus |
| `search` | Run a Solr query (classic params or JSON DSL `body`) |
| `commit` | Issue a hard or soft commit |
| `optimize` | Merge segments |
| `create-collection` | Upload configset then create collection |
| `delete-collection` | Delete collection (and optionally its configset) |
| `raw-request` | Issue an arbitrary Solr V2 API request |

## Corpus format

Document corpora use NDJSON (newline-delimited JSON), with alternating action
and document lines — the same format as OpenSearch/Elasticsearch bulk API:

```
{"index": {"_id": "1", "_index": "my-collection"}}
{"title": "Hello world", "body": "..."}
{"index": {"_id": "2"}}
{"title": "Second doc", "body": "..."}
```

The `_id` field is mapped to Solr's `id` field. `_index` and `_type` are used
for routing/logging only and are not stored in the document.

## Custom queries

For search operations using Solr's JSON Query DSL, pass a `body` dict:

```json
{
  "operation-type": "search",
  "body": {
    "query": {"field": {"title": "hello"}},
    "limit": 10
  }
}
```

For classic Solr query syntax, use `q`, `fl`, `rows`, `fq`, and `sort`
parameters directly:

```json
{
  "operation-type": "search",
  "q": "title:hello",
  "rows": 10,
  "fl": "id,title,score"
}
```
