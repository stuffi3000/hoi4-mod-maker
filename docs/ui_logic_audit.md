# UI operation logic audit + optimization plan

## User workflow

The normal MOD production process is as follows:

```
mapping→ Province→ terrain→ river→ area(state/country/continent) → Logistics(strategic area/railway) → settings→ Export
```

Each page should arrange controls in the "order in which users do things."

---

## Audit page by page

### 1. Map drawing (LandPage) - has the most controls and needs to be streamlined

**Current number of controls**: 8 areas, 20+ controls
**question**:
- Tools (Brush/Eraser/Fill/Transform/Translate) and land type (land/ocean/lake) are separated, but 99% of user operations are "select land → draw" and should be merged
- The "Smooth Coastline" button is sandwiched between land type and province generation, in an awkward position
- The province generation area is mixed with: generation button + number of provinces + ocean density + lake density + verification + one-click initialization, too complicated
- The original reference picture and the customized reference picture have repeated structures in the two areas and can be merged.
- "One-click initialization" is hidden at the bottom of the province generation area, but it is the most commonly used entry-level function

**Optimization plan**:
```
[One-click initialization] ← Mentioned at the top, newbies will see it first
─── drawing tools───
  brush| Eraser| padding(F) | transform| Pan
  [Brush size slider]
─── Lot type───
  land| ocean| lake← Change to horizontaltoggle button group
─── Operation───
  [smooth coastline]
─── Province generation───
  Number of provinces: [12000]
  ocean density: [15%]
  lake density: [30%]
  [Generate provinces] [Verify]         ← two side by side
─── Reference picture───              ← merge into one area
  Original reference: [Reveal] Transparency: [30%]
  Custom reference: [Reveal] Transparency: [40%] Zoom: [100%] [Covered]
```

### 2. DensityPage — OK, minor changes

**Currently**: 3 regions, reasonable
**Problem**: Density map is an auxiliary for province generation, but if it is placed in a separate tab, users can easily forget to switch back.
**Optimization**: Keep the status quo, but add a prompt at the bottom of the page "After drawing the density map, switch back to "Map Drawing" to generate provinces"

### 3. Province (ProvincePage) — OK, minor changes

**Current**: Information area + tool area (merge/expand/cut) + regeneration area
**question**:
- The province information area takes up a lot of space but is read-only and can be reduced.
- The three merge/expand/cut toggle buttons should be more obviously mutually exclusive
**optimization**:
```
─── Province information───            ← Change to single line: "ID: 123 | land| plain| 450px"
─── Editing tools───
  [merge] [expansion] [cutting]      ← keep
  (Status prompt)
─── Region regeneration───
  [Frame selection area] [Perform a rebuild]   ← keep
```

### 4. HeightPage — too many controls and needs to be streamlined

**CURRENT**: 7 areas, 30+ controls
**question**:
- "One-click smart generation" appears twice (big button at the top + button in the automatic generation area), repeated
- The mountain line drawing area is very complicated (switch+peak+attenuation+confirm/cancel), but only used in mountain mode
- The 5 preset buttons in the manual brush area occupy one row and can be more compact
- The location of the "Import Heightmap" button is not obvious
**optimization**:
```
[Intelligently generate height with one click]          ← Keep only one
  seeds: [42] [random]
  mountain height: [200]
  [Smooth]
─── Mountain line drawing───            ← Collapse area, click to expand
  [Start drawing mountains]
  peak: [220] Attenuation: [80px]
  [Cancel] [Confirm]
─── Manual fine-tuning───
  height value: [120]
  seabed| sea level| flat ground| hills| Mountain← keep
─── import───
  [Import heightmap]
```

### 5. Terrain (TerrainPage) — OK, but mode switching is confusing

**Current**: Automatic generation + province mode/brush mode switching + terrain selection grid + generation parameters
**question**:
- Automatically generate buttons one at the top and one at the bottom, repeat
- The difference between province mode vs brush mode is not intuitive
**optimization**:
```
[Automatically generate terrain with one click]          ← Keep only one
  seeds: [42] [random]
  noise: [20] spread: [65%]
─── edit mode───
  [by province] [brush]           ← addtooltip explain the difference
  (Brush mode only shows brush size and soft edges)
─── Terrain selection───
  (Terrain mesh remains unchanged)
```

### 6. RiverPage — clear steps, keep

**Currently**: 3-step guide (select width → draw → mark) + tools + verification
**Question**: No big problem, it’s very clear
**Optimization**: Maintain status quo

### 7. State (StatePage) — the order of operations needs to be adjusted

**Current**: Automatic grouping → Batch state creation → Assignment mode → List → Properties → Details
**question**:
- "Automatic grouping" and "batch state building" are both at the top, but novices don't know which one to use first
- Assignment mode (checkbox) and batch establishment (toggle) are easily confused
- Attribute editing (name/population/category) is below the list, but the list is too short to see it all
**optimization**:
```
─── quick start───
  [Automatic grouping] Number of provinces per state: [15]     ← merge into one line
─── Manual editing───
  [Drag and drop to assign provinces]                  ← change to explicittoggle
  [Frame selected provinces to create states]
  [Confirm statehood]
─── State List───                    ← Increased height
  (list)
─── Select state attributes───
  Name/ population/ Category
  [DetailsEdit] [VPEdit]
```

### 8. Country (CountryPage) — OK, minor changes

**Current**: Create → Quick Create → List → Properties
**Problem**: The two create buttons are easily confused
**Optimization**: Merged into a "Create Country" button, click to open the pop-up dialog box

### 9. ContinentPage — OK

**Current**: List + Add, Delete, Modify + Pick
**Questions**: No major issues
**Optimization**: Keep

### 10. Strategic Region (StrategicRegionPage) — too many buttons and too complicated

**Current**: Prompt → AutoGenerate → AutoWeather → Create from State → Confirm → Assign Mode → List → New/Delete → Properties
**question**:
- There are 5 buttons in a row at the top (Auto Generate/Auto Weather/Create from State/Confirm/Assign), the user does not know which one to click
- "Create from State" toggle and "Assign Mode" checkbox functionality overlap
**optimization**:
```
─── quick start───
  [Automatically generated(Group by state)]
  [Automatically assign weather]
─── Manual editing───
  [Drag and drop to assign provinces(land+ocean)]     ← Merge assignments and create from states
─── Area list───
  (list) [Create new empty area] [Delete]
─── Select area properties───
  Name/ weather/ naval terrain
```

### 11. Logistics (LogisticsPage) — OK

**Current**: Adjacency Edit → Railroad/Supply
**Questions**: No major issues
**Optimization**: Keep

### 12-13. Color map/default map — OK

Settings page, few controls, keep it.

---

## General optimization rules

| Rules | Description |
|------|------|
| **Put the most commonly used ones at the top** | One-click initialization, automatically generate such buttons and put them at the first position on the page |
| **Remove duplicate buttons** | Only keep one entry for the same function |
| **Merge related controls** | Automatically generate buttons + parameters and put them in the same section |
| **Tips to shorten text** | Don’t write a paragraph if you can explain it clearly in one line |
| **Use toggle group for mutually exclusive operations** | Don’t have both checkbox and toggle button |
| **Single line for read-only information** | Province information does not require 5 lines, one line is enough |
| **List height increased** | More space for state list/strategic area list |

---

## Change priority

| Priority | Page | Changes |
|--------|------|--------|
| High | LandPage | Major changes: merge reference maps, improve one-click initialization, change land type to horizontal |
| High | HeightPage | Medium changes: remove duplicate buttons and fold mountain areas |
| High | StatePage | Medium changes: Adjust the order of operations and enlarge the list |
| High | StrategicRegionPage | Medium changes: button grouping, reducing the number of top buttons |
| Medium | TerrainPage | Small change: Remove the duplicate generation button |
| Medium | ProvincePage | Small change: Change the province information to a single line |
| Low | Other pages | Basically motionless |
