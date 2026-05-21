# Developer Guide

This document walks you through what's needed to start contributing code to
Apache Solr Benchmark.

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

- **Python 3.9+**: Use [pyenv](https://github.com/pyenv/pyenv) to manage
  Python versions.

  Debian/Ubuntu:
  ```bash
  sudo apt-get install -y make build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev \
    xz-utils tk-dev libffi-dev liblzma-dev git
  ```

  macOS:
  ```bash
  xcode-select --install
  brew install pyenv jq zlib xz
  ```

- **Docker** (optional): required for the `docker` pipeline.
  Install Docker and confirm `docker ps` works.

- **Git 1.9+**

## Setup

Fork and clone the repository, then install in development mode:

```bash
cd solr-benchmark   # (or your fork directory)
make develop
```

Activate the virtual environment:

| Platform | Shell | Command |
|----------|-------|---------|
| Posix | bash/zsh | `source .venv/bin/activate` |
| | fish | `source .venv/bin/activate.fish` |
| | csh/tcsh | `source .venv/bin/activate.csh` |
| Windows | cmd.exe | `.venv\Scripts\activate.bat` |
| | PowerShell | `.venv\Scripts\Activate.ps1` |

## Importing the Project into an IDE

The project uses a virtualenv created by `make develop`. In PyCharm:

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
solr-benchmark execute-test \
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
python -m pytest tests/unit/solr/ -v
```

### Integration tests

Integration tests require a running Solr instance (local or Docker).

```bash
make it
```

## Submitting a Pull Request

1. **Run tests**: `make test` (and `make it` if applicable).
2. **Sign commits** with DCO: `git commit -s`.
3. **Rebase** onto the latest `main` before opening a PR.
4. Open the PR, referencing the related issue (`Closes #123`).
5. Respond to review comments; squash commits if asked.

## Developing Breaking Changes

Develop breaking changes in a dedicated feature branch. Rebase onto `main`
before the next release and merge at that point.

## Miscellaneous

### Avoiding secrets in commits

Install [git-secrets](https://github.com/awslabs/git-secrets) to prevent
accidentally committing credentials:

```bash
git clone https://github.com/awslabs/git-secrets.git
cd git-secrets && make install
```

### Developer mode (quick iteration)

```bash
python3 -m pip install -e .
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
