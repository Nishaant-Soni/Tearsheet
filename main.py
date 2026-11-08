# Import tools so they get registered via decorators
import tearsheet.tools.analyze  # noqa: F401
import tearsheet.tools.plot  # noqa: F401
import tearsheet.tools.retrieve  # noqa: F401
from server import mcp

if __name__ == "__main__":
    mcp.run()
