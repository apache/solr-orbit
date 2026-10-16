# Developer Guide

This document walks you through what's needed to start contributing code to
Apache Solr Orbit.

### Table of Contents
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Importing the project into an IDE](#importing-the-project-into-an-ide)
- [Setting Up a Local Solr Instance (Optional)](#setting-up-a-local-solr-instance-optional)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Developing Breaking Changes](#developing-breaking-changes)
- [Miscellaneous](#miscellaneous)

## Prerequisites

- **uv**: unified Python toolchain (replaces pip, pyenv, and virtualenv).

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  Or via Homebrew: `brew install uv`

- **Docker** (optional): required for the `docker` pipeline.
  Install Docker and confirm `docker ps` works.

- **Git 1.9+**

## Setup

Fork and clone the repository, then install in development mode:

```bash
cd solr-orbit   # (or your fork directory)
make develop
```

This runs `uv sync --extra develop`, which:
1. Downloads Python 3.12 automatically if needed.
2. Creates `.venv` in the project root.
3. Installs all dependencies (pinned via `uv.lock`).

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Or prefix any command with `uv run` to use the project's venv without activating it:

```bash
uv run pytest tests/
```

## Importing the Project into an IDE

In PyCharm:

1. Go to *Settings → Python Interpreter*.
2. Select *Existing Environment*.
3. Point the interpreter to `.venv/bin/python3` inside the repository root.
4. In *Python Integrated Tools → Testing*, set the default runner to `pytest`.

## Setting Up a Local Solr Instance (Optional)

Download the latest Solr release from https://solr.apache.org/downloads.html:

```bash
wget https://downloads.apache.org/solr/solr/<version>/solr-<version>.tgz
tar -xf solr-<version>.tgz
cd solr-<version>
bin/solr start -c   # SolrCloud mode (recommended)
```

Verify Solr is running:

```bash
curl http://localhost:8983/api/node/system | python3 -m json.tool
```

### Running a workload against a local Solr cluster

```bash
solr-orbit execute-test \
  --pipeline=benchmark-only \
  --workload=<your-workload> \
  --target-host=localhost:8983
```

Logs are written to `~/.benchmark/logs/benchmark.log`.

## Running Tests

### Unit tests

```bash
make test
# or directly:
uv run pytest tests/ -v
```

### Integration tests

Integration tests require a running Solr instance (local or Docker).

```bash
make it
```

## Submitting a Pull Request

1. **Run tests**: `make test` (and `make it` if applicable).
2. **Rebase** onto the latest `main` before opening a PR.
3. Open the PR, referencing the related issue (`Closes #123`).
4. Respond to review comments; squash commits if asked.

## Developing Breaking Changes

Develop breaking changes in a dedicated feature branch. Rebase onto `main`
before the next release and merge at that point.

## Miscellaneous

### Updating dependencies

To add or change a dependency, edit `pyproject.toml` then run:

```bash
uv lock          # regenerate uv.lock
uv sync --extra develop   # update the local venv
```

Always commit both `pyproject.toml` and `uv.lock` together.

### Avoiding secrets in commits

Install [git-secrets](https://github.com/awslabs/git-secrets) to prevent
accidentally committing credentials:

```bash
git clone https://github.com/awslabs/git-secrets.git
cd git-secrets && make install
```

### Developer mode (quick iteration)

```bash
uv sync --extra develop
```

Changes to source files are reflected immediately on the next run.

### Debugging unit tests in Visual Studio Code

Add to your `launch.json`:

```json
{
    "name": "pytest (current file)",
    "type": "python",
    "request": "launch",
    "module": "pytest",
    "args": ["-k", "${file}"]
}
```
