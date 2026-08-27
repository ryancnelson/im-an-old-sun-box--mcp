from importlib import import_module


def test_package_and_entrypoint_are_importable() -> None:
    package = import_module("old_sun_mcp")
    entrypoint = import_module("old_sun_mcp.__main__")

    assert package.__version__ == "0.1.0"
    assert callable(entrypoint.main)
