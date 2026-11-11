"""Entry point: the `tearsheet` command, `python -m tearsheet`, or `uv run main.py`."""

# Importing the tool modules registers their tools on the shared server.
import tearsheet.tools.analyze  # noqa: F401
import tearsheet.tools.plot  # noqa: F401
import tearsheet.tools.retrieve  # noqa: F401
from tearsheet.server import mcp


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
