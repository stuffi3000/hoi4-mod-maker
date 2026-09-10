# Logistics generation

Open **Logistics → Generate logistics…**, choose settings, click **Preview
generation**, then **Apply generation**. Ctrl+Z undoes the entire operation.
Existing railroads and hubs are preserved unless you enable Replace.

**Drawn map** connects capitals, victory points, existing hubs and railway
provinces through adjacent land provinces. Each state contributes a fallback
hub. Provinces must belong to states. Water, unassigned provinces and impassable
adjacencies break the network; separate islands remain separate.

**Reference image** accepts an image aligned to the full map extent. Mark routes
in a distinct color, select that color, and adjust the color tolerance. The image
is resized to the map dimensions without changing its orientation. Matching
pixels select provinces; adjacent selected land provinces get railway links.
Transparent pixels are ignored. This is color-based tracing, so labels or other
features using the same color can also select provinces. Preview reports the
proposed link and hub counts; inspect the resulting network on the map after
applying and undo if needed.

Railway levels can be set from 1 to 5. Supply hubs are optional. Strategic
regions retain their existing Auto Generate action. Special adjacency rules
(such as canals and straits) remain manually authored.
