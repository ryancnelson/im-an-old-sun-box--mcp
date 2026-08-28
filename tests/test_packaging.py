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
        "niagara-playbox": "linux",
        "ec2trib": "illumos",
    }
    assert hosts["minnie-2-2"]["local"] is True
    assert hosts["ec2cicd"]["ssh_target"] == "root@ec2cicd"
    assert hosts["niagara-playbox"]["ssh_target"] == "niagara@niagara-playbox"
    assert all(host["allowed_socket_roots"] for host in registry)
