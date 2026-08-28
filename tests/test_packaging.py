from importlib import import_module, resources


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
