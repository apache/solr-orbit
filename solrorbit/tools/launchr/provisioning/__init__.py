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
"""Provisioning strategies.

``local`` and ``preconfigured`` create no infrastructure; ``ec2`` does. The
registry becomes Python entry points once a strategy needs to ship separately
from this package.
"""

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.provisioning.base import ProvisioningStrategy
from solrorbit.tools.launchr.provisioning.ec2 import Ec2Provisioning
from solrorbit.tools.launchr.provisioning.local import LocalProvisioning
from solrorbit.tools.launchr.provisioning.preconfigured import PreconfiguredProvisioning

REGISTRY: dict[str, type] = {
    Ec2Provisioning.name: Ec2Provisioning,
    LocalProvisioning.name: LocalProvisioning,
    PreconfiguredProvisioning.name: PreconfiguredProvisioning,
}

__all__ = [
    "ProvisioningStrategy",
    "Ec2Provisioning",
    "LocalProvisioning",
    "PreconfiguredProvisioning",
    "REGISTRY",
    "get_strategy",
    "available",
]


def available() -> list[str]:
    """Names of every registered provisioning strategy."""
    return sorted(REGISTRY)


def get_strategy(name: str, **kwargs) -> ProvisioningStrategy:
    """Instantiate a provisioning strategy by name.

    Unknown keyword arguments are dropped, so a strategy that creates nothing
    -- and therefore has no use for storage or a session id -- does not have
    to accept them.
    """
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ConfigError(
            f"Unknown provisioning strategy {name!r}. Available: {', '.join(available())}"
        ) from None
    import inspect

    accepted = inspect.signature(cls.__init__).parameters
    return cls(**{k: v for k, v in kwargs.items() if k in accepted})
