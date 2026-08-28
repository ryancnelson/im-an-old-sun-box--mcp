"""Typed host registry and QEMU console argument parsing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Literal

Platform = Literal["linux", "darwin", "illumos"]

_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HOST_KEYS = {
    "id",
    "label",
    "platform",
    "ssh_target",
    "local",
    "allowed_socket_roots",
    "lifecycle_argv",
    "discovery_timeout_seconds",
    "connect_timeout_seconds",
}


@dataclass(frozen=True)
class ConsoleHost:
    host_id: str
    label: str
    platform: Platform
    ssh_target: str | None
    allowed_socket_roots: tuple[PurePosixPath, ...]
    lifecycle_argv: tuple[str, ...] | None = None
    discovery_timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 5.0

    def allows(self, path: PurePosixPath) -> bool:
        """Return whether *path* is lexically inside an allowlisted root."""
        if not path.is_absolute() or ".." in path.parts:
            return False
        return any(path == root or root in path.parents for root in self.allowed_socket_roots)


@dataclass(frozen=True)
class QemuProcess:
    pid: int
    started_at: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ConsoleTarget:
    target_id: str
    host_id: str
    socket_path: PurePosixPath
    pid: int
    started_at: str
    command: str
    qemu_name: str | None
    socket_mtime: float | None

    @classmethod
    def create(
        cls,
        *,
        host_id: str,
        socket_path: PurePosixPath,
        pid: int,
        started_at: str,
        command: str,
        qemu_name: str | None,
        socket_mtime: float | None,
    ) -> "ConsoleTarget":
        identity = f"{host_id}\0{pid}\0{started_at}\0{socket_path}".encode()
        target_id = hashlib.sha256(identity).hexdigest()[:24]
        return cls(target_id, host_id, socket_path, pid, started_at, command, qemu_name, socket_mtime)


def _option_values(argv: tuple[str, ...], option: str) -> tuple[str, ...]:
    values: list[str] = []
    for index, value in enumerate(argv[:-1]):
        if value == option:
            values.append(argv[index + 1])
    return tuple(values)


def _comma_fields(value: str) -> tuple[str, dict[str, str]]:
    fields = value.split(",")
    parsed: dict[str, str] = {}
    for field in fields[1:]:
        key, separator, item = field.partition("=")
        if separator:
            parsed[key] = item
    return fields[0], parsed


def parse_console_paths(argv: tuple[str, ...] | list[str]) -> tuple[PurePosixPath, ...]:
    """Extract Unix sockets used by QEMU serial devices from an argv vector."""
    arguments = tuple(argv)
    chardevs: dict[str, PurePosixPath] = {}
    for definition in _option_values(arguments, "-chardev"):
        backend, fields = _comma_fields(definition)
        if backend == "socket" and fields.get("id") and fields.get("path"):
            chardevs[fields["id"]] = PurePosixPath(fields["path"])

    paths: list[PurePosixPath] = []
    for serial in _option_values(arguments, "-serial"):
        if serial.startswith("unix:"):
            paths.append(PurePosixPath(serial.removeprefix("unix:").split(",", 1)[0]))
        elif serial.startswith("chardev:"):
            path = chardevs.get(serial.removeprefix("chardev:"))
            if path is not None:
                paths.append(path)

    return tuple(dict.fromkeys(paths))


def parse_qemu_name(argv: tuple[str, ...] | list[str]) -> str | None:
    values = _option_values(tuple(argv), "-name")
    if not values:
        return None
    name, _ = _comma_fields(values[-1])
    return name or None


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{field} must be a positive number")
    return float(value)


def parse_hosts_json(payload: str) -> tuple[ConsoleHost, ...]:
    """Parse a strict JSON console-host registry."""
    try:
        raw_hosts = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("host registry must be valid JSON") from exc
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise ValueError("host registry must be a non-empty JSON array")

    hosts: list[ConsoleHost] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_hosts):
        if not isinstance(raw, dict):
            raise ValueError(f"host registry entry {index} must be an object")
        unknown = set(raw) - _HOST_KEYS
        if unknown:
            raise ValueError(f"unknown host registry keys: {', '.join(sorted(unknown))}")

        host_id = raw.get("id")
        if not isinstance(host_id, str) or not _HOST_ID.fullmatch(host_id):
            raise ValueError("host id must contain only letters, digits, dots, dashes, and underscores")
        if host_id in seen:
            raise ValueError(f"duplicate host id: {host_id}")
        seen.add(host_id)

        label = raw.get("label", host_id)
        if not isinstance(label, str) or not label:
            raise ValueError(f"host {host_id} label must be a non-empty string")
        platform = raw.get("platform")
        if platform not in {"linux", "darwin", "illumos"}:
            raise ValueError(f"host {host_id} has unsupported platform")

        local = raw.get("local", False)
        if not isinstance(local, bool):
            raise ValueError(f"host {host_id} local must be a boolean")
        ssh_target = raw.get("ssh_target")
        if local:
            if ssh_target is not None:
                raise ValueError(f"local host {host_id} cannot define ssh_target")
            ssh_target = None
        elif not isinstance(ssh_target, str) or not ssh_target:
            raise ValueError(f"remote host {host_id} requires ssh_target")

        raw_roots = raw.get("allowed_socket_roots")
        if not isinstance(raw_roots, list) or not raw_roots or not all(isinstance(item, str) for item in raw_roots):
            raise ValueError(f"host {host_id} allowed_socket_roots must be a non-empty string array")
        roots = tuple(PurePosixPath(item) for item in raw_roots)
        if any(not root.is_absolute() or ".." in root.parts for root in roots):
            raise ValueError(f"host {host_id} socket roots must be absolute without parent traversal")

        raw_lifecycle = raw.get("lifecycle_argv")
        lifecycle: tuple[str, ...] | None = None
        if raw_lifecycle is not None:
            if not isinstance(raw_lifecycle, list) or not raw_lifecycle or not all(
                isinstance(item, str) and item for item in raw_lifecycle
            ):
                raise ValueError(f"host {host_id} lifecycle_argv must be a non-empty string array")
            lifecycle = tuple(raw_lifecycle)

        discovery_timeout = _positive_number(raw.get("discovery_timeout_seconds", 5.0), "discovery timeout")
        connect_timeout = _positive_number(raw.get("connect_timeout_seconds", 5.0), "connect timeout")
        hosts.append(
            ConsoleHost(
                host_id=host_id,
                label=label,
                platform=platform,
                ssh_target=ssh_target,
                allowed_socket_roots=roots,
                lifecycle_argv=lifecycle,
                discovery_timeout_seconds=discovery_timeout,
                connect_timeout_seconds=connect_timeout,
            )
        )
    return tuple(hosts)
