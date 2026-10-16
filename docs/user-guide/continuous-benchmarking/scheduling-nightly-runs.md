---
title: Scheduling Nightly Runs
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 60
---

# Scheduling Nightly Runs

Automate the sequence only once you have run it by hand. Everything below assumes `launchr run` and `reportr build --publish` already work from a shell on this host.

A nightly consists of three steps and one safety net:

1. Validate the configuration — fails in seconds if something is wrong.
2. Run the matrix.
3. Build and publish the site.
4. Separately and more often: reclaim anything a failed run left behind.

## A systemd timer

```ini
# /etc/systemd/system/solr-benchmark.service
[Unit]
Description=Nightly Solr benchmark
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=benchmark
WorkingDirectory=/srv/solr-orbit
Environment=BENCHMARK_HOME=/srv/solr-orbit
Environment=HOME=/home/benchmark
Environment=AWS_PROFILE=solr-orbit
ExecStartPre=/usr/local/bin/launchr validate-config --config /etc/solr-orbit/launchr.yaml
ExecStart=/usr/local/bin/launchr run --config /etc/solr-orbit/launchr.yaml
ExecStartPost=/usr/local/bin/reportr build --config /etc/solr-orbit/reportr.yaml --publish
TimeoutStartSec=12h
```

```ini
# /etc/systemd/system/solr-benchmark.timer
[Unit]
Description=Run the Solr benchmark nightly

[Timer]
OnCalendar=*-*-* 01:00:00
Persistent=false

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now solr-benchmark.timer
systemctl list-timers solr-benchmark.timer
journalctl -u solr-benchmark.service -f
```

Four details matter:

- **`HOME` must be set.** The AWS credential chain reads `~/.aws/config`, and a systemd unit does not inherit your shell's environment.
- **`TimeoutStartSec` must exceed a full run.** A full-corpus matrix takes hours; the default would kill it partway and leave infrastructure running.
- **`Persistent=false`** so a host that was off overnight does not start a multi-hour benchmark the moment it boots.
- **`ExecStartPost` runs only on success**, so a failed session does not publish a half-empty site. Use `ExecStopPost` instead if you would rather publish whatever completed.

## The cron equivalent

```cron
0 1 * * *  BENCHMARK_HOME=/srv/solr-orbit AWS_PROFILE=solr-orbit \
           /usr/local/bin/launchr run --config /etc/solr-orbit/launchr.yaml --quiet \
           && /usr/local/bin/reportr build --config /etc/solr-orbit/reportr.yaml --publish
```

Cron's environment is smaller still — give it absolute paths and set `HOME` explicitly if the credential chain needs it.

## The teardown sweep

If a run is killed outright — a reboot, an OOM, a dropped connection — its own cleanup never executes and cloud instances keep billing. Schedule a reconciliation sweep independently of the benchmark:

```cron
30 * * * *  /usr/local/bin/launchr teardown --config /etc/solr-orbit/launchr.yaml --older-than 6h
```

{: .warning }
`--older-than` is not optional in a scheduled sweep. Without it, the instances of a run that is *currently in progress* look exactly like a leak, and the sweep destroys the benchmark it was meant to protect. The window must comfortably exceed your longest run.

Run it by hand with `--dry-run` first to see what it would reclaim.

## When a run fails

The failure modes are different and want different responses:

| Symptom | Meaning |
|---------|---------|
| One cell failed, the rest completed | Data, not an outage. The report is stored with `status: failed` and its logs. |
| Every cell failed identically | Usually configuration or credentials. `validate-config` as a pre-flight step catches most of these before any spend. |
| The session died partway | Infrastructure may still be running. The teardown sweep reclaims it; check `launchr teardown --dry-run`. |

A failed cell appears in the stored summary and is skipped by the site, which charts only what it can plot. Nothing silently disappears.

## Iterations and statistical confidence

[Performance Testing Best Practices](../optimizing-benchmarks/best-practices.html) recommends running three or more iterations and aggregating them, to separate signal from run-to-run variance. `launchr` defaults to `iterations: 1`.

That is a deliberate trade, not an oversight. A nightly schedule produces repeats across *days* rather than within a session, so variance becomes visible as scatter on the trend line instead of being averaged away. Raising `iterations` multiplies the cost of every cell — on cloud hardware, directly in money.

Choose by what you intend to detect. Chasing a small regression on a single night needs within-session repeats; watching for drift over months does not. If you raise it, raise `aggregate` with it, and expect the session to take proportionally longer.

## A reasonable nightly matrix

Keep it small. A matrix that does not finish before the next trigger is worse than a smaller one that does.

```yaml
solr_versions:
  - "9.11.0"            # the current release, as a fixed reference
  - "10.2.0-SNAPSHOT"   # the 10.x branch
  - "11.0.0-SNAPSHOT"   # main
workloads:
  - name: nyc_taxis
defaults:
  provisioning: ["ec2-2node"]
  cluster_config: ["2shard-1replica"]
```

One pinned release anchors the chart: if its numbers move, the environment changed, not Solr.
