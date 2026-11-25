---
title: install
parent: Command Reference
grand_parent: Reference
nav_order: 55
---

# install

Installs a local Solr node for use with the [`start`](start.html) and [`stop`](stop.html) commands. This is a low-level provisioning command for when you want manual control over the Solr lifecycle rather than having `run` manage it automatically.

## Syntax

```bash
solr-orbit install [OPTIONS]
```

## Options

### Distribution

| Option | Default | Description |
|--------|---------|-------------|
| `--distribution-version` | — | Solr version to install (e.g., `9.10.1`) |
| `--distribution-repository` | `release` | Repository to download Solr from |
| `--revision` | — | Source code revision for the `from-sources` pipeline |

### Runtime

| Option | Default | Description |
|--------|---------|-------------|
| `--runtime-jdk` | — | Major JDK version to use (e.g., `21`) |
| `--solr-modules` | — | Comma-separated Solr modules to enable (e.g., `extraction`) |
| `--plugin-params` | — | Comma-separated `key:value` pairs passed to all configured plugins |

### Cluster configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--cluster-config` | `defaults` | Cluster config preset to apply |
| `--cluster-config-params` | — | Comma-separated `key:value` variable overrides for the cluster config |
| `--cluster-config-path` | — | Local path to a cluster configuration directory |
| `--cluster-config-repository` | — | Git URL for a custom cluster-config repository |
| `--cluster-config-revision` | — | Git revision of the cluster-config repository |

### Node placement

| Option | Default | Description |
|--------|---------|-------------|
| `--network-host` | `127.0.0.1` | Host address for Solr to bind to |
| `--http-port` | `38983` | HTTP port for the Solr node |
| `--node-name` | `benchmark-node-0` | Name for the installed node |
| `--master-nodes` | — | Comma-separated list of master node names (for multi-node setups) |
| `--seed-hosts` | — | Comma-separated seed host addresses for cluster discovery |

## Example

Install Solr 10.1.0 locally on the default port:

```bash
solr-orbit install \
  --distribution-version 10.1.0 \
  --cluster-config defaults
```

Install on a custom port with a specific JDK:

```bash
solr-orbit install \
  --distribution-version 10.1.0 \
  --runtime-jdk 21 \
  --http-port 18983 \
  --node-name my-node
```

After installation, use the printed installation ID with the [`start`](start.html) command.

## See also

- [start](start.html)
- [stop](stop.html)
