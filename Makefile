# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

SHELL = /bin/bash
UV_ERROR = "\033[0;31mIMPORTANT\033[0m: Please install uv — see https://docs.astral.sh/uv/getting-started/installation/\n"

all: develop

check-uv:
	@which uv > /dev/null 2>&1 || { printf $(UV_ERROR); exit 1; }

check-java:
	@if ! test "$(JAVA21_HOME)" || ! java --version > /dev/null 2>&1 || ! javadoc --help > /dev/null 2>&1; then \
	    echo "Java installation issues for running integration tests" >&2; \
	    exit 1; \
	fi
	@if test `java --version | sed -n 's/[^0-9]*\([0-9]*\).*./\1/p;q'` != 17; then \
	    echo "NOTE: Java version 17 required to have all integration tests pass" >&2; \
	fi

develop: check-uv
	uv sync --extra develop

build: check-uv
	uv build

# Builds a wheel from source, then installs it as a uv tool (isolated env, binaries on PATH).
install: build
	uv tool install --force --reinstall dist/*.whl
	rm -rf dist

clean:
	rm -rf .benchmarks .eggs .tox .benchmark_it .cache build dist *.egg-info logs junit-py*.xml *.whl NOTICE.txt THIRD_PARTY.table THIRD_PARTY.next

# Avoid conflicts between .pyc/pycache related files created by local Python interpreters and other interpreters in Docker
python-caches-clean:
	-@find . -name "__pycache__" -prune -exec rm -rf -- \{\} \;
	-@find . -name ".pyc" -prune -exec rm -rf -- \{\} \;

tox-env-clean:
	rm -rf .tox

lint: develop
	uv run ruff check .
	# uv run ruff format --check .  # uncomment once the codebase has been formatted

test: develop
	uv run pytest tests/

it: check-uv check-java python-caches-clean tox-env-clean
	uv run --extra develop tox

it312 it313: check-uv check-java python-caches-clean tox-env-clean
	uv run --extra develop tox -e $(@:it%=py%)

benchmark: develop
	uv run pytest benchmarks/

coverage: develop
	uv run coverage run -m pytest tests/
	uv run coverage html

# Regenerates the dependency table in THIRD_PARTY.md from the runtime dependencies, leaving the
# hand-maintained sections above the marker untouched. --isolated runs in a fresh environment
# without the develop/test extras, so tools like pytest and ruff stay out of the list.
# --with-system keeps setuptools and wheel, which pip-licenses otherwise drops even though wheel
# is a declared runtime dependency; pip-licenses and its own dependencies are ignored instead.
licenses: check-uv
	@grep -q GENERATED-TABLE-BELOW THIRD_PARTY.md || { echo "THIRD_PARTY.md has no GENERATED-TABLE-BELOW marker; refusing to overwrite it" >&2; exit 1; }
	uv run --isolated --with pip-licenses pip-licenses --with-authors --with-urls --with-system \
	    --format=markdown --ignore-packages solr-orbit pip-licenses prettytable wcwidth \
	    --output-file THIRD_PARTY.table
	@awk '{ print } index($$0, "GENERATED-TABLE-BELOW") { exit }' THIRD_PARTY.md > THIRD_PARTY.next
	@echo >> THIRD_PARTY.next
	@cat THIRD_PARTY.table >> THIRD_PARTY.next
	@mv THIRD_PARTY.next THIRD_PARTY.md
	@rm -f THIRD_PARTY.table

release-checks:
	./release-checks.sh $(release_version) $(next_version)

# usage: e.g. make release release_version=0.9.2 next_version=0.9.3
release: release-checks clean it
	./release.sh $(release_version) $(next_version)

.PHONY: install clean python-caches-clean tox-env-clean test it it312 it313 benchmark coverage licenses release release-checks check-uv
