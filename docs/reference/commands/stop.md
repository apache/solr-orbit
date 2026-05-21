---
title: stop
parent: Command Reference
grand_parent: Reference
nav_order: 85
---

# stop

Stops a locally running Solr node that was started with the [`start`](start.html) command.

## Syntax

```bash
solr-benchmark stop --installation-id ID [OPTIONS]
```

## Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--installation-id` | Yes | — | ID of the installation to stop |
| `--preserve-install` | No | off | Keep the installation files on disk after stopping. By default, the installation directory is deleted when the node stops |

## Examples

Stop a node and clean up:

```bash
solr-benchmark stop --installation-id <installation-id>
```

Stop a node but keep the installation files:

```bash
solr-benchmark stop --installation-id <installation-id> --preserve-install
```

## See also

- [install](install.html)
- [start](start.html)
