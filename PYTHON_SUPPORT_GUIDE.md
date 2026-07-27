# Python Support Guide

This document walks developers through how to add support for new major and
minor Python versions in Apache Solr Orbit.

## Update Python versions supported

Make changes to the following files and open a PR titled
"Update Python versions supported to `<list of versions>`".

* `pyproject.toml`: Update `requires-python` and the `classifiers` list under `[project]`.
* `pyproject.toml`: Update `envlist` in the `[tool.tox]` `legacy_tox_ini` section.
  Integration test environments are created by [tox-uv](https://github.com/tox-dev/tox-uv),
  which downloads missing Python interpreters automatically — no further setup is needed.
* `.python-version`: If updating the default development Python version, update the
  pinned version (used by `uv` when creating `.venv`).
* `Makefile`: If adding or removing a version, update the `it<VERSION>` targets
  (e.g. `it312 it313`).

* `solrorbit/__init__.py`: Update the minimum version in the error message:

  ```python
  raise RuntimeError("Solr Orbit requires at least Python <MIN_VERSION> but you are using:\n\nPython %s" % str(sys.version))
  ```

## Testing new Python versions

1. Set up a fresh environment on each supported OS: macOS, Ubuntu, Amazon Linux 2.
2. Create a virtual environment with the new Python version (uv downloads it if missing):
   ```bash
   uv sync --extra develop --python <PYTHON VERSION>
   uv run python --version   # confirm
   ```

3. Run the following tests:

**Basic run with a local Solr instance (benchmark-only pipeline):**
```bash
solr-orbit run \
  --pipeline=benchmark-only \
  --workload=<YOUR_WORKLOAD> \
  --target-host="localhost:8983" \
  --test-mode
```

**Run without test mode:**
```bash
solr-orbit run \
  --pipeline=benchmark-only \
  --workload=<YOUR_WORKLOAD> \
  --target-host="<SOLR HOST:PORT>"
```

**Run with distribution provisioning:**
```bash
solr-orbit run \
  --pipeline=solr-from-distribution \
  --distribution-version=9.7.0 \
  --workload=<YOUR_WORKLOAD> \
  --test-mode
```

4. To test the installed binary path explicitly:
   ```bash
   which solr-orbit   # e.g. /path/to/solr-orbit/.venv/bin/solr-orbit
   .venv/bin/solr-orbit run --pipeline=benchmark-only ...
   ```

## Creating a pull request

After testing, open a PR. Once merged, create and push a version tag to
trigger the release pipeline:

```bash
git tag <NEW MAJOR.MINOR.PATCH VERSION> main
git push origin <NEW MAJOR.MINOR.PATCH VERSION>
```
