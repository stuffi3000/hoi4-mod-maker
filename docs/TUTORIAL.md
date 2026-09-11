# HOI4 Map Making Tool — Tutorial

Create a HOI4 full conversion MOD from scratch that can be played in the game.

## Overall process

```
Draw land and sea → Generate provinces → Generate height → Generate terrain → Create states and countries → Export → Enter the game
```

There are 7 steps in total, just follow them.

---

## Step 1: Create a new project

1. Open the software and click **New Project**
2. Select the map size (5632x2048 is recommended, the same size as the original)
3. Select the save path and give it a name.

> You will see a completely black map, this is normal.

## Step 2: Draw the Land and Sea

Switch to **Land & Sea** mode (first one from the left).

1. Select the **Brush** tool
2. Click the **Draw Land** button (green) to draw the shape of the continent on the map
3. There is no need to draw the ocean - any place not drawn will automatically be the ocean.
4. If you make a mistake, use **Eraser** to erase it, or Ctrl+Z to undo it.
5. Use the **Fill** tool to quickly fill large areas
6. If you want to draw a lake, click the **Draw Lake** button

> **Tip**: You can import a reference picture (File → Import Reference Picture), facing the reference picture.

## Step 3: Generate provinces

Still in **"Land and Sea"** mode.

1. Set the **number of provinces** (generally 5000-15000, the larger the map, the more)
2. Click **Generate Province**
3. Wait a few seconds and a colored province grid will appear on the map.
4. Click **Verify Province** to check if there are any problems

> Province is the most basic map unit in HOI4, and each colored block is a province.

### Hand drawn and refined provinces

Switch to **"Province"** mode. Automatic generation and manual drawing will edit the same province map and can be mixed:

1. Click **Import Reference Image** to continue using the same background image when drawing the land.
2. Use **Select** to click on an automatically generated province, then cut the **Brush** and drag from the inside of the province outward to modify the border.
3. Click **New Province** and draw directly; the location of the first stroke will determine whether it is a land, ocean or lake province
4. **Fill** only processes unallocated blank areas; please use **Merge** between existing provinces
5. The brush will keep the provinces continuous and partially repair the X-shaped intersection after letting go; it is still recommended to click **Verify Provinces** after completion.

> Manually drawn pixels will not be overwritten by incremental automatic generation. You can draw the key provinces first, and then let automatic generation fill in the remaining blank areas, or you can automatically generate them first and then refine them one by one.

## Step 4: Generate height map

Switch to **"Height"** mode.

1. Click **Smart Generate Height**
2. The software will automatically calculate where it should be high (mountains) and where it should be low (plains)
3. Not satisfied? Change the **seed** number and click Generate, and you will get a different mountain distribution.
4. **Mountain Strength** Slider: The bigger the mountain, the higher it will be
5. You can use **Smooth Height** to make the transition softer

> The height map determines the ups and downs of the terrain in the game. Light colors = high, dark colors = low.

## Step 5: Generate terrain

Switch to **Terrain** mode.

1. Click **Intelligent Terrain Generation**
2. The software automatically assigns based on the height map: low = plains/forests, high = hills/mountains, highest = snow mountains
3. If you are not satisfied, you can adjust the parameters and regenerate:
- **Seed**: Change random results
- **Noise intensity**: affects the complexity of terrain boundaries
- **Scatter density**: affects the spot effect (more natural)
4. Partially dissatisfied? Switch to **Brush** mode, select a terrain, and modify it manually

> Terrain affects combat bonuses and movement speed in the game.

## Step 6: Statehood and Nationhood

### Create states

Switch to **"State"** mode.

1. Click **Auto Group** - automatically divide the province into several states
2. Or manually: click **Select Province to Create a State**, click the province, and click **Confirm to create a new state**

### Build a country

Switch to **"Country"** mode.

1. Click **Create Country**
2. Enter the country code (3 English capital letters, such as AAA), country name, and select a color
3. Click on a state in the states list to assign it to a country

> At least 1 country is required to enter the game.

### Shortcut

If you just want to test quickly, there is a **One-click initialization (state+strategic area+country)** button at the bottom of the **"Land and Sea"** mode to get it done in one step.

## Step 7: Export MOD

1. Click the **Export MOD** button at the bottom on the left
2. A preflight dialog box will pop up, which will tell you what is missing and automatically complete it.
3. Click **Start Export**
4. Wait for completion (it may take a few seconds to dozens of seconds for large maps)

After the export is completed, the MOD file is at:
```
D:\Documents\Paradox Interactive\Hearts of Iron IV\mod\WorldTest\
```

## Step 8: Enter game testing

1. Open Steam → Launch HOI4
2. Check your MOD in the launcher (named Fantasy World)
3. Click to start the game
4. Select country → Start

> If it crashes, check the "Help" menu in the software for debugging guidance.

---

## FAQ

### Q: Is the generated terrain all flat?
First generate the height map (step 4), and then generate the terrain (step 5). Terrain depends on the height map.

### Q: The game crashes?
Most common reasons:
- No country → Must build at least one
- Provinces are too fragmented → reduce the number of provinces and regenerate them
- Try **One-click initialization** to automatically complete all missing data

### Q: Is the brush too small/large?
Each mode page has a **Brush Size** slider, drag to adjust.

### Q: How to cancel?
Ctrl+Z undo, Ctrl+Y redo.

### Q: How to zoom in and out of the map?
Use the mouse wheel to zoom, hold down the middle/right button and drag to pan. Ctrl+0 Fit to window.

### Q: How to switch to English interface?
Menu → Settings → Language / Language

---

## Pattern description quick check

| Mode | Purpose | Key Operations |
|------|------|---------|
| Land and sea | Draw the shape of the continent | Draw the land with a brush and fill it in |
| Province | Edit province | Reference drawing stroke, brush/fill, merge/cut/expand |
| Height | Terrain height | Intelligent generation + manual fine-tuning |
| Terrain | Plains/mountains, etc. | Intelligent generation + brush modification |
| River | Draw a river | 1 pixel wide, top, bottom, left, and right |
| State | Province grouping | Automatic grouping or manual selection |
| Country | Create country | Build at least 1 |
| Continents | Continent division | Add continent + specified provinces |
| Strategic Areas | Weather/Sea | Automatic or Create from State |
| Logistics | Railway/Supply | Draw railway lines + supply points |
| Overview map | Zoom background color | Set land/sea/lake color |
| Map configuration | Engine parameters | Generally do not need to touch |
