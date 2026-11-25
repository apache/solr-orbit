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
"""The EC2 calls launchr makes, and nothing else.

Deliberately thin and free of launchr's own types, so the provisioning
strategy above it reads as a lifecycle rather than as AWS trivia, and so these
can be tested against a stub client.

**Everything created here carries the session tag.** That is not bookkeeping:
it is the only thing standing between a crashed orchestrator and an instance
that bills until someone notices. ``launchr teardown`` finds orphans by tag
alone, with no state file to lose, which is why there is no state file.
"""

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

from solrorbit.tools.launchr.errors import ProvisioningError

logger = logging.getLogger(__name__)

#: Tag marking everything launchr created. Queried by teardown.
TAG_MANAGED = "launchr"
#: Tag carrying the session id, so one run's resources can be found alone.
TAG_SESSION = "launchr-session"
#: Tag carrying the profile, for cost attribution per hardware shape.
TAG_PROFILE = "launchr-profile"
#: Tag naming what an instance is for: ``driver`` or ``solr``.
TAG_ROLE = "launchr-role"

#: AL2023 is the default because it is current, has a predictable `dnf`, and
#: ships cloud-init -- which is how launchr knows user-data finished.
DEFAULT_AMI_PATTERN = "al2023-ami-2023.*-kernel-6.*-x86_64"
AMAZON_OWNER = "137112412989"

#: Ports open *within* the security group. Solr HTTP, the embedded-ZK port
#: Solr listens on, and standalone ZooKeeper's client port.
INTERNAL_PORTS = (8983, 9983, 2181)

_POLL_INTERVAL = 5


@dataclass
class Instance:
    """One running EC2 instance."""

    instance_id: str
    role: str
    name: str
    private_ip: str
    public_ip: str | None
    availability_zone: str
    instance_type: str
    ami: str

    @property
    def ssh_host(self) -> str:
        """Where launchr administers it from outside the VPC."""
        if not self.public_ip:
            raise ProvisioningError(
                f"{self.name} ({self.instance_id}) has no public address, so launchr cannot "
                f"reach it. Use a subnet that assigns public IPs, or add a bastion."
            )
        return self.public_ip


def tags_for(session_id: str, profile: str, **extra: str) -> list[dict]:
    """The tag set every created resource carries."""
    tags = {
        "Name": f"launchr-{session_id}",
        TAG_MANAGED: "true",
        TAG_SESSION: session_id,
        TAG_PROFILE: profile,
        # The account's cost reporting keys off `project`; a resource without
        # it is invisible in the per-project budget.
        "project": "solr",
        "managed_by": "launchr",
    }
    tags.update({k: v for k, v in extra.items() if v})
    return [{"Key": k, "Value": str(v)} for k, v in tags.items()]


def client(service: str, *, region: str, profile: str | None = None):
    """A boto3 client, with a clear error when credentials are missing."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is a core dependency
        raise ProvisioningError("The ec2 provisioning strategy needs boto3.") from exc
    try:
        session = boto3.session.Session(
            profile_name=profile or None, region_name=region,
        )
        return session.client(service)
    except Exception as exc:
        raise ProvisioningError(
            f"Could not create an AWS {service} client in {region}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def latest_ami(ec2, *, pattern: str = DEFAULT_AMI_PATTERN) -> str:
    """Newest Amazon-owned AMI matching ``pattern``.

    Resolved rather than pinned, and then *recorded* in the report. A pinned
    AMI is better for comparing runs months apart -- the plan's Packer image --
    but an unpinned one that is written down still lets a reader tell whether
    two results shared a kernel.
    """
    response = ec2.describe_images(
        Owners=[AMAZON_OWNER],
        Filters=[
            {"Name": "name", "Values": [pattern]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
            {"Name": "root-device-type", "Values": ["ebs"]},
        ],
    )
    images = sorted(response.get("Images", []), key=lambda i: i["CreationDate"], reverse=True)
    if not images:
        raise ProvisioningError(f"No AMI matched {pattern!r}; set options.ami explicitly.")
    chosen = images[0]
    logger.info("Resolved AMI %s (%s)", chosen["ImageId"], chosen.get("Name"))
    return chosen["ImageId"]


def default_subnet(ec2, *, availability_zone: str | None = None) -> tuple[str, str, str]:
    """Pick one subnet, returning ``(subnet_id, vpc_id, availability_zone)``.

    One subnet, so every instance in a run shares an availability zone. Two
    Solr nodes in different AZs would add inter-AZ latency to every replica
    operation and quietly make the numbers incomparable with a single-AZ run.
    """
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}]).get("Vpcs", [])
    if not vpcs:
        raise ProvisioningError(
            "No default VPC in this region, and launchr does not create one. "
            "Set options.subnet_id to a subnet that assigns public IPs."
        )
    vpc_id = vpcs[0]["VpcId"]

    filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
    if availability_zone:
        filters.append({"Name": "availability-zone", "Values": [availability_zone]})
    subnets = ec2.describe_subnets(Filters=filters).get("Subnets", [])
    if not subnets:
        raise ProvisioningError(f"No subnet in {vpc_id}" + (f" / {availability_zone}" if availability_zone else ""))
    # Deterministic: the same region picks the same subnet run after run, so
    # results are comparable without anyone pinning it by hand.
    chosen = sorted(subnets, key=lambda s: s["SubnetId"])[0]
    return chosen["SubnetId"], vpc_id, chosen["AvailabilityZone"]


def subnet_details(ec2, subnet_id: str) -> tuple[str, str]:
    """Return ``(vpc_id, availability_zone)`` for an explicitly configured subnet."""
    subnets = ec2.describe_subnets(SubnetIds=[subnet_id]).get("Subnets", [])
    if not subnets:
        raise ProvisioningError(f"Subnet {subnet_id} not found")
    return subnets[0]["VpcId"], subnets[0]["AvailabilityZone"]


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def create_security_group(ec2, *, vpc_id: str, session_id: str, profile: str,
                          ssh_cidrs: list[str], admin_ports: tuple[int, ...] = ()) -> str:
    """A group allowing control traffic from ``ssh_cidrs``, and Solr/ZK within itself.

    ``ssh_cidrs`` is the orchestrator's own address plus whatever ranges the
    profile adds. More than one matters because the first entry is a snapshot
    of a value that moves: a laptop's public address can change mid-run, and
    when it does a `/32` rule silently stops matching and an hours-long
    benchmark dies at the transport layer with nothing wrong with it.

    ``admin_ports`` are opened to the same ranges -- the orchestrator sits
    outside the VPC and has to health-check Solr before it will start a
    benchmark. A deliberate, bounded exposure: named ranges only, an
    ephemeral cluster holding no data, for the length of one run. It also
    means the admin UI is reachable while debugging a failing cell.
    """
    name = f"launchr-{session_id}"
    group_id = ec2.create_security_group(
        GroupName=name,
        Description=f"launchr benchmark session {session_id}",
        VpcId=vpc_id,
        TagSpecifications=[{"ResourceType": "security-group",
                            "Tags": tags_for(session_id, profile)}],
    )["GroupId"]
    logger.info("Created security group %s (%s)", group_id, name)

    permissions: list[dict] = [
        {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
         "IpRanges": [{"CidrIp": c, "Description": "launchr control"} for c in ssh_cidrs]}
        for port in (22, *admin_ports)
    ]
    # Self-referencing rules: the driver and the Solr nodes are all in this
    # group, so this is what lets the driver reach Solr and the Solr nodes
    # reach ZooKeeper, without opening anything to the internet.
    permissions += [
        {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
         "UserIdGroupPairs": [{"GroupId": group_id, "Description": "launchr internal"}]}
        for port in INTERNAL_PORTS
    ]
    ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=permissions)
    return group_id


def create_key_pair(ec2, *, session_id: str, profile: str) -> tuple[str, str]:
    """Create an ephemeral key pair, returning ``(name, private_key_pem)``.

    AWS generates it, so no key material is ever written to a config file or a
    state store. The caller holds the PEM for the life of the run and deletes
    it at teardown; losing it means losing SSH access to that run's instances,
    which is the correct failure -- the instances are disposable.
    """
    name = f"launchr-{session_id}"
    response = ec2.create_key_pair(
        KeyName=name, KeyType="ed25519",
        TagSpecifications=[{"ResourceType": "key-pair",
                            "Tags": tags_for(session_id, profile)}],
    )
    logger.info("Created ephemeral key pair %s", name)
    return name, response["KeyMaterial"]


#: Where a dedicated data volume is attached. The kernel renames it (on Nitro
#: instances it appears as /dev/nvme1n1), so nothing may depend on this name
#: beyond the API call -- the user-data finds the disk by "the one with no
#: filesystem", not by path.
DATA_DEVICE = "/dev/sdb"


def _block_devices(volume_gb: int, volume_type: str,
                   data_volume: dict | None) -> list[dict]:
    """Root volume, plus a dedicated data volume when one is configured.

    ``DeleteOnTermination`` is true on both. That is what makes teardown
    whole: a volume that outlives its instance is a billing line with nothing
    attached to explain it, and the tag sweep is only a backstop for when
    termination itself did not happen.
    """
    devices = [{
        "DeviceName": "/dev/xvda",
        "Ebs": {"VolumeSize": int(volume_gb), "VolumeType": volume_type,
                "DeleteOnTermination": True},
    }]
    if data_volume:
        ebs: dict[str, Any] = {
            "VolumeSize": int(data_volume["size_gb"]),
            "VolumeType": data_volume.get("type", "gp3"),
            "DeleteOnTermination": True,
        }
        # gp3 bills provisioned IOPS and throughput above the 3000/125
        # baseline; io1/io2 take IOPS only. Sending either to a type that
        # does not accept it is an API error, so only pass what was asked for.
        if data_volume.get("iops"):
            ebs["Iops"] = int(data_volume["iops"])
        if data_volume.get("throughput_mbps"):
            ebs["Throughput"] = int(data_volume["throughput_mbps"])
        devices.append({"DeviceName": DATA_DEVICE, "Ebs": ebs})
    return devices


def run_instances(ec2, *, count: int, role: str, name_prefix: str, instance_type: str,
                  ami: str, subnet_id: str, security_group_id: str, key_name: str,
                  user_data: str, volume_gb: int, session_id: str, profile: str,
                  volume_type: str = "gp3", data_volume: dict | None = None) -> list[str]:
    """Launch instances and return their ids."""
    response = ec2.run_instances(
        ImageId=ami,
        InstanceType=instance_type,
        MinCount=count, MaxCount=count,
        KeyName=key_name,
        UserData=base64.b64encode(user_data.encode()).decode(),
        NetworkInterfaces=[{
            "DeviceIndex": 0,
            "SubnetId": subnet_id,
            "Groups": [security_group_id],
            # launchr drives these over the public internet; without this the
            # default subnet's auto-assign setting decides, and a subnet with
            # it off yields instances nothing can reach.
            "AssociatePublicIpAddress": True,
            "DeleteOnTermination": True,
        }],
        BlockDeviceMappings=_block_devices(volume_gb, volume_type, data_volume),
        TagSpecifications=[
            {"ResourceType": resource,
             "Tags": tags_for(session_id, profile, **{TAG_ROLE: role, "Name": name_prefix})}
            for resource in ("instance", "volume")
        ],
    )
    ids = [i["InstanceId"] for i in response["Instances"]]
    logger.info("Launched %d %s instance(s) (%s): %s", count, role, instance_type, ", ".join(ids))
    return ids


def wait_until_running(ec2, instance_ids: list[str], *, timeout: int = 600) -> list[dict]:
    """Block until every instance is running with an address, then describe them."""
    deadline = time.monotonic() + timeout
    while True:
        described = describe(ec2, instance_ids)
        states = {i["State"]["Name"] for i in described}
        if states - {"running"}:
            bad = states & {"terminated", "shutting-down", "stopped"}
            if bad:
                raise ProvisioningError(
                    f"Instance(s) entered {', '.join(sorted(bad))} before becoming usable: "
                    f"{', '.join(instance_ids)}"
                )
        elif all(i.get("PublicIpAddress") for i in described):
            return described
        if time.monotonic() > deadline:
            raise ProvisioningError(
                f"Instances were not running with a public address within {timeout}s: "
                f"{', '.join(instance_ids)} (states: {', '.join(sorted(states))})"
            )
        time.sleep(_POLL_INTERVAL)


def describe(ec2, instance_ids: list[str]) -> list[dict]:
    """Describe instances by id, flattened out of their reservations."""
    if not instance_ids:
        return []
    pages = ec2.get_paginator("describe_instances").paginate(InstanceIds=instance_ids)
    return [i for page in pages for r in page["Reservations"] for i in r["Instances"]]


def to_instance(described: dict, *, role: str, name: str) -> Instance:
    """Turn a describe_instances entry into an :class:`Instance`."""
    return Instance(
        instance_id=described["InstanceId"],
        role=role,
        name=name,
        private_ip=described.get("PrivateIpAddress", ""),
        public_ip=described.get("PublicIpAddress"),
        availability_zone=described.get("Placement", {}).get("AvailabilityZone", ""),
        instance_type=described.get("InstanceType", ""),
        ami=described.get("ImageId", ""),
    )


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def find_sessions(ec2) -> dict[str, list[dict]]:
    """Every live launchr-tagged instance, grouped by session id.

    The backstop for a crashed orchestrator: no state file is consulted, only
    the tags on what is actually running and billing.
    """
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[
            {"Name": f"tag:{TAG_MANAGED}", "Values": ["true"]},
            {"Name": "instance-state-name",
             "Values": ["pending", "running", "stopping", "stopped"]},
        ],
    )
    sessions: dict[str, list[dict]] = {}
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                sessions.setdefault(tags.get(TAG_SESSION, "unknown"), []).append(instance)
    return sessions


def terminate(ec2, instance_ids: list[str], *, wait: bool = True, timeout: int = 600) -> None:
    """Terminate instances, tolerating ones that are already gone."""
    if not instance_ids:
        return
    try:
        ec2.terminate_instances(InstanceIds=instance_ids)
    except Exception as exc:
        if "NotFound" not in str(exc):
            raise
        logger.debug("Some instances were already gone: %s", exc)
    logger.info("Terminating %s", ", ".join(instance_ids))
    if not wait:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            states = {i["State"]["Name"] for i in describe(ec2, instance_ids)}
        except Exception:  # noqa: BLE001 - a vanished instance is a terminated one
            return
        if not states or states <= {"terminated"}:
            return
        time.sleep(_POLL_INTERVAL)
    logger.warning("Instances were still terminating after %ds: %s", timeout, ", ".join(instance_ids))


def delete_security_group(ec2, group_id: str, *, attempts: int = 12) -> None:
    """Delete a security group once nothing is attached to it.

    A group cannot be deleted while an ENI still references it, and an ENI
    lingers for a while after its instance terminates. Retrying is the
    documented way through, and giving up leaks an empty group -- free, and
    reclaimable by the next ``launchr teardown``.
    """
    for attempt in range(1, attempts + 1):
        try:
            ec2.delete_security_group(GroupId=group_id)
            logger.info("Deleted security group %s", group_id)
            return
        except Exception as exc:
            if "NotFound" in str(exc):
                return
            if attempt == attempts:
                logger.warning(
                    "Could not delete security group %s after %d attempts: %s. "
                    "It is free to leave, and `launchr teardown` will retry.",
                    group_id, attempts, exc,
                )
                return
            time.sleep(_POLL_INTERVAL)


def delete_key_pair(ec2, key_name: str) -> None:
    """Delete an ephemeral key pair, tolerating one already gone."""
    try:
        ec2.delete_key_pair(KeyName=key_name)
        logger.info("Deleted key pair %s", key_name)
    except Exception as exc:  # noqa: BLE001 - teardown must never raise
        logger.warning("Could not delete key pair %s: %s", key_name, exc)


def tagged_security_groups(ec2) -> list[tuple[str, str]]:
    """launchr-tagged security groups, as ``(group_id, stack_id)``."""
    groups = ec2.describe_security_groups(
        Filters=[{"Name": f"tag:{TAG_MANAGED}", "Values": ["true"]}],
    ).get("SecurityGroups", [])
    return [(g["GroupId"], _session_of(g)) for g in groups]


def tagged_key_pairs(ec2) -> list[tuple[str, str]]:
    """launchr-tagged key pairs, as ``(key_name, stack_id)``."""
    pairs = ec2.describe_key_pairs(
        Filters=[{"Name": f"tag:{TAG_MANAGED}", "Values": ["true"]}],
    ).get("KeyPairs", [])
    return [(p["KeyName"], _session_of(p)) for p in pairs]


def _session_of(resource: dict) -> str:
    """The session tag on a described resource, or ``''``."""
    return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}.get(TAG_SESSION, "")
