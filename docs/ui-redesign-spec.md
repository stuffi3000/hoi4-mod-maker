# UI redesign specifications — 2026-04-10

## Core changes
1. **Group folding tab** replaces tiled tab (three groups: map drawing/regional management/logistics configuration)
2. **Icon + Text** Button
3. **Remove all pop-ups** — All editors have an inline sidebar, and complex content can be folded with section + scroll.
4. **The sidebar can be dragged and adjusted** (default 320px, minimum 260, maximum 500)
5. **New color scheme** — Neutral dark gray + purple and blue accent (refer to VS Code/Figma dark theme)

## Grouping

### 🗺Mapping
- mainland
- province
- terrain
- height
- river

### 📋 Regional Management
- State (state) — Inline details: Basics/Resources/Buildings/Provincial Buildings/Core Claims Each collapsed section
- country
- continental partition (continent) — migrated from menu popup
- strategic_region — moved from menu popup

### ⚙ Logistics / Configuration
- Logistics — adjacencies + railways + supplies + adjacency_rules
- Overview map (colormap) — moved from menu popup
- Map configuration (default_map) — migrated from menu popup

## Color matching
- Background: #1e1e2e
- Panel: #252535
- Highlight: #6c6cf0 (purple blue)
- Group title: #7c7cff
- Text: #e0e0f0
- Border: #3a3a4a
- Selected: #6c6cf0 white text
- Button hover: rgba(108,108,240,0.15)
- Success (export): #22c55e

## Sidebar
- Default width 320px
- Use QSplitter to implement draggability
- Each page content is wrapped in QScrollArea
- Collapse section is expanded using QToolButton + QFrame animation

## delete
- 5 pop-up window entrances to the tool menu
- 5 sets of dialog handlers for main_window
- State's "Details..." pop-up window entrance (inline replacement)
