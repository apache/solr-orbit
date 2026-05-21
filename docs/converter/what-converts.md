---
title: What Gets Converted
parent: Converter Tool
nav_order: 3
---

# What Gets Converted

The table below summarizes which OpenSearch Benchmark constructs are automatically converted, which require manual review, and which are skipped with a TODO comment.

## Automatically converted

| Construct | Conversion |
|-----------|------------|
| `"indices"` key in workload.json | Renamed to `"collections"` |
| `create-index` operation type | → `create-collection` |
| `delete-index` operation type | → `delete-collection` |
| Simple `match` queries | Converted to Solr JSON DSL equivalent |
| `term` / `terms` queries | Converted to Solr query string or `{!terms}` local params |
| `range` queries | Converted to Solr range filter with ISO 8601 dates |
| `bool` queries (`must` / `filter` / `should` / `must_not`) | Converted to Solr `bool` query parser |
| Date ranges with `format` parameter | Dates parsed per format and written as ISO 8601 |
| `terms` aggregations | Converted to Solr `terms` facet |
| `date_histogram` aggregations | Converted to Solr `range` facet with calendar gap |
| `avg` / `sum` / `min` / `max` aggregations | Converted to Solr function query stats |

## Requires manual review

These constructs are flagged in `CONVERTED.md` but not automatically converted:

| Construct | Reason |
|-----------|--------|
| `script_score` queries | No direct Solr equivalent; requires a custom function query |
| Complex nested aggregations (3+ levels) | Auto-translation may be incomplete; verify output |
| Custom analyzers in mapping | Configset `schema.xml` must be created manually |
| `multi_match` queries | Partially converted; review field list for Solr equivalents |

## Skipped (with TODO comment)

These operations are not meaningful in Apache Solr and are replaced with a `// TODO` comment in the output:

| Construct | Action |
|-----------|--------|
| `cluster-health` | Not applicable to Solr |
| OpenSearch ML Commons operations | Not applicable to Solr |
| `close-index` / `open-index` | Not applicable to Solr |
| Vector search operations (`knn`, `approximate_knn`) | Solr uses different vector search syntax; manual conversion required |

## Date format mapping

When OpenSearch range queries include a `format` parameter, the converter maps date format strings to Python `strptime` patterns:

| OpenSearch format | Python pattern |
|-------------------|---------------|
| `dd/MM/yyyy` | `%d/%m/%Y` |
| `MM/dd/yyyy` | `%m/%d/%Y` |
| `yyyy-MM-dd` | `%Y-%m-%d` |
| `dd-MM-yyyy` | `%d-%m-%Y` |
| `yyyyMMdd` | `%Y%m%d` |

Dates are converted to Solr ISO 8601 format: `YYYY-MM-DDTHH:MM:SSZ`.
