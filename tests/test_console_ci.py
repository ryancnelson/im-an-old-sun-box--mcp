import importlib.util
from pathlib import Path
import pytest


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", ["main", "HEAD", "abc", "a" * 39 + ";", "../main"])
def test_ci_requires_an_exact_revision(value):
    with pytest.raises(ValueError):
        script("console_ci").validate_revision(value)


def test_deployment_rolls_back_if_health_fails():
    calls = []
    def unhealthy(): raise RuntimeError("unhealthy")
    with pytest.raises(RuntimeError, match="unhealthy"):
        script("console_deploy").activate("new", "old", calls.append, unhealthy)
    assert calls == ["new", "old"]


def test_deployment_keeps_the_release_after_successful_health():
    calls = []
    script("console_deploy").activate("new", "old", calls.append, lambda: calls.append("health"))
    assert calls == ["new", "health"]


def test_pipeline_builds_tests_and_deploys_only_main():
    text = (Path(__file__).parents[1] / ".woodpecker/test.yml").read_text()
    assert "name: test-linux-amd64" in text
    assert "name: test-darwin-arm64" in text
    assert "name: build" in text
    assert "name: deploy" in text
    assert "branch: main" in text
    assert "depends_on: [build]" in text
    assert "100.87.104.29" in text
