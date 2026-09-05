"""Typed host registry and QEMU console argument parsing."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
from typing import Awaitable, Callable, Literal, Mapping

from .console_transport import ArgvConsoleConnector, ConsoleConnector, UnixConsoleConnector

Platform = Literal["linux", "darwin", "illumos"]

_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HOST_KEYS = {
    "id",
    "label",
    "platform",
    "ssh_target",
    "local",
    "allowed_socket_roots",
    "allowed_tcp_ports",
    "lifecycle_argv",
    "discovery_timeout_seconds",
    "connect_timeout_seconds",
    "docker_container_prefixes",
    "docker_socket_roots",
}


@dataclass(frozen=True)
class ConsoleHost:
    host_id: str
    label: str
    platform: Platform
    ssh_target: str | None
    allowed_socket_roots: tuple[PurePosixPath, ...]
    allowed_tcp_ports: tuple[int, ...] = ()
    lifecycle_argv: tuple[str, ...] | None = None
    discovery_timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 5.0
    docker_container_prefixes: tuple[str, ...] = ()
    docker_socket_roots: tuple[PurePosixPath, ...] = ()

    def allows_docker(self, name: str, path: PurePosixPath) -> bool:
        return (bool(self.docker_container_prefixes) and name.startswith(self.docker_container_prefixes)
                and path.is_absolute() and ".." not in path.parts
                and not any(c in str(path) for c in ("\0", "\n", "\r", ","))
                and any(path == root or root in path.parents for root in self.docker_socket_roots))

    def allows(self, path: PurePosixPath) -> bool:
        """Return whether *path* is lexically inside an allowlisted root."""
        if not path.is_absolute() or ".." in path.parts or any(character in str(path) for character in ("\0", "\n", "\r")):
            return False
        return any(path == root or root in path.parents for root in self.allowed_socket_roots)

    def allows_tcp(self, host: str, port: int) -> bool:
        """Allow only explicitly configured loopback TCP console ports."""
        return host in {"127.0.0.1", "localhost", "::1"} and port in self.allowed_tcp_ports


@dataclass(frozen=True)
class QemuProcess:
    pid: int
    started_at: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ConsoleTarget:
    target_id: str
    host_id: str
    socket_path: PurePosixPath | None
    pid: int
    started_at: str
    command: str
    qemu_name: str | None
    socket_mtime: float | None
    tcp_host: str | None = None
    tcp_port: int | None = None
    container_id: str | None = None
    container_name: str | None = None

    @property
    def endpoint(self) -> str:
        if self.container_id is not None:
            return f"docker://{self.container_id}{self.socket_path if self.socket_path is not None else '/stdio'}"
        if self.socket_path is not None:
            return str(self.socket_path)
        return f"tcp://{self.tcp_host}:{self.tcp_port}"

    @property
    def endpoint_kind(self) -> str:
        if self.container_id is not None:
            return "docker-unix" if self.socket_path is not None else "docker-stdio"
        return "unix" if self.socket_path is not None else "tcp"

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

    @classmethod
    def create_tcp(
        cls,
        *,
        host_id: str,
        tcp_host: str,
        tcp_port: int,
        pid: int,
        started_at: str,
        command: str,
        qemu_name: str | None,
    ) -> "ConsoleTarget":
        endpoint = f"tcp://{tcp_host}:{tcp_port}"
        identity = f"{host_id}\0{pid}\0{started_at}\0{endpoint}".encode()
        target_id = hashlib.sha256(identity).hexdigest()[:24]
        return cls(target_id, host_id, None, pid, started_at, command, qemu_name, None, tcp_host, tcp_port)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class DiscoveryError:
    kind: str
    message: str


@dataclass(frozen=True)
class DiscoveryReport:
    targets: tuple[ConsoleTarget, ...]
    errors: Mapping[str, DiscoveryError]


CommandRunner = Callable[[tuple[str, ...], bytes, float], Awaitable[CommandResult]]


_DISCOVERY_SCRIPTS: dict[Platform, bytes] = {
    "linux": b"""# OLD_SUN_DISCOVERY_V1 linux
for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue
    command=$(tr '\\000' ' ' < "$proc/cmdline")
    case "$command" in *qemu-system-*) ;; *) continue ;; esac
    pid=${proc##*/}
    started=$(ps -o lstart= -p "$pid" 2>/dev/null) || continue
    printf '%s\\t%s\\t%s\\n' "$pid" "$started" "$command"
done
""",
    "darwin": b"""# OLD_SUN_DISCOVERY_V1 darwin
ps -axo pid=,lstart=,command= | while read -r pid dow mon day clock year command; do
    case "$command" in *qemu-system-*|*qemu-*-softmmu*)
        printf '%s\\t%s %s %s %s %s\\t%s\\n' "$pid" "$dow" "$mon" "$day" "$clock" "$year" "$command"
        ;;
    esac
done
""",
    "illumos": b"""# OLD_SUN_DISCOVERY_V1 illumos
for pid in $(/usr/bin/pgrep -f qemu-system- 2>/dev/null); do
    command=$(/usr/bin/pargs -l "$pid" 2>/dev/null) || continue
    executable=${command%% *}
    case "${executable##*/}" in qemu-system-*) ;; *) continue ;; esac
    started=$(/usr/bin/ps -p "$pid" -o stime= 2>/dev/null) || continue
    [ -n "$started" ] || continue
    printf '%s\\t%s\\t%s\\n' "$pid" "$started" "$command"
done
""",
}

_SOCKET_CHECK_SCRIPTS: dict[Platform, bytes] = {
    "linux": b"""# OLD_SUN_SOCKET_CHECK_V1 linux
socket_dir=$(dirname "$socket_path") || exit 2
socket_base=$(basename "$socket_path") || exit 2
canonical_dir=$(cd "$socket_dir" 2>/dev/null && pwd -P) || exit 3
canonical_path=$canonical_dir/$socket_base
[ -S "$canonical_path" ] || exit 3
printf '%s\\t' "$canonical_path"
stat -c %Y -- "$canonical_path"
""",
    "darwin": b"""# OLD_SUN_SOCKET_CHECK_V1 darwin
socket_dir=$(dirname "$socket_path") || exit 2
socket_base=$(basename "$socket_path") || exit 2
canonical_dir=$(cd "$socket_dir" 2>/dev/null && pwd -P) || exit 3
canonical_path=$canonical_dir/$socket_base
[ -S "$canonical_path" ] || exit 3
printf '%s\\t' "$canonical_path"
stat -f %m "$canonical_path"
""",
    "illumos": b"""# OLD_SUN_SOCKET_CHECK_V1 illumos
socket_dir=$(dirname "$socket_path") || exit 2
socket_base=$(basename "$socket_path") || exit 2
canonical_dir=$(cd "$socket_dir" 2>/dev/null && pwd -P) || exit 3
canonical_path=$canonical_dir/$socket_base
[ -S "$canonical_path" ] || exit 3
printf '%s\\t0\\n' "$canonical_path"
""",
}


async def run_command(argv: tuple[str, ...], stdin: bytes, timeout: float) -> CommandResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    return CommandResult(process.returncode, stdout, stderr)


def parse_process_records(platform: str, output: str) -> tuple[QemuProcess, ...]:
    if platform not in {"linux", "darwin", "illumos"}:
        raise ValueError("unsupported process-record platform")
    records: list[QemuProcess] = []
    for line in output.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        raw_pid, started_at, command = fields
        try:
            pid = int(raw_pid)
            argv = tuple(shlex.split(command))
        except (ValueError, TypeError):
            continue
        if pid > 0 and started_at and argv:
            records.append(QemuProcess(pid, started_at.strip(), argv))
    return tuple(records)


class ConsoleDiscovery:
    def __init__(self, hosts: tuple[ConsoleHost, ...], runner: CommandRunner = run_command):
        self.hosts = hosts
        self._hosts = {host.host_id: host for host in hosts}
        self._runner = runner

    @staticmethod
    def _command(host: ConsoleHost) -> tuple[str, ...]:
        if host.ssh_target is None:
            return ("/bin/sh", "-s")
        timeout = max(1, int(host.connect_timeout_seconds))
        return (
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={timeout}",
            "-T",
            host.ssh_target,
            "/bin/sh",
            "-s",
        )

    async def _run(self, host: ConsoleHost, script: bytes, extra_stdin: bytes = b"") -> CommandResult:
        return await asyncio.wait_for(
            self._runner(self._command(host), script + extra_stdin, host.discovery_timeout_seconds),
            host.discovery_timeout_seconds,
        )

    async def _socket_validation(
        self, host: ConsoleHost, path: PurePosixPath
    ) -> tuple[PurePosixPath, float] | None:
        assignment = f"socket_path={shlex.quote(str(path))}\n".encode()
        script = _SOCKET_CHECK_SCRIPTS[host.platform]
        first_line, body = script.split(b"\n", 1)
        result = await self._run(host, first_line + b"\n" + assignment + body)
        if result.returncode != 0:
            return None
        try:
            line = result.stdout.decode().strip().splitlines()[-1]
            if "\t" in line:
                raw_path, raw_mtime = line.rsplit("\t", 1)
                canonical_path = PurePosixPath(raw_path)
            else:  # Retain compatibility with small external validation adapters.
                canonical_path, raw_mtime = path, line
            mtime = float(raw_mtime)
        except (ValueError, IndexError):
            return None
        if not host.allows(canonical_path):
            return None
        return canonical_path, mtime

    async def _discover_host(self, host: ConsoleHost) -> tuple[ConsoleTarget, ...]:
        result = await self._run(host, _DISCOVERY_SCRIPTS[host.platform])
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", "replace").strip()[-512:]
            raise RuntimeError(error or f"discovery command exited {result.returncode}")

        targets: list[ConsoleTarget] = []
        for process in parse_process_records(host.platform, result.stdout.decode("utf-8", "replace")):
            if not is_qemu_process(process.argv):
                continue
            command = shlex.join(process.argv)
            for path in parse_console_paths(process.argv):
                if not host.allows(path):
                    continue
                validation = await self._socket_validation(host, path)
                if validation is None:
                    continue
                canonical_path, mtime = validation
                targets.append(
                    ConsoleTarget.create(
                        host_id=host.host_id,
                        socket_path=canonical_path,
                        pid=process.pid,
                        started_at=process.started_at,
                        command=command,
                        qemu_name=parse_qemu_name(process.argv),
                        socket_mtime=mtime,
                    )
                )
            for tcp_host, tcp_port in parse_console_tcp_endpoints(process.argv):
                if not host.allows_tcp(tcp_host, tcp_port):
                    continue
                targets.append(
                    ConsoleTarget.create_tcp(
                        host_id=host.host_id,
                        tcp_host=tcp_host,
                        tcp_port=tcp_port,
                        pid=process.pid,
                        started_at=process.started_at,
                        command=command,
                        qemu_name=parse_qemu_name(process.argv),
                    )
                )
        return tuple(targets)

    async def _discover_docker(self, host: ConsoleHost) -> tuple[ConsoleTarget, ...]:
        source = Path(__file__).with_name("console_docker_inventory.py").read_bytes()
        args = shlex.join((json.dumps(host.docker_container_prefixes),
                           json.dumps([str(p) for p in host.docker_socket_roots])))
        script = (f"# OLD_SUN_DOCKER_DISCOVERY_V1\npython3 - {args} <<'OLD_SUN_INVENTORY_END'\n".encode()
                  + source + b"\nOLD_SUN_INVENTORY_END\n")
        result = await self._run(host, script)
        if result.returncode:
            raise RuntimeError("Docker inventory unavailable")
        if len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError("Docker inventory exceeds size limit")
        records = json.loads(result.stdout)
        if not isinstance(records, list):
            raise ValueError("invalid Docker inventory")
        targets = []
        for item in records[:16384]:
            try:
                cid, name, pid = item["container_id"], item["container_name"], item["pid"]
                started, container_started = item["started_at"], item["container_started_at"]
                argv = item["argv"]
                if (not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{64}", cid)
                        or not isinstance(name, str) or not _HOST_ID.fullmatch(name)
                        or not name.startswith(host.docker_container_prefixes)
                        or type(pid) is not int or pid <= 0
                        or not isinstance(started, str) or not started
                        or not isinstance(container_started, str) or not container_started
                        or not isinstance(argv, list) or not all(isinstance(a, str) for a in argv)
                        or not is_qemu_process(argv)):
                    continue
                for path in parse_console_paths(argv):
                    if not host.allows_docker(name, path):
                        continue
                    stat = item["sockets"].get(str(path))
                    if not isinstance(stat, dict) or type(stat.get("inode")) is not int or type(stat.get("device")) is not int:
                        continue
                    identity = json.dumps([host.host_id, cid, container_started, pid, started,
                                           str(path), stat["device"], stat["inode"]]).encode()
                    targets.append(ConsoleTarget(
                        hashlib.sha256(identity).hexdigest()[:24], host.host_id, path, pid,
                        f"{container_started}/{started}", shlex.join(argv), parse_qemu_name(argv),
                        float(stat["mtime"]), container_id=cid, container_name=name))
                if item.get("stdio") is True and has_serial_stdio(argv):
                    identity = json.dumps([host.host_id, cid, container_started, pid, started, "stdio"]).encode()
                    targets.append(ConsoleTarget(
                        hashlib.sha256(identity).hexdigest()[:24], host.host_id, None, pid,
                        f"{container_started}/{started}", shlex.join(argv), parse_qemu_name(argv), None,
                        container_id=cid, container_name=name))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return tuple(targets)

    async def discover(self) -> DiscoveryReport:
        async def one(host: ConsoleHost, docker: bool = False) -> tuple[str, tuple[ConsoleTarget, ...] | Exception]:
            key = f"{host.host_id}/docker" if docker else host.host_id
            try:
                return key, await asyncio.wait_for(
                    self._discover_docker(host) if docker else self._discover_host(host),
                    host.discovery_timeout_seconds,
                )
            except Exception as exc:
                return key, exc

        results = await asyncio.gather(*(one(host) for host in self.hosts),
                                      *(one(host, True) for host in self.hosts if host.docker_container_prefixes))
        targets: list[ConsoleTarget] = []
        errors: dict[str, DiscoveryError] = {}
        for host, result in results:
            if isinstance(result, Exception):
                kind = "timeout" if isinstance(result, TimeoutError) else "command_failed"
                errors[host] = DiscoveryError(kind, str(result) or kind)
            else:
                targets.extend(result)
        targets.sort(key=lambda target: (target.host_id, target.qemu_name or "", target.pid, target.endpoint))
        return DiscoveryReport(tuple(targets), errors)

    async def revalidate(self, target: ConsoleTarget) -> ConsoleTarget:
        host = self._hosts.get(target.host_id)
        if host is None:
            raise ValueError("stale console target: host is no longer configured")
        current = await asyncio.wait_for(
            self._discover_docker(host) if target.container_id else self._discover_host(host),
            host.discovery_timeout_seconds,
        )
        for candidate in current:
            if candidate.target_id == target.target_id:
                return candidate
        raise ValueError("stale console target: process or socket identity changed")

    def connector(self, target: ConsoleTarget) -> ConsoleConnector:
        host = self._hosts.get(target.host_id)
        if host is None:
            raise ValueError("unknown or disallowed console target")
        if target.container_id is not None:
            if (not re.fullmatch(r"[a-f0-9]{64}", target.container_id)
                    or not host.docker_container_prefixes
                    or not (target.container_name or "").startswith(host.docker_container_prefixes)
                    or target.socket_path is not None and not host.allows_docker(target.container_name or "", target.socket_path)):
                raise ValueError("unknown or disallowed console target")
            if target.socket_path is None:
                # Docker requires a TTY when the container was created with one.
                # Keep the SSH link binary and give only Docker a raw, no-echo PTY.
                remote_argv = ("socat", "-d", "-d", "-", "EXEC:docker attach --sig-proxy=false --detach-keys= "
                               f"{target.container_id},pty,setsid,ctty,rawer,echo=0")
                ready_marker = b"starting data transfer loop"
            else:
                source = Path(__file__).with_name("console_socket_relay.py").read_text()
                remote_argv = ("docker", "exec", "-i", target.container_id,
                               "python3", "-c", source, str(target.socket_path))
                ready_marker = b"OLD_SUN_CONSOLE_READY"
            if host.ssh_target is None:
                return ArgvConsoleConnector(remote_argv, ready_marker=ready_marker)
            timeout = max(1, int(host.connect_timeout_seconds))
            return ArgvConsoleConnector(("ssh", "-o", "BatchMode=yes", "-o",
                                         f"ConnectTimeout={timeout}", "-T", host.ssh_target,
                                         shlex.join(remote_argv)), ready_marker=ready_marker)
        ready_marker = None
        if target.socket_path is not None:
            if not host.allows(target.socket_path):
                raise ValueError("unknown or disallowed console target")
            if host.ssh_target is None:
                return UnixConsoleConnector(Path(str(target.socket_path)))
            remote_argv = ("/usr/bin/socat", "-d", "-d", "-", f"UNIX-CONNECT:{target.socket_path}")
            ready_marker = b"starting data transfer loop"
        else:
            if target.tcp_host is None or target.tcp_port is None or not host.allows_tcp(target.tcp_host, target.tcp_port):
                raise ValueError("unknown or disallowed console target")
            remote_argv = ("/usr/bin/nc", target.tcp_host, str(target.tcp_port))
            if host.ssh_target is None:
                return ArgvConsoleConnector(remote_argv)
        timeout = max(1, int(host.connect_timeout_seconds))
        return ArgvConsoleConnector(
            (
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={timeout}",
                "-T",
                host.ssh_target,
                shlex.join(remote_argv),
            ),
            ready_marker=ready_marker,
        )


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


def is_qemu_process(argv: tuple[str, ...] | list[str]) -> bool:
    """Recognize upstream QEMU and UTM's bundled softmmu executable."""
    for value in tuple(argv)[:2]:
        executable = PurePosixPath(value).name
        if executable.startswith("qemu-system-") or (executable.startswith("qemu-") and executable.endswith("-softmmu")):
            return True
    return False


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


def has_serial_stdio(argv: tuple[str, ...] | list[str]) -> bool:
    arguments = tuple(argv)
    devices = set()
    for value in _option_values(arguments, "-chardev"):
        backend, fields = _comma_fields(value)
        if backend == "stdio" and fields.get("id") and fields.get("signal") == "off":
            devices.add(fields["id"])
    return any(s == "stdio" or s.startswith("chardev:") and s[8:] in devices
               for s in _option_values(arguments, "-serial"))


def parse_console_tcp_endpoints(argv: tuple[str, ...] | list[str]) -> tuple[tuple[str, int], ...]:
    """Extract loopback TCP servers referenced by QEMU serial devices."""
    arguments = tuple(argv)
    chardevs: dict[str, tuple[str, int]] = {}
    for definition in _option_values(arguments, "-chardev"):
        backend, fields = _comma_fields(definition)
        if backend != "socket" or not fields.get("id") or fields.get("server") not in {"on", "yes"}:
            continue
        tcp_host = fields.get("host", "127.0.0.1")
        try:
            tcp_port = int(fields.get("port", ""))
        except ValueError:
            continue
        if tcp_host in {"127.0.0.1", "localhost", "::1"} and 1 <= tcp_port <= 65535:
            chardevs[fields["id"]] = (tcp_host, tcp_port)

    endpoints: list[tuple[str, int]] = []
    for serial in _option_values(arguments, "-serial"):
        if serial.startswith("chardev:"):
            endpoint = chardevs.get(serial.removeprefix("chardev:"))
            if endpoint is not None:
                endpoints.append(endpoint)
    return tuple(dict.fromkeys(endpoints))


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

        raw_roots = raw.get("allowed_socket_roots", [])
        if not isinstance(raw_roots, list) or not all(isinstance(item, str) for item in raw_roots):
            raise ValueError(f"host {host_id} allowed_socket_roots must be a string array")
        roots = tuple(PurePosixPath(item) for item in raw_roots)
        if any(not root.is_absolute() or ".." in root.parts for root in roots):
            raise ValueError(f"host {host_id} socket roots must be absolute without parent traversal")

        raw_tcp_ports = raw.get("allowed_tcp_ports", [])
        if not isinstance(raw_tcp_ports, list) or any(
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 for port in raw_tcp_ports
        ):
            raise ValueError(f"host {host_id} allowed_tcp_ports must contain valid TCP ports")
        tcp_ports = tuple(dict.fromkeys(raw_tcp_ports))
        prefixes = raw.get("docker_container_prefixes", [])
        docker_roots_raw = raw.get("docker_socket_roots", [])
        if (not isinstance(prefixes, list) or any(not isinstance(p, str) or not _HOST_ID.fullmatch(p) for p in prefixes)
                or not isinstance(docker_roots_raw, list) or any(not isinstance(p, str) for p in docker_roots_raw)):
            raise ValueError("Docker prefixes and socket roots must be explicit string arrays")
        docker_roots = tuple(PurePosixPath(p) for p in docker_roots_raw)
        if (bool(prefixes) != bool(docker_roots) or prefixes and platform != "linux"
                or any(not p.is_absolute() or ".." in p.parts or str(p) == "/" for p in docker_roots)):
            raise ValueError("Docker discovery requires Linux, prefixes, and scoped absolute socket roots")
        if not roots and not tcp_ports and not prefixes:
            raise ValueError(f"host {host_id} requires an allowed console endpoint")

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
                allowed_tcp_ports=tcp_ports,
                lifecycle_argv=lifecycle,
                discovery_timeout_seconds=discovery_timeout,
                connect_timeout_seconds=connect_timeout,
                docker_container_prefixes=tuple(prefixes),
                docker_socket_roots=docker_roots,
            )
        )
    return tuple(hosts)
