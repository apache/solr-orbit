---
title: operations
parent: Workload Reference
grand_parent: Reference
nav_order: 100
---

# operations

Operations define the actions performed during a test procedure. They are referenced from test procedure schedules.

## Syntax

Operations can be defined inline in a schedule or in a top-level `"operations"` section:

```json
{
  "operations": [
    {
      "name": "my-search",
      "operation-type": "search",
      "body": {
        "query": "*:*",
        "rows": 10
      }
    }
  ]
}
```

## Built-in operation types

### bulk-index

```json
{
  "operation-type": "bulk-index",
  "bulk-size": 500,
  "collection": "my_collection"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bulk-size` | `500` | Number of documents per batch |
| `collection` | (first collection in workload) | Target collection |
| `corpora` | (all corpora) | Corpus name to index from |
| `commit` | `false` | If `true`, issue a hard commit to Solr after each batch |

### search

The `search` operation supports two styles.

**JSON body style** — passes a full Solr JSON Request API object:

```json
{
  "operation-type": "search",
  "body": {
    "query": "*:*",
    "rows": 10,
    "fl": "id,title"
  },
  "collection": "my_collection"
}
```

**Classic params style** — individual Solr query parameters as top-level fields:

```json
{
  "operation-type": "search",
  "q": "city:New York",
  "fl": "id,name",
  "rows": 10,
  "fq": "type:restaurant",
  "sort": "score desc",
  "request-params": {
    "defType": "edismax"
  },
  "collection": "my_collection"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `body` | (none) | Full Solr JSON query body ([JSON Request API](https://solr.apache.org/guide/solr/latest/query-guide/json-request-api.html) format). Takes precedence over classic params if both are present |
| `q` | `*:*` | Query string (classic params style) |
| `fl` | (none) | Field list to return |
| `rows` | (none) | Number of documents to return |
| `fq` | (none) | Filter query |
| `sort` | (none) | Sort order |
| `request-params` | `{}` | Additional Solr query parameters appended to the request |
| `collection` | (first collection in workload) | Target collection |

### commit

```json
{ "operation-type": "commit" }
```

Issues a hard commit to Solr. Also registered as `refresh`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `collection` | (first collection in workload) | Target collection |
| `soft-commit` | `false` | If `true`, issues a soft commit instead of a hard commit |

### optimize

```json
{ "operation-type": "optimize", "max-segments": 1 }
```

Issues a force-merge (optimize) to reduce the segment count to `max-segments` (default: 1).

### wait-for-merges

```json
{ "operation-type": "wait-for-merges" }
```

Polls the Solr node metrics API until no active merge operations remain across any core, or the timeout is reached.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `collection` | (first collection in workload) | Target collection |
| `retry-wait-period` | `2.0` | Seconds between polling attempts |
| `max-wait-seconds` | `3600` | Maximum seconds to wait before giving up |

### paginated-search

```json
{
  "operation-type": "paginated-search",
  "q": "my query",
  "rows": 100,
  "sort": "id asc"
}
```

Executes a cursor-paginated Solr search using Solr's `cursorMark` deep pagination API. Fetches all result pages and returns the total document count. Also registered as `scroll-search`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `collection` | (first collection in workload) | Target collection |
| `q` | `*:*` | Query string |
| `rows` | `100` | Page size (documents per request) |
| `sort` | `id asc` | Sort order — must include a uniqueKey field for cursor pagination to work |
| `fl` | (none) | Field list to return |
| `fq` | (none) | Filter query |
| `request-params` | `{}` | Additional Solr query parameters |

### create-collection

```json
{
  "operation-type": "create-collection",
  "collection": "my_collection",
  "configset-path": "configsets/my_schema",
  "num-shards": 1,
  "replication-factor": 1
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `collection` | (required) | Collection name |
| `configset` | (collection name) | Configset name to use; defaults to the collection name |
| `configset-path` | (none) | Path to local configset directory (relative to workload dir) |
| `num-shards` | `1` | Number of shards |
| `replication-factor` | `1` | Number of NRT replicas per shard |
| `tlog-replicas` | `0` | Number of TLOG replicas per shard |
| `pull-replicas` | `0` | Number of pull replicas per shard |
| `delete-configset-on-error` | `true` | Delete uploaded configset if collection creation fails |

### delete-collection

```json
{
  "operation-type": "delete-collection",
  "collection": "my_collection"
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `collection` | (required) | Collection name to delete |
| `configset` | (collection name) | Configset name to delete alongside the collection |
| `delete-configset` | `true` | If `true`, also deletes the associated configset |
| `ignore-missing` | `true` | If `true`, silently succeeds if the collection does not exist |

### raw-request

```json
{
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

Executes an arbitrary HTTP request against the Solr Admin API (`/api/...` V2 endpoints).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `path` | (required) | API path, e.g. `/api/collections/my_coll/config` |
| `method` | `GET` | HTTP method: `GET`, `POST`, `DELETE` |
| `body` | (none) | Request body (JSON object) |
| `headers` | `{}` | Additional HTTP headers |

### sleep

```json
{ "operation-type": "sleep", "duration": 5 }
```

Pauses the schedule for the specified number of seconds. Useful between tasks that need a settling period (for example, after a commit before running queries).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `duration` | (required) | Seconds to sleep |

### composite

```json
{
  "operation-type": "composite",
  "operations": [
    { "operation-type": "bulk-index", "bulk-size": 500 },
    { "operation-type": "commit" }
  ]
}
```

Groups multiple operations into a single logical unit. Operations within the composite execute sequentially; the composite completes when all child operations finish. Useful for measuring end-to-end latency of a multi-step sequence.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `operations` | (required) | Array of operation definitions to execute in sequence |

### retry wrapper

Any operation can be wrapped with retry logic by adding retry parameters directly to the operation definition:

```json
{
  "operation-type": "bulk-index",
  "bulk-size": 500,
  "retries": 3,
  "retry-wait-period": 0.5,
  "retry-on-timeout": true,
  "retry-on-error": true
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `retries` | `0` | Number of times to retry on failure |
| `retry-until-success` | `false` | If `true`, retry indefinitely until the operation succeeds |
| `retry-wait-period` | `0.5` | Seconds to wait between retry attempts |
| `retry-on-timeout` | `true` | Retry when a timeout error occurs |
| `retry-on-error` | `false` | Retry when any other error occurs |

## Backup operations

The following backup-related operation types are registered but not yet implemented in this release:
`create-backup`, `restore-backup`, `create-backup-repository`, `delete-backup-repository`, `wait-for-backup-create`.
Use `raw-request` to call the [Solr Backup V2 API](https://solr.apache.org/guide/solr/latest/configuration-guide/backups.html) directly.
