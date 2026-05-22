# Apache Solr Orbit

Apache Solr Orbit is a macrobenchmarking framework for [Apache Solr](https://solr.apache.org/).

It is a fork/port of [Rally](https://github.com/elastic/rally)/[Opensearch Benchmark](https://github.com/opensearch-project/opensearch-benchmark), ported to work with Apache Solr.

## Documentation

Full documentation is available in [`docs/`](docs/) folder of this repository. Build the docs with jekyll.
A public documentation site is available at [https://apache.github.io/solr-orbit/](https://apache.github.io/solr-orbit/).

**This is a Work in Progress**

## What is Apache Solr Orbit?

If you are looking to performance test Apache Solr, this tool can help you with:

* Running performance benchmarks and recording results
* Setting up and tearing down Solr clusters for benchmarking (local distribution, build-from-source or Docker, including nightly builds)
* Managing benchmark workloads (collections, configsets, search operations)
* Run same workload against multiple Solr versions or multiple cluster-configurations (heap size, GC settings, etc.)
* Collecting JVM, node, and collection metrics via telemetry devices
* Output results for each run in JSON format, suitable for analysis and dashboarding
* Assist in converting existing OpenSearch Benchmark workloads to Solr format

## Quick Start

### Install

**NOTE**: We do not offer the tool as a python package yet

```bash
pip install -e .
```

### Run a benchmark against a Solr version in Docker

```bash
solr-orbit run \
  --pipeline=docker \
  --distribution-version=9.10.1 \
  --workload=nyc_taxis \
  --test-mode
```

**Note**: Defaults to cloud mode (SolrCloud with embedded ZooKeeper).

### Provision Solr locally, then benchmark

```bash
solr-orbit run \
  --pipeline=from-distribution \
  --distribution-version=9.10.1 \
  --workload=nyc_taxis \
  --test-mode
```

**Note**: Always uses cloud mode (SolrCloud with embedded ZooKeeper).

### Provision Solr from source, then benchmark

```bash
solr-orbit run \
  --pipeline=from-sources \
  --distribution-version=9.10.1 \
  --workload=nyc_taxis \
  --test-mode
```

## Workload format

See [Workload Reference](https://apache.github.io/solr-orbit/reference/workloads/) in the documentation for the full `workload.json` format, including `collections`, `corpora`, `operations`, and `test-procedures`.

Pre-built workloads are available at [https://github.com/apache/solr-orbit-workloads](https://github.com/apache/solr-orbit-workloads). Feel free to
contribute your own with a pull request!

## Result output

Each test-run outputs a **test_run.json**, a complete canonical record of the benchmark run including:
  - Benchmark metadata (version, environment, pipeline, user tags)
  - Workload and test procedure information
  - Cluster configuration specification (heap size, GC settings, all variables)
  - Detailed operation metrics (throughput, latency, error rates)
  - System metrics (GC times, merge times, segment counts, etc.)

This output can be used for further analysis, comparison and dashboarding.

## License

Apache License, Version 2.0. See [LICENSE](LICENSE) for the full text.

This product includes software developed by the OpenSearch Contributors, and
prior to that by Elasticsearch (Rally). Full attribution is in [NOTICE](NOTICE).
