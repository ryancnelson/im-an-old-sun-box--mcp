"""Console entry point."""


def main() -> None:
    """Start the stdio MCP server."""
    from .server import run

    run()


if __name__ == "__main__":
    main()

