---
title: Continuous Benchmarking
parent: User Guide
nav_order: 40
has_children: true
---

# Continuous Benchmarking

A single benchmark tells you how a cluster performed today. A *series* of benchmarks tells you whether Solr is getting faster or slower, and which change was responsible. Producing that series by hand does not scale: it means provisioning identical hardware every time, running the same matrix of versions and workloads, storing each result where the next run can find it, and turning the accumulated history into something readable.

Two companion tools ship with Apache Solr Orbit to do that work.

| Tool | Responsibility |
|------|----------------|
| `launchr` | Runs a *matrix* of benchmarks — versions × workloads × hardware profiles × cluster configs — provisioning and destroying infrastructure around each one, and storing every result immutably. |
| `reportr` | Reads that store and emits a static website charting each metric over time. |

Both are console scripts installed with Solr Orbit. Neither replaces `solr-orbit`: `launchr` invokes it once per matrix cell, and `reportr` never runs a benchmark at all.

## Who this chapter is for

You have already run benchmarks locally, understand workloads and test procedures, and now want runs to happen on a schedule without you. If you have not benchmarked Solr before, start with the [Quickstart](../../quickstart.html) and [Running a Workload](../working-with-workloads/running-workloads.html) instead.

## Reading order

The chapter is written to be read in sequence. Each step produces something before the next begins.

| Page | What you end up with |
|------|----------------------|
| [How Continuous Benchmarking Works](overview.html) | The model: cells, groups, the enriched report, the version timeline. |
| [A Local Trial Run](a-local-trial-run.html) | A real matrix run and a trends site, on your own machine, with no cloud account. |
| [Configuring launchr](configuring-launchr.html) | A `launchr.yaml` that describes the matrix you actually want. |
| [Results and Trend Reports](results-and-trends.html) | A site you can read, tuned to show the tasks you care about. |
| [Running on a Dedicated Host](on-a-dedicated-host.html) | The whole pipeline off your laptop and onto a machine that stays up. |
| [Scheduling Nightly Runs](scheduling-nightly-runs.html) | Runs that happen without you, and clean up after themselves. |
| [Provider: AWS](provider-aws.html) | Benchmarks on dedicated cloud hardware, destroyed when finished. |
| [Publishing the Site to S3](publishing-to-s3.html) | A public URL showing the trend. |

Scheduling comes before the cloud provider on purpose: a cron job wrapping a procedure you have not yet run by hand is how you discover a misconfiguration at four in the morning with instances billing.

## Command reference

Flags and options for both tools live in Reference, not here:

- [launchr Command Reference](../../reference/launchr-cli.html)
- [reportr Command Reference](../../reference/reportr-cli.html)
