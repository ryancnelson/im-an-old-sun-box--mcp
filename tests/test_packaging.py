from importlib import import_module
import json
from pathlib import Path


def test_package_and_entrypoint_are_importable() -> None:
    package = import_module("old_sun_mcp")
    entrypoint = import_module("old_sun_mcp.__main__")

    assert package.__version__ == "0.1.0"
    assert callable(entrypoint.main)


def test_example_console_registry_contains_lab_hosts() -> None:
    registry = json.loads(Path("examples/console-hosts-minnie.json").read_text())
    hosts = {host["id"]: host for host in registry}

    assert {host_id: host["platform"] for host_id, host in hosts.items()} == {
        "ec2cicd": "linux",
        "minnie-2-2": "darwin",
        "teddeck": "darwin",
        "niagara-playbox": "linux",
        "hp2": "linux",
        "ec2trib": "illumos",
        "biggie": "linux",
    }
    assert hosts["minnie-2-2"]["local"] is True
    assert hosts["ec2cicd"]["ssh_target"] == "root@ec2cicd"
    assert hosts["niagara-playbox"]["ssh_target"] == "root@niagara-playbox"
    assert hosts["teddeck"]["ssh_target"] == "ryan@teddeck"
    assert hosts["teddeck"]["allowed_tcp_ports"] == [4449]
    assert all(host.get("allowed_socket_roots") or host.get("allowed_tcp_ports") for host in registry)


def test_registry_covers_checked_in_woodpecker_launch_contracts():
    from old_sun_mcp.console_discovery import parse_hosts_json
    from pathlib import PurePosixPath

    hosts = {h.host_id: h for h in parse_hosts_json(Path("examples/console-hosts-minnie.json").read_text())}
    assert hosts["ec2trib"].allows(PurePosixPath("/tink/runs/woodpecker-solaris9/run/console.sock"))
    assert hosts["ec2trib"].allows(PurePosixPath("/tink/sun4m-solaris9/runs/run/console.sock"))
    assert hosts["niagara-playbox"].allows(PurePosixPath("/mnt/disk-images/woodpecker/sun4u-openbios-42/run/console.sock"))
    for name in ("sparc64-qemu-openindiana-20g-ci-42", "sun4u-openbios-woodpecker-42"):
        assert hosts["ec2cicd"].allows_docker(name, PurePosixPath("/state/console.sock"))
        assert hosts["niagara-playbox"].allows_docker(name, PurePosixPath("/run/sun4u/console.sock"))
    assert not hosts["niagara-playbox"].allows_docker("unrelated-service", PurePosixPath("/state/console.sock"))
