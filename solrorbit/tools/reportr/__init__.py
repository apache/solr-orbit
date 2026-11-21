# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""reportr — the Solr Orbit benchmark trends site generator.

reportr reads the enriched JSON reports that :mod:`solrorbit.tools.launchr`
writes to storage and emits a static site: per-workload data files plus a
single-page app that charts them. No backend, no database, nothing to operate.

See ``README.md`` in this package for the user-facing documentation.
"""

__all__ = ["__version__"]

from solrorbit.version import version as _orbit_version

__version__ = _orbit_version()
