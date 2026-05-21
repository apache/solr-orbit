# Integration Tests

> **Note**: The integration tests in this directory were originally written for OpenSearch Benchmark and test OpenSearch-specific pipeline steps (provisioning, starting, and querying OpenSearch clusters). They are **not yet adapted** for Apache Solr Benchmark and will not pass against a Solr cluster.
>
> A Solr-native integration test suite is planned as a future user story. Until then, use the Solr unit tests in `tests/unit/solr/` to validate Solr-specific functionality.

## Running the existing tests

These tests require a running OpenSearch cluster and are not part of the default CI for this branch.

```bash
make it   # Requires Java, Docker; ~30 min
```
