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

import it

@it.random_benchmark_config
def test_sources(cfg):
    port = it.free_port()
    # analysis-extras is Solr's home for the ICU analysis components that the
    # OpenSearch analysis-icu plugin provided, so this keeps the test's intent:
    # build from source with an extra module enabled.
    assert it.run_test(cfg, f"--pipeline=from-sources --revision=latest "
                        f"--workload=geonames --test-mode "
                        f"--test-procedure=append-no-conflicts --cluster-config=4gheap "
                        f"--solr-modules=analysis-extras --solr-port={port}") == 0

    port = it.free_port()
    assert it.run_test(cfg, f"--pipeline=from-sources --workload=geonames --test-mode "
                        f"--test-procedure=append-no-conflicts-index-only --cluster-config=\"4gheap,ea\" "
                        f"--solr-port={port}") == 0
