import json
from pathlib import PurePosixPath

import pytest

from old_sun_mcp.console_discovery import CommandResult, ConsoleDiscovery, parse_hosts_json


CID = "a" * 64


def host():
    return parse_hosts_json(json.dumps([{
        "id": "ci", "platform": "linux", "ssh_target": "root@ci",
        "allowed_socket_roots": ["/runs"],
        "docker_container_prefixes": ["woodpecker-"],
        "docker_socket_roots": ["/state", "/run"],
    }]))[0]


def record(**changes):
    value = {
        "container_id": CID, "container_name": "woodpecker-42",
        "container_started_at": "2026-09-04T20:00:00Z", "pid": 52,
        "started_at": "123456", "argv": ["qemu-system-sparc64", "-name", "Solaris trial",
            "-serial", "unix:/state/console.sock,server=on,wait=off"],
        "sockets": {"/state/console.sock": {"device": 1, "inode": 23, "mtime": 1.0}},
    }
    value.update(changes)
    return value


class Runner:
    def __init__(self):
        self.records = [record()]
        self.docker_error = False
        self.calls = []

    async def __call__(self, argv, stdin, timeout):
        self.calls.append((argv, stdin))
        if b"OLD_SUN_DOCKER_DISCOVERY_V1" in stdin:
            if self.docker_error:
                return CommandResult(1, b"", b"Docker unavailable")
            return CommandResult(0, json.dumps(self.records).encode(), b"")
        if b"OLD_SUN_DISCOVERY_V1" in stdin:
            return CommandResult(0, b"7\tstarted\tqemu-system-sparc64 -serial unix:/runs/native.sock,server=on\n", b"")
        return CommandResult(0, b"/runs/native.sock\t1\n", b"")


@pytest.mark.asyncio
async def test_container_socket_is_discovered_without_attaching():
    runner = Runner()
    discovery = ConsoleDiscovery((host(),), runner)
    report = await discovery.discover()
    assert report.errors == {}
    assert len(report.targets) == 2
    target = next(t for t in report.targets if t.container_id)
    assert target.endpoint_kind == "docker-unix"
    assert target.socket_path == PurePosixPath("/state/console.sock")
    assert target.container_name == "woodpecker-42"
    assert target.qemu_name == "Solaris trial"
    assert all(b"socat" not in script for _, script in runner.calls)
    connector = discovery.connector(target)
    assert CID in connector.argv[-1]
    assert "docker exec -i" in connector.argv[-1]
    assert "python3 -c" in connector.argv[-1]
    assert connector.argv[-1].endswith(" /state/console.sock")
    assert connector.ready_marker == b"OLD_SUN_CONSOLE_READY"


@pytest.mark.parametrize("changes", [
    {"container_id": "bad;command"},
    {"container_name": "unapproved"},
    {"container_started_at": ""},
    {"pid": 0},
    {"argv": ["not-qemu", "-serial", "unix:/state/console.sock"]},
    {"sockets": {}},
    {"argv": ["qemu-system-sparc", "-serial", "unix:/etc/private.sock"],
     "sockets": {"/etc/private.sock": {"device": 1, "inode": 2, "mtime": 1}}},
])
@pytest.mark.asyncio
async def test_untrusted_or_stopped_container_is_not_listed(changes):
    runner = Runner()
    runner.records = [record(**changes)]
    report = await ConsoleDiscovery((host(),), runner).discover()
    assert [t.pid for t in report.targets] == [7]


@pytest.mark.asyncio
async def test_docker_failure_does_not_hide_native_console():
    runner = Runner()
    runner.docker_error = True
    report = await ConsoleDiscovery((host(),), runner).discover()
    assert [t.pid for t in report.targets] == [7]
    assert report.errors["ci/docker"].kind == "command_failed"


@pytest.mark.parametrize("changes", [
    {"container_started_at": "2026-09-04T21:00:00Z"},
    {"started_at": "different-process"},
    {"sockets": {"/state/console.sock": {"device": 1, "inode": 24, "mtime": 1}}},
])
@pytest.mark.asyncio
async def test_revalidation_rejects_restarted_container_or_replaced_socket(changes):
    runner = Runner()
    discovery = ConsoleDiscovery((host(),), runner)
    target = next(t for t in (await discovery.discover()).targets if t.container_id)
    runner.records = [record(**changes)]
    with pytest.raises(ValueError, match="stale"):
        await discovery.revalidate(target)


def test_docker_configuration_is_explicit_and_linux_only():
    assert host().docker_container_prefixes == ("woodpecker-",)
    for changes in [
        {"docker_container_prefixes": ["*"]},
        {"docker_container_prefixes": [""]},
        {"docker_socket_roots": ["/"]},
        {"docker_socket_roots": ["relative"]},
        {"platform": "darwin"},
    ]:
        value = {"id": "ci", "platform": "linux", "ssh_target": "ci",
                 "allowed_socket_roots": ["/runs"],
                 "docker_container_prefixes": ["woodpecker-"], "docker_socket_roots": ["/state"]}
        value.update(changes)
        with pytest.raises(ValueError):
            parse_hosts_json(json.dumps([value]))


@pytest.mark.asyncio
async def test_interactive_docker_stdio_can_be_attached_without_signal_forwarding():
    runner = Runner()
    runner.records = [record(argv=["qemu-system-sparc64", "-chardev", "stdio,id=term,signal=off",
                                   "-serial", "chardev:term"], sockets={}, stdio=True)]
    discovery = ConsoleDiscovery((host(),), runner)
    target = next(t for t in (await discovery.discover()).targets if t.container_id)
    assert target.endpoint_kind == "docker-stdio"
    assert target.endpoint == f"docker://{CID}/stdio"
    assert "attach --sig-proxy=false" in discovery.connector(target).argv[-1]
    runner.records[0]["stdio"] = False
    with pytest.raises(ValueError, match="stale"):
        await discovery.revalidate(target)


def test_remote_inventory_reads_exact_argv_and_socket_identity(monkeypatch, tmp_path):
    from old_sun_mcp import console_docker_inventory as inventory
    calls = []
    proc = tmp_path / "52"
    proc.mkdir()
    (proc / "cmdline").write_bytes(b"qemu-system-sparc64\0-name\0Solaris trial\0-serial\0unix:/state/console.sock,server=on\0")
    (proc / "stat").write_text("52 (qemu (test)) " + " ".join(["S"] + ["0"] * 18 + ["123456"]))
    original_path = inventory.Path
    monkeypatch.setattr(inventory, "Path", lambda value: tmp_path if value == "/proc" else original_path(value))

    def command(*argv):
        calls.append(argv)
        if argv[1] == "ps": return f"{CID} woodpecker-42\n"
        if argv[1] == "inspect": return json.dumps({"state": {"Running": True, "StartedAt": "start", "Pid": 52}, "stdin": False, "tty": False})
        if argv[1] == "top": return "PID\n52\n"
        if argv[1] == "exec": return "1 23 1\n"
        raise AssertionError(argv)

    monkeypatch.setattr(inventory, "command", command)
    records = inventory.inventory(["woodpecker-"], ["/state"])
    assert len(records) == 1
    assert records[0]["argv"][2] == "Solaris trial"
    assert records[0]["started_at"] == "123456"
    assert records[0]["sockets"]["/state/console.sock"]["inode"] == 23
    assert all("attach" not in call and "socat" not in call for call in calls)


@pytest.mark.asyncio
async def test_docker_stdio_supplies_a_raw_tty_and_preserves_control_bytes(tmp_path, monkeypatch):
    import asyncio
    import os
    import shlex
    import shutil
    import sys
    from old_sun_mcp.console_transport import ArgvConsoleConnector

    if not shutil.which("socat"):
        pytest.skip("socat required for raw TTY integration test")
    fake = tmp_path / "docker"
    fake.write_text(f"#!{sys.executable}\n"
                    "import os,sys\n"
                    "if not os.isatty(0): sys.exit('the input device is not a TTY')\n"
                    "os.write(1,b'ready\\n')\n"
                    "while True:\n"
                    " data=os.read(0,1024)\n"
                    " if not data: break\n"
                    " os.write(1,data)\n")
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    runner = Runner()
    runner.records = [record(argv=["qemu-system-sparc64", "-serial", "stdio"], sockets={}, stdio=True)]
    discovery = ConsoleDiscovery((host(),), runner)
    target = next(t for t in (await discovery.discover()).targets if t.container_id)
    remote = tuple(shlex.split(discovery.connector(target).argv[-1]))
    endpoint = await ArgvConsoleConnector(remote).connect()
    try:
        assert await asyncio.wait_for(endpoint.reader.readline(), 2) == b"ready\n"
        data = b"a\r\n\x03\x00\xffz"
        endpoint.writer.write(data)
        await endpoint.writer.drain()
        assert await asyncio.wait_for(endpoint.reader.readexactly(len(data)), 2) == data
    finally:
        await endpoint.close()


@pytest.mark.asyncio
async def test_cancelled_discovery_reaps_the_command(monkeypatch):
    import asyncio
    from old_sun_mcp.console_discovery import run_command

    started = asyncio.Event()
    class Process:
        returncode = None
        killed = False
        reaped = False
        async def communicate(self, stdin):
            started.set()
            await asyncio.Future()
        def kill(self): self.killed = True
        async def wait(self): self.reaped = True
    process = Process()
    async def create(*args, **kwargs): return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(run_command(("ssh", "ci"), b"inventory", 5))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert process.killed and process.reaped
