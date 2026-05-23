---
title: Running Distributed Load
parent: Optimizing Benchmarks
grand_parent: User Guide
nav_order: 30
---

# Running Distributed Load

By default, Apache Solr Orbit generates all load from the machine where you run the `solr-orbit` command. For large clusters or high-throughput benchmarks, a single machine may become the bottleneck before Solr does. Distributed load generation lets you spread the workload across multiple machines.

## Architecture

In distributed mode, one machine acts as the **coordinator** and one or more additional machines act as **workers**. The coordinator:

- Parses and distributes the workload
- Sends task assignments to each worker
- Collects and aggregates metrics from all workers

Each worker:
- Executes its assigned portion of the load against the Solr cluster
- Sends metrics back to the coordinator

The coordinator and workers communicate over the network. All machines must be able to reach each other and the Solr cluster.

## Prerequisites

- The same version of Apache Solr Orbit must be installed on all coordinator and worker machines
- All machines must have network access to the Solr cluster
- Workers must have the workload data files available at the same path as the coordinator (or accessible via a shared filesystem)

## Configuration

### Start the benchmark daemon on each worker

On each worker machine, start the benchmark daemon:

```bash
solr-orbitd start --node-ip WORKER_IP --coordinator-ip COORDINATOR_IP
```

Replace `WORKER_IP` with the IP address of that worker machine and `COORDINATOR_IP` with the IP address of the machine that will run `solr-orbit run`.

### Run the benchmark from the coordinator

On the coordinator machine, pass the worker IPs via `--worker-ips`:

```bash
solr-orbit run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts solr1:8983,solr2:8983,solr3:8983 \
  --worker-ips 192.168.1.10,192.168.1.11,192.168.1.12
```

The coordinator automatically divides the corpus and task schedule across the specified workers.

## How load is divided

The corpus is partitioned by line ranges in the NDJSON data files. Each worker receives a non-overlapping slice of documents to index. For query tasks, each worker runs the full query schedule with the specified `clients` count, so the effective query rate is `clients × number_of_workers`.

## Example: 3-worker setup

```bash
# On worker-1 (192.168.1.10):
solr-orbitd start --node-ip 192.168.1.10 --coordinator-ip 192.168.1.1

# On worker-2 (192.168.1.11):
solr-orbitd start --node-ip 192.168.1.11 --coordinator-ip 192.168.1.1

# On worker-3 (192.168.1.12):
solr-orbitd start --node-ip 192.168.1.12 --coordinator-ip 192.168.1.1

# On the coordinator (192.168.1.1):
solr-orbit run \
  --workload nyc_taxis \
  --pipeline benchmark-only \
  --target-hosts solr1:8983,solr2:8983 \
  --worker-ips 192.168.1.10,192.168.1.11,192.168.1.12 \
  --user-tag "workers:3"
```

## Stopping workers

When the benchmark is complete, stop each worker daemon:

```bash
solr-orbitd stop --node-ip 192.168.1.10 --coordinator-ip 192.168.1.1
```

Check daemon status on any worker:

```bash
solr-orbitd status
```

See the [solr-orbitd reference](../../reference/commands/benchmarkd.html) for full daemon documentation.

## When to use distributed load

Consider distributed load generation when:

- A single machine cannot sustain the target query rate (CPU or network saturated on the load generator, not on Solr)
- You want to simulate many independent clients connecting from different source IPs
- Your indexing throughput is limited by the speed of reading and sending documents from the coordinator
