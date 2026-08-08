"""
Tool 注册表 — 全局存储所有已注册的工具实例。
"""
from __future__ import annotations

from domain.tools.base import Tool


class ToolRegistry:
    """单例注册表。"""
    _tools: dict[str, Tool] = {}

    @classmethod
    def register(cls, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} must define a name attribute")
        if tool.name in cls._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> Tool | None:
        return cls._tools.get(name)

    @classmethod
    def list_for_mode(cls, display_mode: str) -> list[Tool]:
        return [t for t in cls._tools.values() if display_mode in t.display_modes]

    @classmethod
    def all(cls) -> list[Tool]:
        return list(cls._tools.values())


# 便捷函数
def register_tool(tool: Tool) -> None:
    ToolRegistry.register(tool)


def get_tool(name: str) -> Tool | None:
    return ToolRegistry.get(name)


def list_tools(display_mode: str | None = None) -> list[Tool]:
    if display_mode is None:
        return ToolRegistry.all()
    return ToolRegistry.list_for_mode(display_mode)
