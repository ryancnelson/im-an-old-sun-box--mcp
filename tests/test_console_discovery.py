from pathlib import PurePosixPath

import pytest

from old_sun_mcp.console_discovery import ConsoleHost, parse_console_paths, parse_hosts_json


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
