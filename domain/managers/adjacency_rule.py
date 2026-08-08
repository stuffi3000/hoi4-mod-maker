"""
Adjacency Rule 管理器 — 海峡/运河通行规则.

参考: 参考/Map modding.txt 行 504-520 + vanilla map/adjacency_rules.txt

每个 rule 有:
- name: 字符串 ID, 在 adjacencies.csv 第 9 列引用
- 4 种关系 × 4 种通行权限:
  contested / enemy / friend / neutral × army / navy / submarine / trade
- required_provinces: 控制者必须同时控制的省份列表 (≥2)
- icon_province: 海军视图里图标显示的省份 (sea)
- offset: 图标 3D 偏移 (X Z Y), 默认 0 0 0

格式示例 (vanilla SUEZ_CANAL):
adjacency_rule = {
    name = "SUEZ_CANAL"
    contested = { army=no navy=no submarine=no trade=no }
    enemy     = { army=no navy=no submarine=no trade=no }
    friend    = { army=yes navy=yes submarine=yes trade=yes }
    neutral   = { army=yes navy=yes submarine=yes trade=yes }
    required_provinces = { 12049 1155 4073 9947 }
    icon = 12049
}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PassType = Literal["army", "navy", "submarine", "trade"]
RelationType = Literal["contested", "enemy", "friend", "neutral"]

ALL_PASS_TYPES: tuple[str, ...] = ("army", "navy", "submarine", "trade")
ALL_RELATIONS: tuple[str, ...] = ("contested", "enemy", "friend", "neutral")


@dataclass
class AdjacencyRule:
    """一条 adjacency rule."""
    name: str
    # 4 种关系下的 4 种通行权限. dict 嵌 dict, 默认全部 no
    contested: dict[str, bool] = field(default_factory=lambda: {p: False for p in ALL_PASS_TYPES})
    enemy: dict[str, bool] = field(default_factory=lambda: {p: False for p in ALL_PASS_TYPES})
    friend: dict[str, bool] = field(default_factory=lambda: {p: True for p in ALL_PASS_TYPES})
    neutral: dict[str, bool] = field(default_factory=lambda: {p: True for p in ALL_PASS_TYPES})
    # 控制条件
    required_provinces: list[int] = field(default_factory=list)
    icon_province: int = -1  # -1 = 不写

    def get_relation(self, relation: str) -> dict[str, bool]:
        """获取某关系的通行权限 dict."""
        return {
            "contested": self.contested,
            "enemy": self.enemy,
            "friend": self.friend,
            "neutral": self.neutral,
        }[relation]

    def to_block(self) -> str:
        """序列化为 adjacency_rules.txt 里的一个 adjacency_rule={...} 块."""
        lines: list[str] = []
        lines.append("adjacency_rule = {")
        lines.append(f'\tname = "{self.name}"')
        lines.append("")
        for rel in ALL_RELATIONS:
            d = self.get_relation(rel)
            lines.append(f"\t{rel} = {{")
            for p in ALL_PASS_TYPES:
                lines.append(f"\t\t{p} = {'yes' if d.get(p) else 'no'}")
            lines.append("\t}")
        if self.required_provinces:
            ids = " ".join(str(p) for p in self.required_provinces)
            lines.append(f"\trequired_provinces = {{ {ids} }}")
        if self.icon_province > 0:
            lines.append(f"\ticon = {self.icon_province}")
        lines.append("}")
        return "\n".join(lines)


class AdjacencyRuleManager:
    """管理所有 adjacency rules. 按 name 去重."""

    def __init__(self) -> None:
        self._rules: dict[str, AdjacencyRule] = {}

    def add(self, rule: AdjacencyRule) -> None:
        if not rule.name:
            raise ValueError("Rule name cannot be empty")
        self._rules[rule.name] = rule

    def remove(self, name: str) -> bool:
        if name in self._rules:
            del self._rules[name]
            return True
        return False

    def get(self, name: str) -> AdjacencyRule | None:
        return self._rules.get(name)

    def get_all(self) -> list[AdjacencyRule]:
        return list(self._rules.values())

    def names(self) -> list[str]:
        return list(self._rules.keys())

    def count(self) -> int:
        return len(self._rules)

    def clear(self) -> None:
        self._rules = {}

    # ─────────── 数据同步 (compact_with_references) ───────────

    def drop_provinces(self, pids: set[int]) -> None:
        """删除引用了被删省份的 rule (整条丢弃)."""
        to_drop = []
        for name, rule in self._rules.items():
            if rule.icon_province in pids:
                to_drop.append(name)
                continue
            if any(p in pids for p in rule.required_provinces):
                to_drop.append(name)
        for n in to_drop:
            del self._rules[n]

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        new_rules: dict[str, AdjacencyRule] = {}
        for name, rule in self._rules.items():
            new_required = []
            broken = False
            for p in rule.required_provinces:
                np = old_to_new.get(p)
                if np is None:
                    broken = True
                    break
                new_required.append(np)
            if broken:
                continue
            new_icon = -1
            if rule.icon_province > 0:
                new_icon = old_to_new.get(rule.icon_province, -1)
                if new_icon < 0:
                    continue
            new_rules[name] = AdjacencyRule(
                name=rule.name,
                contested=dict(rule.contested),
                enemy=dict(rule.enemy),
                friend=dict(rule.friend),
                neutral=dict(rule.neutral),
                required_provinces=new_required,
                icon_province=new_icon,
            )
        self._rules = new_rules

    # ─────────── 序列化 ───────────

    def to_dict(self) -> dict:
        return {
            "rules": [
                {
                    "name": r.name,
                    "contested": dict(r.contested),
                    "enemy": dict(r.enemy),
                    "friend": dict(r.friend),
                    "neutral": dict(r.neutral),
                    "required_provinces": list(r.required_provinces),
                    "icon_province": r.icon_province,
                }
                for r in self._rules.values()
            ]
        }

    def from_dict(self, data: dict) -> None:
        self._rules = {}
        for d in data.get("rules", []):
            rule = AdjacencyRule(
                name=d["name"],
                contested={k: bool(v) for k, v in (d.get("contested") or {}).items()},
                enemy={k: bool(v) for k, v in (d.get("enemy") or {}).items()},
                friend={k: bool(v) for k, v in (d.get("friend") or {}).items()},
                neutral={k: bool(v) for k, v in (d.get("neutral") or {}).items()},
                required_provinces=[int(p) for p in d.get("required_provinces", [])],
                icon_province=int(d.get("icon_province", -1)),
            )
            # 补 missing pass types
            for rel in ALL_RELATIONS:
                rd = rule.get_relation(rel)
                for p in ALL_PASS_TYPES:
                    if p not in rd:
                        rd[p] = False
            self._rules[rule.name] = rule
