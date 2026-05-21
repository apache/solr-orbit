---
title: solr-benchmarkd
parent: Command Reference
grand_parent: Reference
nav_order: 15
---

# solr-benchmarkd

`solr-benchmarkd` is the daemon binary used for distributed load generation. It must be running on every **worker** machine before starting a distributed benchmark from the coordinator.

## Syntax

```bash
solr-benchmarkd start   --node-ip IP --coordinator-ip IP
solr-benchmarkd stop    --node-ip IP --coordinator-ip IP
solr-benchmarkd restart --node-ip IP --coordinator-ip IP
solr-benchmarkd status
```

## Subcommands

| Subcommand | Description |
|-----------|-------------|
| `start` | Start the daemon and register with the coordinator |
| `stop` | Stop the running daemon |
| `restart` | Stop and restart the daemon |
| `status` | Print whether the daemon is currently running |

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--node-ip` | Yes (`start`, `stop`, `restart`) | IP address of this worker machine |
| `--coordinator-ip` | Yes (`start`, `stop`, `restart`) | IP address of the coordinator machine running `solr-benchmark` |

## Examples

Start daemons on two worker machines, then run the benchmark from the coordinator:

```bash
# On worker-1 (192.168.1.10):
solr-benchmarkd start --node-ip 192.168.1.10 --coordinator-ip 192.168.1.1

# On worker-2 (192.168.1.11):
solr-benchmarkd start --node-ip 192.168.1.11 --coordinator-ip 192.168.1.1

# On the coordinator (192.168.1.1):
solr-benchmark run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts solr1:8983,solr2:8983 \
  --worker-ips 192.168.1.10,192.168.1.11
```

Check daemon status on a worker:

```bash
solr-benchmarkd status
```

Stop a worker daemon when the benchmark is complete:

```bash
solr-benchmarkd stop --node-ip 192.168.1.10 --coordinator-ip 192.168.1.1
```

## See also

- [Running Distributed Load](../../user-guide/optimizing-benchmarks/running-distributed-load.html)
- [run command](run.html)
