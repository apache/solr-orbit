---
title: collections
parent: Workload Reference
grand_parent: Reference
nav_order: 65
---

# collections

The `"collections"` array in `workload.json` defines the Solr collections to create before the benchmark starts.

## Syntax

```json
{
  "collections": [
    {
      "name": "<collection-name>",
      "configset-path": "<path>",
      "num-shards": 1,
      "replication-factor": 1,
      "tlog-replicas": 0,
      "pull-replicas": 0
    }
  ]
}
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | The collection name. Must be a valid Solr collection name. |
| `configset-path` | string | No | — | Path relative to the workload directory pointing to a configset directory. If provided, the configset is uploaded to Solr/ZooKeeper before the collection is created. If omitted, the configset named by `configset` (or the collection name) must already exist on the server. |
| `num-shards` | integer | No | `1` | Number of shards for the collection. |
| `replication-factor` | integer | No | `1` | Number of NRT (near-real-time) replicas per shard. NRT replicas participate in leader elections. |
| `tlog-replicas` | integer | No | `0` | Number of TLOG replicas per shard. TLOG replicas buffer updates in a transaction log. |
| `pull-replicas` | integer | No | `0` | Number of Pull replicas per shard. Pull replicas are read-only and receive index segments from the leader. |

## Example

```json
{
  "collections": [
    {
      "name": "nyc_taxis",
      "configset-path": "configsets/nyc_taxis",
      "num-shards": 2,
      "replication-factor": 1,
      "tlog-replicas": 1,
      "pull-replicas": 0
    }
  ]
}
```

## Notes

- When `configset-path` is provided, the directory must contain at minimum `schema.xml` and `solrconfig.xml`.
- For SolrCloud, the configset is uploaded to ZooKeeper before the collection is created.
- If the collection already exists when the benchmark starts, it is deleted and recreated so that benchmarks are repeatable.
- See the [Apache Solr Reference Guide: Collections API](https://solr.apache.org/guide/solr/latest/deployment-guide/collections-api.html) for background.
