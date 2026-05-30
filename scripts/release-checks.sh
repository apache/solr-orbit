#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

set -euo pipefail
cd "$(dirname "$0")/.."

release_version=${1:-}
next_version=${2:-}

if [ -z "$release_version" ] || [ -z "$next_version" ]; then
    echo "Usage: $0 <release_version> <next_version>"
    echo "  e.g. $0 0.9.2 0.9.3"
    exit 1
fi

echo "Running release checks for version ${release_version} (next: ${next_version})"

echo "--- Apache RAT license audit ---"
make rat

echo "All release checks passed for version ${release_version}."
