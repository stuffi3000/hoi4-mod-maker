"""Apply a logistics proposal as one undoable edit."""
from commands.base import Command


class GenerateLogisticsCommand(Command):
    label = "Generate logistics"

    def __init__(self, project, proposal, level=3, supply=True, replace=False):
        self.project = project
        self.before = (project.railway_mgr.to_dict(), project.supply_mgr.to_dict())
        from domain.managers.railway import RailwayManager
        from domain.managers.supply_node import SupplyNodeManager
        rails, hubs = RailwayManager(), SupplyNodeManager()
        if not replace:
            rails.from_dict(self.before[0])
        hubs.from_dict(self.before[1])
        if replace and supply:
            hubs.clear()
        existing = {
            tuple(sorted((a, b)))
            for entry in rails.get_all()
            for a, b in zip(entry.province_ids, entry.province_ids[1:])
            if a != b
        }
        for edge in proposal.edges:
            if edge not in existing:
                rails.add(level, list(edge))
        if supply:
            for pid in proposal.hubs:
                if not hubs.contains(pid):
                    hubs.add(pid)
        self.after = (rails.to_dict(), hubs.to_dict())

    def _apply(self, data):
        self.project.railway_mgr.from_dict(data[0])
        self.project.supply_mgr.from_dict(data[1])
        self.project.mark_dirty()
        self.project.event_bus.emit("railway_changed")

    def execute(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
