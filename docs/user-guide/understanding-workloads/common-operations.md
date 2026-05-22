---
title: Common Operations
parent: Understanding Workloads
grand_parent: User Guide
nav_order: 16
---

# Common Operations

Apache Solr Orbit provides the following built-in operation types.

## bulk-index

Indexes documents from a corpus into a Solr collection in batches.

```json
{
  "name": "bulk-index",
  "operation-type": "bulk-index",
  "bulk-size": 500,
  "collection": "nyc_taxis"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bulk-size` | `500` | Number of documents per batch |
| `collection` | (first collection in workload) | Target collection |

## search

Executes a Solr query and measures latency and throughput.

```json
{
  "name": "match-all",
  "operation-type": "search",
  "body": {
    "query": "*:*",
    "rows": 10,
    "fl": "id"
  }
}
```

For Solr JSON DSL queries using structured query syntax:

```json
{
  "name": "range-query",
  "operation-type": "search",
  "body": {
    "query": {
      "range": "pickup_datetime:[2015-01-01T00:00:00Z TO 2015-02-01T00:00:00Z]"
    }
  }
}
```

The `body` is passed directly as the Solr JSON query body. Use standard [Solr JSON Request API](https://solr.apache.org/guide/solr/latest/query-guide/json-request-api.html) syntax.

## commit

Issues a hard commit to flush all pending documents.

```json
{
  "name": "commit",
  "operation-type": "commit"
}
```

To issue a soft commit instead:

```json
{
  "name": "soft-commit",
  "operation-type": "commit",
  "soft-commit": true
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `soft-commit` | `false` | If `true`, issues a soft commit instead of a hard commit |

## optimize

Issues an optimize (force-merge) command to reduce the number of index segments.

```json
{
  "name": "optimize",
  "operation-type": "optimize",
  "max-segments": 1
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max-segments` | `1` | Target segment count after optimization |

## wait-for-merges

Polls the Solr node metrics API until all background merge operations have completed.

```json
{
  "name": "wait-for-merges",
  "operation-type": "wait-for-merges"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `retry-wait-period` | `2.0` | Seconds between polling attempts |
| `max-wait-seconds` | `3600` | Maximum seconds to wait |

## paginated-search

Executes a cursor-paginated Solr search using `cursorMark` deep pagination. Fetches all result pages and returns the total document count.

```json
{
  "name": "paginated-search",
  "operation-type": "paginated-search",
  "q": "*:*",
  "rows": 100,
  "sort": "id asc"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `q` | `*:*` | Query string |
| `rows` | `100` | Page size (documents per request) |
| `sort` | `id asc` | Sort order — must include a uniqueKey field |
| `fl` | (none) | Field list |
| `fq` | (none) | Filter query |

## create-collection

Creates a Solr collection.

```json
{
  "name": "create-collection",
  "operation-type": "create-collection",
  "collection": "my_collection",
  "configset-path": "configsets/my_schema",
  "num-shards": 1,
  "replication-factor": 1
}
```

## delete-collection

Deletes a Solr collection.

```json
{
  "name": "delete-collection",
  "operation-type": "delete-collection",
  "collection": "my_collection"
}
```

## raw-request

Executes a raw HTTP request against the Solr Admin API. Useful for custom operations not covered by built-in types.

```json
{
  "name": "my-custom-op",
  "operation-type": "raw-request",
  "path": "/api/collections/my_collection/config",
  "method": "POST",
  "body": {
    "set-property": {
      "updateHandler.autoSoftCommit.maxTime": "5000"
    }
  }
}
```
