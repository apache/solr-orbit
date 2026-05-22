---
title: generate-data
parent: Command Reference
grand_parent: Reference
nav_order: 40
---

# generate-data

Generates synthetic benchmark data from an existing index schema (JSON mappings) or a custom Python module. The generated corpus can be used in Apache Solr Orbit workloads.

## Syntax

```bash
solr-orbit generate-data --index-mappings FILE --total-size N --index-name NAME [OPTIONS]
solr-orbit generate-data --custom-module FILE  --total-size N --index-name NAME [OPTIONS]
```

`--index-mappings` and `--custom-module` are mutually exclusive. `--total-size` is required.

## Options

| Option | Short | Required | Default | Description |
|--------|-------|----------|---------|-------------|
| `--index-mappings` | `-i` | Yes (or `--custom-module`) | — | Path to a JSON file containing index mappings to use as the schema for generated documents |
| `--custom-module` | `-m` | Yes (or `--index-mappings`) | — | Path to a custom Python module that defines document generation logic. The module must contain a `generate_synthetic_document()` function |
| `--total-size` | `-s` | Yes | — | Target corpus size in GB |
| `--index-name` | `-n` | Yes | — | Name for the generated corpus (used in the output file path) |
| `--output-path` | `-p` | No | `./generated_corpora` | Directory where the generated corpus files will be written |
| `--custom-config` | `-c` | No | — | Optional config file for overriding synthetic data generation settings or providing values used by a custom module |
| `--test-document` | `-t` | No | off | Generate a single document and print it to the console for validation, without writing a full corpus |

## Examples

Generate 10 GB of synthetic data from an existing schema:

```bash
solr-orbit generate-data \
  --index-mappings /path/to/mappings.json \
  --index-name my_index \
  --total-size 10 \
  --output-path /data/corpora
```

Preview a single generated document using a custom module:

```bash
solr-orbit generate-data \
  --custom-module /path/to/my_generator.py \
  --index-name my_index \
  --total-size 1 \
  --test-document
```

## See also

- [Corpora](../workloads/corpora.html)
- [create-workload](create-workload.html)
