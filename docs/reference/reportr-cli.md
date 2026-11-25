---
title: reportr Command Reference
parent: Reference
nav_order: 54
---

# reportr Command Reference

`reportr` builds a static benchmark trends site from stored Solr Orbit reports. It runs no benchmarks. For how to read what it produces, see [Results and Trend Reports](../user-guide/continuous-benchmarking/results-and-trends.html).

```bash
reportr [-v | -q] <command> [options]
```

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help and exit. |
| `--version` | Print the version and exit. |
| `-v`, `--verbose` | Log at DEBUG level. |
| `-q`, `--quiet` | Log warnings and errors only. |

Every subcommand accepts the same options for locating the result store:

| Option | Description |
|--------|-------------|
| `-c FILE`, `--config FILE` | Configuration file. Defaults to `./reportr.yaml` if present. |
| `--local DIR` | Read reports from this directory — shorthand for a local `--storage-path`. |
| `--storage BACKEND` | Storage backend: `local` or `s3`. Inferred from an `s3://` path. |
| `--storage-path PATH` | Storage root. Defaults to the store `launchr` writes to. |

{: .note }
`reportr` resolves settings as **CLI flag > `reportr.yaml` > built-in default**. Unlike `launchr`, there is no environment-variable layer and no `validate-config` subcommand.

---

## build

Reads every stored report and writes the site.

```bash
reportr build [options]
```

### Options

| Option | Description |
|--------|-------------|
| `--out DIR` | Where to write the site. Default `./site-output`. |
| `--metrics METRICS` | Comma-separated metric keys, overriding the configuration. |
| `--serve` | Serve the site after building it. |
| `--port PORT` | Port for `--serve`. Default `8080`. |
| `--open` | Open the site in a browser after building. |
| `--publish [DEST]` | Publish after building, to `DEST` or to `site.publish_to`. |

A report the site cannot plot is skipped and counted, not silently dropped: the summary names how many were read, how many were charted, and why the rest were not.

### Examples

```bash
reportr build --serve                       # build and read it locally
reportr build --local ~/.solr-orbit/benchmark-results --serve
reportr build --config reportr-ec2.yaml --publish
```

### See also

[Results and Trend Reports](../user-guide/continuous-benchmarking/results-and-trends.html)

---

## publish

Uploads a site that has already been built.

```bash
reportr publish [--to DEST] [options]
```

### Options

| Option | Description |
|--------|-------------|
| `--out DIR` | The built site to upload. Default `./site-output`. |
| `--to DEST` | `s3://bucket/prefix` or a directory. Defaults to `site.publish_to`. |
| `--dry-run` | List what would be uploaded; upload nothing. |

Publishing adds and replaces files; it never deletes. Where the results share a prefix with the site, a prune would remove the benchmark history.

### Examples

```bash
reportr publish --to s3://my-bucket/public --dry-run
reportr publish --to s3://my-bucket/public
reportr publish --to /srv/www/benchmarks
```

### See also

[Publishing the Site to S3](../user-guide/continuous-benchmarking/publishing-to-s3.html)

---

## metrics

Lists the metric keys the stored reports could supply, and how many reports carry each. Useful because the available percentiles depend on `--latency-percentiles` and on how many samples a run produced — a `--test-mode` run may offer `p50` and `p100` but no `p99`.

```bash
reportr metrics [options]
```

Keys currently charted are marked.

---

## version

```bash
reportr version
```
