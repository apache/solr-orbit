---
title: corpora
parent: Workload Reference
grand_parent: Reference
nav_order: 70
---

# corpora

The `"corpora"` array defines the datasets to index. Each corpus references one or more document files.

## Syntax

```json
{
  "corpora": [
    {
      "name": "<corpus-name>",
      "documents": [
        {
          "source-file": "<file>",
          "document-count": <n>,
          "compressed-bytes": <bytes>,
          "uncompressed-bytes": <bytes>,
          "target-collection": "<collection-name>"
        }
      ]
    }
  ]
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Corpus name, referenced from `bulk-index` operations. |
| `documents` | array | Yes | List of document file descriptors. |
| `source-file` | string | Yes | Path (relative to workload dir) to the compressed NDJSON data file. |
| `document-count` | integer | Yes | Number of documents in the file (used for progress display and `--test-mode` limits). |
| `compressed-bytes` | integer | No | Compressed file size in bytes (for download progress display). |
| `uncompressed-bytes` | integer | No | Uncompressed file size in bytes. |
| `target-collection` | string | No | Target collection name. Defaults to the workload's primary collection. |

## Data file format

Documents must be in gzip-compressed NDJSON (Newline-Delimited JSON) format. Each line is one JSON document. Each document should include an `id` field matching the unique key field in your Solr schema:

```json
{"id": "1", "title": "My document", "timestamp": "2024-01-01T00:00:00Z"}
{"id": "2", "title": "Another document", "timestamp": "2024-01-02T00:00:00Z"}
```

## Example

```json
{
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
  ]
}
```
