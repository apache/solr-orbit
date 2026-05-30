# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging

from solrorbit.builder.utils.jdk_resolver import JdkResolver
from solrorbit.exceptions import SystemSetupError


class JavaHomeResolver:
    def __init__(self, executor):
        self.logger = logging.getLogger(__name__)
        self.executor = executor
        self.jdk_resolver = JdkResolver(executor)

    def resolve_java_home(self, host, cluster_config):
        runtime_jdks = cluster_config.variables["system"]["runtime"]["jdk"]["version"]

        try:
            allowed_runtime_jdks = [int(v) for v in runtime_jdks.split(",")]
        except ValueError:
            raise SystemSetupError(f'ClusterConfigInstance variable key "runtime.jdk" is invalid: "{runtime_jdks}" (must be int)')

        self.logger.info("Allowed JDK versions are %s.", allowed_runtime_jdks)
        return self._detect_jdk(host, allowed_runtime_jdks)

    def _detect_jdk(self, host, jdks):
        major, java_home = self.jdk_resolver.resolve_jdk_path(host, jdks)
        self.logger.info("Detected JDK with major version [%s] in [%s].", major, java_home)
        return major, java_home
