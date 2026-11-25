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
"""Provision real EC2 instances, then destroy them.

**This spends money.** Opt in explicitly::

    LAUNCHR_IT_AWS=1 AWS_PROFILE=pulumi \\
      pytest tests/tools/launchr/ec2_integration_test.py -v -s

The stub tests next door assert that launchr makes the right API calls. They
cannot tell you whether an instance actually boots, whether cloud-init
finishes, whether SSH works with the generated key, or whether teardown
really removes everything -- which is the part that costs money when it is
wrong. That is what this is for.

Deliberately the smallest thing that proves the lifecycle: one Solr node and
one driver on the cheapest sensible instance type, no Solr deployed, no
benchmark run. Roughly two minutes and a few cents.

Every test tears down in a ``finally``, and the last test asserts the account
has no launchr-tagged instances left -- so a bug in teardown fails the suite
rather than quietly billing.
"""

import os

import pytest

from solrorbit.tools.launchr import ledger
from solrorbit.tools.launchr import teardown as reclaim
from solrorbit.tools.launchr.models import ProfileSpec
from solrorbit.tools.launchr.provisioning.ec2 import Ec2Provisioning, aws
from solrorbit.tools.launchr.provisioning.ec2.ssh import SshSession
from solrorbit.tools.launchr.storage import LocalStorageBackend

pytestmark = pytest.mark.skipif(
    not os.environ.get("LAUNCHR_IT_AWS"),
    reason="set LAUNCHR_IT_AWS=1 to provision real EC2 instances",
)

REGION = os.environ.get("LAUNCHR_IT_AWS_REGION", "eu-north-1")
AWS_PROFILE = os.environ.get("LAUNCHR_IT_AWS_PROFILE", "pulumi")

#: Small on purpose. This test proves the lifecycle, not the hardware.
IT_OPTIONS = {
    "region": REGION,
    "aws_profile": AWS_PROFILE,
    "instance_type": "t3.small",
    "driver_instance_type": "t3.small",
    "volume_gb": 20,
    "driver_volume_gb": 20,
}


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "results")


@pytest.fixture
def profile():
    return ProfileSpec(
        name="it-ec2", provisioning="ec2", install_method="docker-ssh",
        nodes=1, port=8983, startup_timeout=600, options=IT_OPTIONS,
    )


@pytest.fixture
def ec2():
    return aws.client("ec2", region=REGION, profile=AWS_PROFILE)


class TestProvisionAndTeardown:
    def test_the_full_lifecycle(self, storage, profile, ec2):
        strategy = Ec2Provisioning(storage=storage, session_id="it")
        infra = None
        try:
            infra = strategy.provision(profile, nodes=1)
            stack_id = infra.handles["stack_id"]

            # -- what provisioning must have produced ----------------------
            assert len(infra.nodes) == 1
            assert infra.driver is not None
            assert infra.driver.ssh is not None

            node = infra.nodes[0]
            assert node.endpoint.port == 8983
            # Solr is addressed on the private IP: routing load over the
            # public interface would measure the internet gateway.
            assert node.endpoint.host.startswith(("10.", "172.", "192.168."))
            assert node.ssh.host != node.endpoint.host

            # -- the ledger recorded it before creating anything -----------
            entry = ledger.leaked(storage)[0]
            assert entry.stack_id == stack_id
            assert entry.region == REGION
            assert len(entry.instance_ids()) == 2  # one Solr node plus the driver

            # -- SSH actually works with the generated key -----------------
            known_hosts = infra.handles["known_hosts"]
            for handle in (node, infra.driver):
                session = SshSession(handle.ssh, known_hosts=known_hosts)
                assert session.run(["echo", "alive"]).stdout.strip() == "alive"

            # -- cloud-init finished, so the tools are really there --------
            solr_session = SshSession(node.ssh, known_hosts=known_hosts)
            docker = solr_session.run(["docker", "--version"], check=False)
            assert docker.ok, f"Docker missing on the Solr node: {docker.stderr}"

            driver_session = SshSession(infra.driver.ssh, known_hosts=known_hosts)
            uv = driver_session.run(
                f"/home/{infra.driver.ssh.user}/.local/bin/uv --version", check=False)
            assert uv.ok, f"uv missing on the driver: {uv.stderr}"

            # Solr Orbit clones the workloads repository with `git clone`, so
            # a driver without git fails every run at workload load.
            git = driver_session.run(["git", "--version"], check=False)
            assert git.ok, f"git missing on the driver: {git.stderr}"

            # -- the instances are tagged, which is what teardown needs ----
            described = aws.describe(ec2, entry.instance_ids())
            for instance in described:
                tags = {t["Key"]: t["Value"] for t in instance["Tags"]}
                assert tags[aws.TAG_MANAGED] == "true"
                assert tags[aws.TAG_SESSION] == stack_id
                assert tags["project"] == "solr"
        finally:
            if infra is not None:
                strategy.teardown(infra)

        # -- teardown really removed everything ---------------------------
        assert ledger.leaked(storage) == [], "the ledger still reports a leak"
        states = {i["State"]["Name"] for i in aws.describe(ec2, entry.instance_ids())}
        assert states <= {"terminated", "shutting-down"}, f"instances survived: {states}"
        assert stack_id not in aws.find_sessions(ec2)

    def test_reconcile_reclaims_a_leak(self, storage, profile, ec2):
        """The crashed-orchestrator case: provision, lose the handle, recover."""
        strategy = Ec2Provisioning(storage=storage, session_id="itleak")
        infra = strategy.provision(profile, nodes=1)
        stack_id = infra.handles["stack_id"]
        instance_ids = ledger.leaked(storage)[0].instance_ids()
        try:
            # Simulate the crash: the process that held `infra` is gone, and
            # nothing local remembers the stack. Only tags and the ledger do.
            del infra

            result = reclaim.reconcile(storage, regions=[], aws_profile=AWS_PROFILE)
            assert stack_id in result.terminated
            assert ledger.leaked(storage) == []
        finally:
            # Belt and braces: if reconcile failed, do not leave them running.
            aws.terminate(ec2, instance_ids, wait=False)

        states = {i["State"]["Name"] for i in aws.describe(ec2, instance_ids)}
        assert states <= {"terminated", "shutting-down"}


class TestNothingLeftBehind:
    """Runs last. A leak here means the suite itself is costing money."""

    def test_the_account_has_no_launchr_instances(self, ec2):
        remaining = aws.find_sessions(ec2)
        assert not remaining, (
            f"launchr-tagged instances are still running in {REGION}: "
            f"{ {k: [i['InstanceId'] for i in v] for k, v in remaining.items()} }. "
            f"Run: launchr teardown --config examples/launchr-ec2.yaml"
        )
