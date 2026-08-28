from importlib import import_module, resources
from pathlib import Path
import tomllib


def test_package_and_entrypoint_are_importable() -> None:
    package = import_module("old_sun_mcp")
    entrypoint = import_module("old_sun_mcp.__main__")
    console_entrypoint = import_module("old_sun_mcp.console_main")

    assert package.__version__ == "0.1.0"
    assert callable(entrypoint.main)
    assert callable(console_entrypoint.main)
    static = resources.files("old_sun_mcp").joinpath("static")
    assert static.joinpath("index.html").is_file()
    assert static.joinpath("vendor/xterm.mjs").is_file()
    assert static.joinpath("vendor/addon-fit.mjs").is_file()


def test_tribblix_console_extra_has_no_pydantic_or_mcp_native_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["dependencies"] == []
    assert any(item.startswith("starlette") for item in project["optional-dependencies"]["console"])
    assert not any(
        "fastapi" in item or "pydantic" in item or item.startswith("mcp")
        for item in project["optional-dependencies"]["console"]
    )
