"""Local MCP adapter; importing it does not start a service or open a database."""

from .client import ElectroChemClient, MCPClientError

__all__ = ["ElectroChemClient", "MCPClientError"]
