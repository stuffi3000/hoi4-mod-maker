# Reference base map UX redesign design

Date: 2026-07-05
Status: Approved by user (with style drawing confirmation)
Style diagram: https://claude.ai/code/artifact/3a979421-da51-4dda-9e81-1e69909f6866

## need

Four improvements to the "① Basemap" card on the land drawing page:

1. **Import button on top** — "Import reference images..." is placed on the first row of the card.
2. **Open original reference** - A new button is added in the card to load the original map from the game directory with one click (reusing the `_on_load_vanilla_ref` logic of the file menu) without having to flip through the menu.
3. **The two pictures are customized separately** — The original reference picture is complemented with zoom slider + fill button + drag ability, and is completely symmetrical with the customized picture (current situation: the original picture is forced to stretch and fill, and the transparency can only be adjusted).
4. **Adjustment mode drag** - Added "Adjust reference image position" switch button; during activation, left-click drag = move reference image, scroll wheel = zoom reference image, **all drawing functions are paused**; ESC or click again to exit.

## Card layout (after revision)

```
① Reference base map
[Import reference image…(blue stroke)] [Open original reference]
─ Original reference──────────── [hide]
  Transparency▬▬▬ 30%
  Zoom▬▬▬ 100%  [Covered]
─ Custom reference map────────── [hide]
  Transparency▬▬▬ 40%
  Zoom▬▬▬ 100%  [Covered]
[🖐 Adjust the position of the reference image]（switch)
Adjust object: (•)Customize( )Original← Normally grayed out, available after activation
Prompt line (small font)
```

## Adjust mode behavior

- After the switch button is activated, it turns **orange** (`#f97316`, consistent with the transformation tool checked), and the text changes to "Adjusting the reference image (click or ESC to exit)".
- The adjusted reference image on the canvas displays an **orange dotted border**, and the cursor changes to the movement style (SizeAllCursor).
- Input interception: left-click dragging and moving to select the reference image; scroll wheel to zoom it (synchronized back to the page slider); brush/fill/province click/box selection, etc. are not triggered; middle-click/space panning view is retained.
- Exit: Click the button again or press ESC → to resume normal drawing and hide the dotted frame.
- The "Adjustment Object" radio selection determines whether the drag/wheel will act on the custom image or the original image.
- The original Ctrl+left-click dragging/Ctrl+wheel zoom (applies to custom graphs) remains unchanged.

## Implementation structure

| Documentation | Changes |
|------|------|
| `views/canvas/ref_images.py` | Refactoring: extracting the common"Reference layer"structure (item + originalpixmap + scale），Original/Customize one copy each, unifiedload / opacity / scale / move / fit / visible interface. The old method names are retained as thin wrappers,main_window The wiring does not change with the existing test.|
| `views/canvas/widget.py` | `_vanilla_ref_item` Adapt new structure at initialization; add adjustment mode status+ dashed boxQGraphicsRectItem。 |
| `views/canvas/input_router.py` | mousePress/Move/Release/wheel Top interception adjustment mode;ESC Exit (signal the page button to uncheck).|
| `features/map/land/page.py` | Card rearrangement+ New controls+ New signal:`open_vanilla_requested`、`adjust_mode_toggled(bool)`、`adjust_target_changed(str)`、original zoom/Full of signals.|
| `views/main_window.py` | New signal wired to canvas/file_ops. |
| `ui/i18n/en/land.py` | Add and maintain the English interface copy. |

## verify

- `pytest` full quantity (the page signal interface is backward compatible, all old tests should be passed).
- Manual GUI: In the adjustment mode, the brush is invalid, dragging/wheeling is effective, ESC exits to resume drawing; the original image can be zoomed and dragged; "full" reset.

## Risk

- input_router event has many branches (15+), and the adjustment mode interception must be placed before all drawing branches. Missing one branch will cause "wrong drawing during adjustment". Countermeasure: Intercept and put mousePressEvent at the top (second only to middle-click panning).
- Refactor ref_images and change the internal attribute names. All `_vanilla_ref_item` references scattered in widget.py need to be synchronized.
