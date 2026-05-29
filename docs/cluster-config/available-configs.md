---
title: Available Configs
parent: Cluster Config
nav_order: 2
---

# Available Cluster Configs

## defaults

Sets the Java heap to 1 GB (`heap_size=1g`). This is the baseline configuration that all other heap-size configs extend.

```
heap_size: 1g
```

**Usage:**
```bash
solr-orbit run --cluster-config defaults ...
```

---

## 1gheap

Sets the Solr JVM heap to 1 GB. Suitable for small workloads and testing.

```
heap_size: 1g
```

**Usage:**
```bash
solr-orbit run --cluster-config 1gheap ...
```

---

## 2gheap

Sets the Solr JVM heap to 2 GB.

```
heap_size: 2g
```

**Usage:**
```bash
solr-orbit run --cluster-config 2gheap ...
```

---

## 4gheap

Sets the Solr JVM heap to 4 GB. Suitable for larger workloads.

```
heap_size: 4g
```

**Usage:**
```bash
solr-orbit run --cluster-config 4gheap ...
```

---

## 8gheap

Sets the Solr JVM heap to 8 GB.

```
heap_size: 8g
```

**Usage:**
```bash
solr-orbit run --cluster-config 8gheap ...
```

---

## 16gheap

Sets the Solr JVM heap to 16 GB.

```
heap_size: 16g
```

**Usage:**
```bash
solr-orbit run --cluster-config 16gheap ...
```

---

## 24gheap

Sets the Solr JVM heap to 24 GB.

```
heap_size: 24g
```

**Usage:**
```bash
solr-orbit run --cluster-config 24gheap ...
```

---

## g1gc

Enables the G1 garbage collector. Recommended for latency-sensitive benchmarks.

```
use_g1_gc: true
```

**Usage:**
```bash
solr-orbit run --cluster-config g1gc ...
```

---

## parallelgc

Enables the Parallel (throughput-optimized) garbage collector.

```
use_cms_gc: false
use_g1_gc: false
```

**Usage:**
```bash
solr-orbit run --cluster-config parallelgc ...
```

Note: `parallelgc` is available in the `main` cluster config bundle but not in `1.0`.

---

## vanilla

The base cluster configuration. All other heap and GC configs extend `vanilla`. Use this when you want to run Solr with no heap or GC overrides beyond Solr Orbit defaults.

**Usage:**
```bash
solr-orbit run --cluster-config vanilla ...
```

---

## ea

Mixin that enables Java assertions (`-ea`). Useful for debugging workload runs.

**Usage:**
```bash
solr-orbit run --cluster-config ea ...
```

---

## fp

Mixin that preserves JVM frame pointers. Required for accurate async-profiler CPU profiles.

**Usage:**
```bash
solr-orbit run --cluster-config fp ...
```

---

## debug-non-safepoints

Mixin that enables more accurate CPU profiling by recording non-safepoint debug information.

**Usage:**
```bash
solr-orbit run --cluster-config debug-non-safepoints ...
```

---

## Comparing configs

To compare G1GC vs Parallel GC on the same workload:

```bash
# Run 1: G1GC
solr-orbit run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --cluster-config g1gc

# Run 2: Parallel GC
solr-orbit run \
  --pipeline docker \
  --distribution-version 9.10.1 \
  --workload nyc_taxis \
  --cluster-config parallelgc

# Compare results
solr-orbit compare \
  --baseline <g1gc-run-id> \
  --contender <parallelgc-run-id>
```
