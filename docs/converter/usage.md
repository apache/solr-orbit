---
title: Usage
parent: Converter Tool
nav_order: 2
---

# Using the Converter

## Basic usage

```bash
solr-benchmark convert-workload \
  --workload-path /path/to/osb-workload \
  --output-path /path/to/solr-workload
```

## Options

| Option | Description |
|--------|-------------|
| `--workload-path` | Path to the source OpenSearch Benchmark workload directory |
| `--output-path` | Destination directory for the converted workload |
| `--force` | Overwrite the output directory if it already exists |

## Output

The converter produces a copy of the workload in the output directory with the following changes applied:

- `"indices"` keys renamed to `"collections"` in `workload.json`
- `create-index` / `delete-index` operation types replaced with `create-collection` / `delete-collection`
- OpenSearch JSON DSL search bodies translated to Solr JSON query format
- Date range filters converted from custom formats (e.g., `dd/MM/yyyy`) to ISO 8601
- Aggregations translated to Solr facet syntax

A `CONVERTED.md` file is written to the output directory summarizing what was converted and flagging any items that require manual review.

## Example output

```
Converted workload saved to: /path/to/solr-workload

Summary:
  - workload.json: renamed 2 "indices" key(s) to "collections"
  - operations/default.json: translated 5 search bodies
  - operations/default.json: converted 3 date range filters
  - operations/default.json: translated 4 aggregations to facets

Items requiring manual review (see CONVERTED.md):
  - 1 script_score query (not auto-translated)
  - 2 complex nested aggregations
```

## Idempotent re-runs

If the output directory already contains a `CONVERTED.md` file, the converter will skip it unless `--force` is passed. This makes re-runs safe after partial edits:

```bash
# Re-run without losing manual edits
solr-benchmark convert-workload \
  --workload-path /path/to/osb-workload \
  --output-path /path/to/solr-workload \
  --force
```

{: .warning }
> Using `--force` overwrites all files in the output directory, including any manual edits you have made.
