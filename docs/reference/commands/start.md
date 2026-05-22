---
title: start
parent: Command Reference
grand_parent: Reference
nav_order: 60
---

# start

Starts a locally installed Solr node previously created by the [`install`](install.html) command.

## Syntax

```bash
solr-orbit start --installation-id ID --test-run-id ID [OPTIONS]
```

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--installation-id` | Yes | ID of the installation to start (returned by the `install` command) |
| `--test-run-id` | Yes | Test run ID to associate with this start event |
| `--runtime-jdk` | No | Major JDK version to use (e.g., `21`) |
| `--telemetry` | No | Comma-separated telemetry device names to activate |
| `--telemetry-params` | No | Comma-separated `key:value` parameters for telemetry devices |

## Example

```bash
# Install and capture the installation ID
solr-orbit install --distribution-version 9.10.1

# Start the installed node (use the ID printed by install)
solr-orbit start \
  --installation-id <installation-id> \
  --test-run-id my-run-001

# Run the benchmark against the manually started node
solr-orbit run \
  --pipeline benchmark-only \
  --target-hosts localhost:38983 \
  --workload nyc_taxis \
  --test-run-id my-run-001

# Stop when done
solr-orbit stop --installation-id <installation-id>
```

## See also

- [install](install.html)
- [stop](stop.html)
