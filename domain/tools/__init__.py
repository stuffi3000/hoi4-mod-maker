"""Tool Framework — All editing tools are organized into a unified template.

Each tool is a Tool subclass, registered with ToolRegistry.
When canvas receives a mouse event, it finds the corresponding tool and calls on_press / on_drag / on_release."""

from domain.tools.base import Tool, ToolContext, CleanupLevel
from domain.tools.registry import ToolRegistry, register_tool, get_tool, list_tools

__all__ = [
    "Tool",
    "ToolContext",
    "CleanupLevel",
    "ToolRegistry",
    "register_tool",
    "get_tool",
    "list_tools",
]
