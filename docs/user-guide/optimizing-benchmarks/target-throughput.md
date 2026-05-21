---
title: Target Throughput
parent: Optimizing Benchmarks
grand_parent: User Guide
nav_order: 10
---

# Target Throughput

`target-throughput` is one of the most important — and most misunderstood — parameters in Apache Solr Benchmark. Getting it right is key to measuring meaningful latency.

## What target-throughput means

`target-throughput` sets the rate at which Apache Solr Benchmark issues requests, measured in operations per second (ops/s). It does **not** guarantee that Solr will complete requests at that rate — it only controls how fast the benchmark sends them.

## Two benchmark modes

### Pure throughput mode (no target-throughput)

When `target-throughput` is not set (or set to `0`), each benchmark client sends one request, waits for the response, then immediately sends the next. The benchmark drives load as fast as the cluster can handle.

In this mode **latency equals service time** — there is no queue wait because every request is dispatched as soon as the previous one completes.

Use this mode to find the maximum throughput your Solr cluster can sustain.

### Throughput-throttled mode (target-throughput set)

When `target-throughput` is set, the benchmark issues requests at a fixed rate regardless of how fast responses arrive. If a request takes longer than the inter-request interval, the next request must wait in a local queue. That wait time is added to the latency measurement.

**Latency = service time + queue wait time**

Use this mode to measure how your cluster behaves under a *specific, realistic load* — for example, the query rate your production system typically receives.

## Why setting target-throughput too high is dangerous

If you set `target-throughput` higher than what Solr can actually sustain, the request queue grows without bound. Each successive request waits longer than the previous one, and measured latency climbs continuously — but this inflation is an artifact of the benchmark configuration, not a property of the cluster.

**Example:** Suppose individual search requests take 200 ms (5 ops/s max throughput). If you set `target-throughput: 10`, the benchmark tries to send a request every 100 ms. After the first request, a second request is already queued. It waits 100 ms before sending, adding 100 ms to its latency. By the tenth request, there is 900 ms of accumulated queue wait. This grows without limit as the run continues.

## How to set target-throughput correctly

1. Run the workload once **without** `target-throughput` to establish the maximum sustainable throughput.
2. Set `target-throughput` to a value **below** the maximum — for example, 70–80% of the observed peak.
3. Re-run and verify that latency stays stable throughout the run (not climbing over time). A stable latency indicates the queue is not growing.

### Checking for queue buildup

If latency climbs steadily from the start of the run to the end, your `target-throughput` is too high. Reduce it until latency stabilizes.

## Setting target-throughput in a workload

Set `target-throughput` in the schedule section of your workload's test procedure:

```json
{
  "schedule": [
    {
      "operation": "search",
      "clients": 4,
      "target-throughput": 20
    }
  ]
}
```

This example issues 20 search requests per second across 4 clients (5 requests per client per second).

You can also override it at runtime without editing the workload file:

```bash
solr-benchmark run \
  --workload nyc_taxis \
  --workload-params "search_target_throughput:20"
```

## See also

- [Concepts — Metrics](../concepts.html#metrics) — definitions of latency, service time, and throughput
- [Fine-tuning workloads](../working-with-workloads/finetune-workloads.html) — other schedule parameters
