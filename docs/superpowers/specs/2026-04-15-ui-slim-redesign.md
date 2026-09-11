# UI burden reduction and reconstruction design

## question

The interface is bloated: the 13 mode navigation is too long, there are too many controls on each page, the panel is fixed and takes up space, the workflow is unclear, and provinces are cleared by accident.

## Plan: Three swords to reduce the burden

### First Cut: Merge Mode 13 → 7

| After merge | Contains original schema | Description |
|--------|-----------|------|
| Drawing Maps | Land and Sea + Province Density | Density as Tool Option (Brush/Fill/Transform/Density) |
| Province | Province | Unchanged |
| Terrain | Height + Terrain | Use internal tabs to switch between "Height" and "Terrain" |
| river | river | unchanged |
| Countries & Regions | State + Country + Continent | Switch internally using tabs |
| Logistics | Strategic Area + Logistics System | Internal tab switching |
| Settings | Overview map + map configuration | Not commonly used, put last |

### The second cut: only core controls are exposed on each page

Each page is divided into two layers:
- **Core Area** (directly visible): 3-5 most commonly used buttons/controls
- **Collapse area** (click to expand): advanced parameters, uncommon options

specific:
- Draw a map: toolbar + brush size + plot type + generate province + one-click initialization → direct display. Province parameters/reference map/coastline smoothing → Collapse
- Terrain: automatically generate height + automatically generate terrain → display directly. Seed/Mountain Strength/Threshold Parameters/Mountain Line Drawing → Collapse
- Countries and regions: automatically generate states + create countries → display directly. Property editing/detailed list → Collapse

### The third knife: protection against accidental touch

**Problem**: After generating provinces, switching back to land mode clears all provinces as soon as you draw them.

**Plan**: If there are already provinces when drawing land, pop up the confirmation dialog box "Modifying the land will clear the existing provinces, do you want to continue?" instead of silently clearing it. Give users a choice:
- Continue (clear province)
- Cancel
- Only modify the current area (do not clear other provinces) ← Can be done later

### Things not to do

- Do not change the layout structure of the main window (keep left panel + right canvas)
- Do not change the underlying architecture (controllers/commands/EventBus does not change)
- Do not change the export system
- No new features, pure UI organization

## Change files

| Documentation | Changes |
|------|------|
| ui/tool_panel.py | Pattern list 13→7, create merge page |
| features/map/land/page.py | Density tool + Folding area + Anti-accidental touch |
| features/map/terrain/page.py + height/page.py | Merge into terrain page (tab page) |
| features/map/state/page.py + country/page.py + continent/page.py | Combined into country and region pages (tab pages) |
| features/map/strategic_region/page.py + logistics/page.py | Merge into logistics page (tab page) |
| features/map/colormap/page.py + default_map/page.py | Merged into settings page (tab page) |
| views/canvas/widget.py | _stamp_brush anti-accidental touch confirmation |
| ui/i18n/en/*.py | Update English interface copy |
| views/main_window.py | Update signal connection |

## Risk

- **Medium**: Tab switching of merged pages requires correct forwarding of all signals
- **Low**: The folding area may be in an incorrect initial state (need to remember the last expanded state)
- **Low**: Anti-accidental touch dialog box may affect the quick operation process (but better than silent clearing)
