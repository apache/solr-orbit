# SPDX-License-Identifier: Apache-2.0
#
# Originally developed by OpenSearch Contributors; licensed under the Apache License, Version 2.0.
# License header was absent in the original source; added when adopted into Apache Solr Orbit.
# Modified by Apache Solr contributors; see git log for details.
#
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
class GitManager:
    def __init__(self, executor):
        self.executor = executor

    def clone(self, host, remote_url, target_dir):
        self.executor.execute(host, f"git clone {remote_url} {target_dir}")

    def fetch(self, host, target_dir, remote="origin"):
        self.executor.execute(host, f"git -C {target_dir} fetch --prune --tags {remote}")

    def checkout(self, host, target_dir, branch="main"):
        self.executor.execute(host, f"git -C {target_dir} checkout {branch}")

    def rebase(self, host, target_dir, remote="origin", branch="main"):
        self.executor.execute(host, f"git -C {target_dir} rebase {remote}/{branch}")

    def get_revision_from_timestamp(self, host, target_dir, timestamp):
        get_revision_from_timestamp_command = f"git -C {target_dir} rev-list -n 1 --before=\"{timestamp}\" --date=iso8601 origin/main"

        return self.executor.execute(host, get_revision_from_timestamp_command, output=True)[0].strip()

    def get_revision_from_local_repository(self, host, target_dir):
        return self.executor.execute(host, f"git -C {target_dir} rev-parse --short HEAD", output=True)[0].strip()
