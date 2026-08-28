import asyncio
from pathlib import PurePosixPath

import pytest

from old_sun_mcp.console_discovery import (
    CommandResult,
    ConsoleDiscovery,
    ConsoleHost,
    parse_console_paths,
    parse_hosts_json,
    parse_process_records,
)
from old_sun_mcp.console_transport import ArgvConsoleConnector, UnixConsoleConnector


def test_parse_serial_and_chardev_console_paths() -> None:
    assert parse_console_paths(
        (
            "qemu-system-sparc64",
            "-serial",
            "unix:/tink/runs/demo/console.sock,server=on,wait=off",
        )
    ) == (PurePosixPath("/tink/runs/demo/console.sock"),)

    assert parse_console_paths(
        (
            "qemu-system-sparc64",
            "-chardev",
            "socket,id=guestconsole,path=/tmp/demo.sock,server=on,wait=off",
            "-serial",
            "chardev:guestconsole",
        )
    ) == (PurePosixPath("/tmp/demo.sock"),)


def test_parse_console_paths_ignores_unreferenced_chardev() -> None:
    assert parse_console_paths(
        (
            "qemu-system-sparc64",
            "-chardev",
            "socket,id=monitor,path=/tmp/monitor.sock,server=on,wait=off",
            "-monitor",
            "chardev:monitor",
        )
    ) == ()


def test_host_rejects_console_outside_allowed_roots() -> None:
    host = ConsoleHost(
        host_id="ec2trib",
        label="ec2trib",
        platform="illumos",
        ssh_target="root@ec2trib",
        allowed_socket_roots=(PurePosixPath("/tink/runs"),),
    )

    assert host.allows(PurePosixPath("/tink/runs/demo/console.sock"))
    assert not host.allows(PurePosixPath("/tmp/console.sock"))
    assert not host.allows(PurePosixPath("/tink/runs/../private.sock"))


def test_parse_hosts_json_is_strict() -> None:
    hosts = parse_hosts_json(
        """[
          {
            "id": "ec2cicd",
            "label": "ec2cicd",
            "platform": "linux",
            "ssh_target": "root@ec2cicd",
            "allowed_socket_roots": ["/var/lib/niagara-ci/experiments"]
          },
          {
            "id": "minnie-2-2",
            "label": "minnie-2-2",
            "platform": "darwin",
            "local": true,
            "allowed_socket_roots": ["/tmp"]
          }
        ]"""
    )

    assert [host.host_id for host in hosts] == ["ec2cicd", "minnie-2-2"]
    assert hosts[0].ssh_target == "root@ec2cicd"
    assert hosts[1].ssh_target is None


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            '[{"id":"dup","platform":"linux","ssh_target":"a","allowed_socket_roots":["/tmp"]},'
            '{"id":"dup","platform":"linux","ssh_target":"b","allowed_socket_roots":["/tmp"]}]',
            "duplicate",
        ),
        (
            '[{"id":"bad","platform":"solaris","ssh_target":"a","allowed_socket_roots":["/tmp"]}]',
            "platform",
        ),
        (
            '[{"id":"bad","platform":"linux","ssh_target":"a","allowed_socket_roots":["relative"]}]',
            "absolute",
        ),
        (
            '[{"id":"bad","platform":"linux","allowed_socket_roots":["/tmp"]}]',
            "ssh_target",
        ),
        (
            '[{"id":"bad","platform":"linux","ssh_target":"a","allowed_socket_roots":["/tmp"],"extra":1}]',
            "unknown",
        ),
    ],
)
def test_parse_hosts_json_rejects_invalid_registry(payload: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_hosts_json(payload)


@pytest.mark.parametrize("platform", ["linux", "darwin", "illumos"])
def test_parse_platform_process_records(platform: str) -> None:
    records = parse_process_records(
        platform,
        "343827\t2026-08-26T21:04:46Z\tqemu-system-sparc64 -name oi-base -serial unix:/runs/a.sock,server=on\n",
    )
    assert records[0].pid == 343827
    assert records[0].started_at == "2026-08-26T21:04:46Z"
    assert records[0].argv[-2:] == ("-serial", "unix:/runs/a.sock,server=on")


def _host(host_id: str, *, local: bool = False, timeout: float = 5.0) -> ConsoleHost:
    return ConsoleHost(
        host_id=host_id,
        label=host_id,
        platform="darwin" if local else "linux",
        ssh_target=None if local else f"root@{host_id}",
        allowed_socket_roots=(PurePosixPath("/runs"),),
        discovery_timeout_seconds=timeout,
    )


@pytest.mark.asyncio
async def test_discovery_filters_processes_roots_and_invalid_sockets() -> None:
    calls: list[tuple[tuple[str, ...], bytes]] = []

    async def runner(argv: tuple[str, ...], stdin: bytes, timeout: float) -> CommandResult:
        calls.append((argv, stdin))
        if b"OLD_SUN_DISCOVERY_V1" in stdin:
            return CommandResult(
                0,
                b"10\t2026-08-28T10:00:00Z\tqemu-system-sparc64 -name good -serial unix:/runs/good.sock,server=on\n"
                b"11\t2026-08-28T10:01:00Z\tnot-qemu -serial unix:/runs/no.sock\n"
                b"12\t2026-08-28T10:02:00Z\tqemu-system-x86_64 -serial unix:/private/no.sock\n"
                b"13\t2026-08-28T10:03:00Z\tqemu-system-sparc64 -serial unix:/runs/stale.sock\n",
                b"",
            )
        assert b"/runs/good.sock" in stdin or b"/runs/stale.sock" in stdin
        if b"good.sock" in stdin:
            return CommandResult(0, b"1724850000.25\n", b"")
        return CommandResult(1, b"", b"not a socket")

    report = await ConsoleDiscovery((_host("lab"),), runner=runner).discover()

    assert report.errors == {}
    assert len(report.targets) == 1
    target = report.targets[0]
    assert target.qemu_name == "good"
    assert target.socket_mtime == 1724850000.25
    assert target.target_id == report.targets[0].target_id
    assert calls[0][0][:6] == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-T",
    )


@pytest.mark.asyncio
async def test_discovery_reports_timeout_without_losing_other_hosts() -> None:
    async def runner(argv: tuple[str, ...], stdin: bytes, timeout: float) -> CommandResult:
        if "root@slow" in argv:
            await asyncio.sleep(0.05)
            return CommandResult(0, b"", b"")
        if b"OLD_SUN_DISCOVERY_V1" in stdin:
            return CommandResult(
                0,
                b"22\t2026-08-28T11:00:00Z\tqemu-system-sparc64 -serial unix:/runs/live.sock\n",
                b"",
            )
        return CommandResult(0, b"100.0\n", b"")

    report = await ConsoleDiscovery(
        (_host("fast"), _host("slow", timeout=0.01)),
        runner=runner,
    ).discover()

    assert [target.host_id for target in report.targets] == ["fast"]
    assert report.errors["slow"].kind == "timeout"


@pytest.mark.asyncio
async def test_discovery_timeout_bounds_enumeration_and_socket_checks_together() -> None:
    async def runner(argv: tuple[str, ...], stdin: bytes, timeout: float) -> CommandResult:
        if b"OLD_SUN_DISCOVERY_V1" in stdin:
            records = b"".join(
                f"{pid}\tstart-{pid}\tqemu-system-sparc64 -serial unix:/runs/{pid}.sock\n".encode()
                for pid in range(1, 20)
            )
            return CommandResult(0, records, b"")
        await asyncio.sleep(0.01)
        return CommandResult(0, b"100.0\n", b"")

    report = await ConsoleDiscovery((_host("busy", timeout=0.03),), runner=runner).discover()

    assert report.targets == ()
    assert report.errors["busy"].kind == "timeout"


@pytest.mark.asyncio
async def test_revalidation_rejects_changed_process_identity() -> None:
    phase = 0

    async def runner(argv: tuple[str, ...], stdin: bytes, timeout: float) -> CommandResult:
        nonlocal phase
        if b"OLD_SUN_DISCOVERY_V1" in stdin:
            phase += 1
            started = "2026-08-28T11:00:00Z" if phase == 1 else "2026-08-28T11:05:00Z"
            return CommandResult(
                0,
                f"22\t{started}\tqemu-system-sparc64 -serial unix:/runs/live.sock\n".encode(),
                b"",
            )
        return CommandResult(0, b"100.0\n", b"")

    discovery = ConsoleDiscovery((_host("lab"),), runner=runner)
    target = (await discovery.discover()).targets[0]
    with pytest.raises(ValueError, match="stale"):
        await discovery.revalidate(target)


def test_discovery_builds_local_and_ssh_connectors() -> None:
    local = _host("minnie", local=True)
    remote = _host("ec2trib")
    local_target = type("Target", (), {"host_id": "minnie", "socket_path": PurePosixPath("/runs/a.sock")})()
    remote_target = type("Target", (), {"host_id": "ec2trib", "socket_path": PurePosixPath("/runs/b.sock")})()
    discovery = ConsoleDiscovery((local, remote))

    assert isinstance(discovery.connector(local_target), UnixConsoleConnector)
    connector = discovery.connector(remote_target)
    assert isinstance(connector, ArgvConsoleConnector)
    assert connector.argv[-4:] == ("root@ec2trib", "/usr/bin/socat", "-", "UNIX-CONNECT:/runs/b.sock")
