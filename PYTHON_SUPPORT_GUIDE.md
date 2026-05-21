# Python Support Guide

This document walks developers through how to add support for new major and
minor Python versions in Apache Solr Benchmark.

## Update Python versions supported

Make changes to the following files and open a PR titled
"Update Python versions supported to `<list of versions>`".

* `.ci/variables.json`: Update Python variables and `MIN_PY_VER` as needed.
  For example: to add Python `3.13`, ensure there is a `PY313` variable set
  to the latest patch release such as `3.13.1`.
* `.github/workflows/integ-tests.yml`: Update supported Python versions in
  the `python-versions` section.
* `setup.py`: Update `supported_python_versions`.
* `tox.ini`: Update `env_list`.
* `Makefile`: If updating the minimum supported Python version, update the
  `pyinst<MIN_VERSION>` target and `check-pip`:

  ```makefile
  VERSION310 = $(shell jq -r '.python_versions | .[]' .ci/variables.json | sed '$$d' | grep 3\.10)

  pyinst310:
      pyenv install --skip-existing $(VERSION310)
      pyenv local $(VERSION310)

  check-pip:
      @if ! $(PIP) > /dev/null 2>&1 || ! $(PIP) install pip > /dev/null 2>&1; then make pyinst310; fi
  ```

* `osbenchmark/__init__.py`: Update the minimum version in the error message:

  ```python
  raise RuntimeError("Solr Benchmark requires at least Python <MIN_VERSION> but you are using:\n\nPython %s" % str(sys.version))
  ```

## Testing new Python versions

1. Set up a fresh environment on each supported OS: macOS, Ubuntu, Amazon Linux 2.
2. Install the new Python version (via pyenv or from source). Switch to it:
   ```bash
   pyenv local <PYTHON VERSION>
   python3 --version   # confirm
   ```

3. Run the following tests:

**Basic run with a local Solr instance (benchmark-only pipeline):**
```bash
solr-benchmark run \
  --pipeline=benchmark-only \
  --workload=<YOUR_WORKLOAD> \
  --target-host="localhost:8983" \
  --test-mode
```

**Run without test mode:**
```bash
solr-benchmark run \
  --pipeline=benchmark-only \
  --workload=<YOUR_WORKLOAD> \
  --target-host="<SOLR HOST:PORT>"
```

**Run with distribution provisioning:**
```bash
solr-benchmark run \
  --pipeline=solr-from-distribution \
  --distribution-version=9.7.0 \
  --workload=<YOUR_WORKLOAD> \
  --test-mode
```

4. To test the installed binary path explicitly:
   ```bash
   which solr-benchmark   # e.g. /home/user/.pyenv/shims/solr-benchmark
   bash /home/user/.pyenv/shims/solr-benchmark run --pipeline=benchmark-only ...
   ```

## Creating a pull request

After testing, open a PR. Once merged, create and push a version tag to
trigger the release pipeline:

```bash
git tag <NEW MAJOR.MINOR.PATCH VERSION> main
git push origin <NEW MAJOR.MINOR.PATCH VERSION>
```
