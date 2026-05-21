---
title: test-procedures
parent: Workload Reference
grand_parent: Reference
nav_order: 110
---

# test-procedures

Test procedures define named benchmark scenarios within a workload. A workload typically defines one or more test procedures, each specifying a schedule of operations.

## Syntax

```json
{
  "test-procedures": [
    {
      "name": "append-no-conflicts",
      "description": "Index all documents then run searches",
      "default": true,
      "schedule": [
        {
          "operation": "bulk-index",
          "warmup-time-period": 120,
          "clients": 8
        },
        { "operation": "commit" },
        {
          "operation": "search",
          "clients": 1,
          "iterations": 200,
          "target-throughput": 10
        }
      ]
    }
  ]
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Test procedure name, referenced with `--test-procedure` at run time |
| `description` | string | No | Human-readable description |
| `default` | boolean | No | If `true`, this test procedure is used when `--test-procedure` is not specified |
| `schedule` | array | Yes | Sequence of schedule items (operations with execution parameters) |

## Schedule item fields

| Field | Type | Description |
|-------|------|-------------|
| `operation` | string or object | Operation name (string reference) or inline operation definition (object) |
| `clients` | integer | Number of parallel clients |
| `iterations` | integer | Number of times to run the operation |
| `warmup-iterations` | integer | Iterations to discard before recording metrics |
| `warmup-time-period` | integer | Seconds to warm up before recording metrics |
| `target-throughput` | number | Target operations per second (throttle if faster) |
| `time-period` | integer | Fixed duration in seconds (alternative to `iterations`) |

## Selecting a test procedure at run time

```bash
solr-benchmark run \
  --pipeline benchmark-only \
  --target-hosts localhost:8983 \
  --workload my-workload \
  --test-procedure append-no-conflicts
```

## Listing available test procedures

```bash
solr-benchmark info --workload my-workload
```
