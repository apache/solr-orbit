---
title: download
parent: Command Reference
grand_parent: Reference
nav_order: 30
---

# download

Downloads a Solr distribution to the local machine without running a benchmark. Use this to pre-fetch a distribution before running a `from-distribution` or `docker` pipeline benchmark.

## Syntax

```bash
solr-orbit download --distribution-version VERSION [OPTIONS]
```

Because Solr is pure Java, the distribution tarball is the same on every operating system and CPU architecture. There are no OS- or architecture-specific variants to select.

## Options

| Option | Description |
|--------|-------------|
| `--distribution-version` | Solr version to download (e.g., `9.10.1`, `10.0.0`) |
| `--distribution-repository` | Source repository (default: `release`) |
| `--cluster-config` | Cluster configuration preset to apply |
| `--cluster-config-params` | Comma-separated `key:value` variable overrides for the cluster configuration |
| `--cluster-config-path` | Local path to a cluster configuration directory |
| `--cluster-config-repository` | Git URL for a cluster configuration repository |

## Output

On success, the command prints a JSON object with the path to the downloaded artifact:

```json
{
  "solr": "/Users/yourname/.solr-orbit/distributions/solr-9.10.1.tgz"
}
```

## Examples

```bash
# Download Solr 9.10.1
solr-orbit download --distribution-version 9.10.1
```

## See also

- [from-distribution pipeline](../../user-guide/concepts.html#pipelines)
- [Cluster Config](../../cluster-config/)
