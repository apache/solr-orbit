---
title: Configuring
parent: Install and Configure
grand_parent: User Guide
nav_order: 7
---

# Configuring Apache Solr Benchmark

Apache Solr Benchmark stores its configuration in `~/.solr-benchmark/benchmark.ini`, which is
automatically created the first time Solr Benchmark runs.

The file is divided into the following sections, which you can customize based on the needs of
your environment.

## meta

This section contains meta information about the configuration file.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `config.version` | Integer | The version of the configuration file format. This value is managed by Solr Benchmark and should not be changed manually. |

## system

This section contains global information for the current benchmark environment. These settings
should be identical on all machines where Solr Benchmark is installed.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `env.name` | String | The name of the benchmark environment, used as metadata in result documents. Only alphanumeric characters are allowed. Default is `local`. |
| `available.cores` | Integer | The number of available CPU cores. Solr Benchmark aims to create one asyncio event loop per core and distributes clients evenly. Defaults to the number of logical CPU cores on the host. |
| `async.debug` | Boolean | Enables debug mode on Solr Benchmark's asyncio event loop. Default is `false`. |
| `passenv` | String | A comma-separated list of environment variable names that should be forwarded during the benchmark run. |

## node

This section contains node-specific information that can be customized for your environment.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `root.dir` | String | The directory that stores all Solr Benchmark data. Solr Benchmark assumes full control over this directory and all its subdirectories. Default is `~/.solr-benchmark`. |

## benchmarks

This section configures the Solr Benchmark data directory.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `local.dataset.cache` | String | The directory in which benchmark datasets are stored. Depending on the workloads you run, this directory may contain hundreds of GB of data. Default is `~/.solr-benchmark/benchmarks/data`. |

## reporting

This section defines how benchmark metrics are stored during a run.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `datastore.type` | String | `in-memory` (default) keeps all metrics in RAM for the duration of the run. `filesystem` keeps metrics in RAM and also streams every raw sample to a `metrics.jsonl` file on disk. See [Metrics](../../../reference/metrics/) for details. |
| `sample.queue.size` | Integer | The number of metric samples that can be held in Solr Benchmark's in-memory queue. Default is `2^20`. |
| `metrics.request.downsample.factor` | Integer | Saves only every Nth sample. Useful when running benchmarks with many clients to avoid storing excessive data. Default is `1` (all samples saved). |
| `output.processingtime` | Boolean | If `true`, shows an additional processing time metric in the console report. Default is `false`. |

### Example: filesystem metrics store

```ini
[reporting]
datastore.type = filesystem
```

When `datastore.type` is set to `filesystem`, raw metric documents are written to
`~/.solr-benchmark/benchmarks/test-runs/<run-id>/metrics.jsonl` incrementally during the run.
See [Filesystem Metrics Store](../../../reference/metrics/filesystem-metrics-store.html) for
file layout details and examples for inspecting raw samples.

## workloads

This section defines how workloads are retrieved. Keys follow the format
`<repository-name>.url`, selectable at run time with `--workload-repository=<repository-name>`.

```ini
[workloads]
default.url = https://github.com/janhoy/solr-benchmark-workloads
```

## defaults

This section defines the default values for certain Solr Benchmark CLI parameters.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `preserve_benchmark_candidate` | Boolean | Determines whether Solr installations are preserved or removed after a benchmark run. To preserve an installation for a single run, use `--preserve-install` on the command line. Default is `false`. |

## distributions

This section configures how Solr distribution archives are managed when using
`--pipeline=from-distribution`.

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `release.cache` | Boolean | Determines whether downloaded Solr release archives are cached locally for reuse. Default is `true`. |

## Proxy configurations

If your host accesses the internet through an HTTP proxy, you can configure Solr Benchmark to
use it for downloading workloads and distribution archives.

1. Add your proxy URL to your shell profile:

   ```bash
   export http_proxy=http://proxy.example.org:4444/
   ```

2. Source your shell profile and verify the proxy URL is set:

   ```bash
   source ~/.bash_profile ; echo $http_proxy
   ```

3. Configure Git to use the proxy:

   ```bash
   git config --global http.proxy $http_proxy
   ```

4. Verify the proxy is working by cloning the workloads repository:

   ```bash
   git clone https://github.com/janhoy/solr-benchmark-workloads.git
   ```

5. Confirm Solr Benchmark picks up the proxy setting by checking the log at
   `~/.solr-benchmark/logs/benchmark.log`. At startup you should see:

   ```
   Connecting via proxy URL [http://proxy.example.org:4444/] to the Internet (picked up from the environment variable [http_proxy]).
   ```

## Logging

Logs from Solr Benchmark can be configured in `~/.solr-benchmark/logging.json`. For details on
the log file format, see the Python documentation:

- [Python Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html) — general tips.
- [Logging configuration schema](https://docs.python.org/3/library/logging.config.html#logging-config-dictschema) — file format reference.
- [Logging handlers](https://docs.python.org/3/library/logging.handlers.html) — customizing where log output is written.

By default, Solr Benchmark writes all log output to `~/.solr-benchmark/logs/benchmark.log`.
Log level is controlled via `~/.solr-benchmark/logging.json`, not via a CLI flag.
