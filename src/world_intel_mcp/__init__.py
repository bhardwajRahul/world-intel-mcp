"""World Intelligence MCP Server — real-time global intelligence across 30+ domains."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("world-intel-mcp")
except PackageNotFoundError:  # running from a checkout without an install
    __version__ = "0.0.0+uninstalled"
