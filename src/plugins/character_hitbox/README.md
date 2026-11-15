# Character Hitbox (Detection) Editor

A dedicated visual editor for authoring per-clip active detection windows and hitboxes (`<name>.hitbox.json`) over animation frames.

## Overview

Unlike the Character Collision Editor (which defines a single static body collision shape for a sprite), the Hitbox Editor is built specifically for animation-driven gameplay:
- Per-clip animation timelines (`idle`, `walk`, `attack`, `slash`, etc.)
- Active frame windows (`[frame_start, frame_end]`)
- Multi-shape authoring: Rectangles, Circles, Capsules, and accurate interactive Polygons
- Live animation playback and frame-by-frame scrubbing with preserved zoom/pan
- 32-bit collision layer and mask channel configuration
- Broad-phase clip hull preview (the union AABB of every window in the clip)
- Compatible with `tilemap-parser`'s `parse_character_hitboxes` and runtime systems

## Usage

### Standalone CLI

```bash
python -m plugins.character_hitbox.standalone path/to/character.anim.json \
    --name "Hero" --data-root /path/to/project/data
```

### Controls

| Action | Control |
|---|---|
| Scrub frames | `<` / `>` buttons or **Left / Right arrow** keys |
| Play / Pause playback | **Play** button or **Spacebar** |
| Set window start / end | **S>** / **E>** buttons |
| Pan canvas | **Middle-click drag** or **Space + Left-click drag** |
| Zoom canvas | **Mouse wheel** (centered on cursor) |
| Reset View | **Fit** button or **R** |
| Toggle Grid / Probe | **G** (Grid), **P** (Probe coordinates) |
| Save Hitbox data | **Save** button or **Ctrl+S** / **Cmd+S** |

### Data Format

Files are saved as `<character_name>.hitbox.json`:

```json
{
  "character_name": "bullet",
  "clips": {
    "shoot": {
      "hits": [
        {
          "id": "blast",
          "frames": [0, 3],
          "shapes": [
            {
              "type": "circle",
              "radius": 14.0,
              "offset": [8.0, 8.0]
            }
          ],
          "collision_layer": 1,
          "collision_mask": 4,
          "properties": {
            "damage": "blast"
          }
        }
      ]
    }
  }
}
```
