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
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging

from solrorbit import exceptions
from solrorbit.utils import jvm


def java_home(cluster_config_runtime_jdks, specified_runtime_jdk=None):
    def determine_runtime_jdks():
        if specified_runtime_jdk:
            return [specified_runtime_jdk]
        else:
            return allowed_runtime_jdks

    def detect_jdk(jdks):
        major, java_home = jvm.resolve_path(jdks)
        logger.info("Detected JDK with major version [%s] in [%s].", major, java_home)
        return major, java_home

    logger = logging.getLogger(__name__)

    try:
        allowed_runtime_jdks = [int(v) for v in cluster_config_runtime_jdks.split(",")]

    except ValueError:
        raise exceptions.SystemSetupError(
            "ClusterConfigInstance config key \"runtime.jdk\" is invalid: \"{}\" (must be int)".format(
                cluster_config_runtime_jdks))

    runtime_jdk_versions = determine_runtime_jdks()

    logger.info("Allowed JDK versions are %s.", runtime_jdk_versions)
    return detect_jdk(runtime_jdk_versions)
