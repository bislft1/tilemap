# Character Hitbox Editor

Author animation hitboxes in a dedicated Pygame editor. The Character Collision
Editor remains responsible for static body collision shapes.

Open **Tools > Character Hitbox Editor**, or run:

```bash
PYTHONPATH=src python -m plugins.character_hitbox.standalone path/to/hero.anim.json --data-root data
```

The standalone window supports sizes of 800x600 and larger.

## Drawing across frames

1. Load an animation and choose a clip in the left panel.
2. Select a frame using the timeline, arrow buttons, or Left/Right keys.
   Frame numbers are **zero-based**, and window ranges include both endpoints.
3. Click **New** (plus icon). The new window starts empty on this frame.
4. Choose a shape in the **Add shape** toolbar. For polygons, click at least
   three points and press Enter, right-click, or click the first vertex to close.
   For rectangles, circles, and capsules, drag on the empty canvas to create one.
   Drawing without New automatically creates a window on the current frame.
5. For a different hitbox on another frame, scrub there and click New, then draw.
   Existing windows retain their geometry. Inactive shapes are never editable.
6. To reuse the **same geometry** over several frames, select its window,
   scrub to the desired boundary, and click Start or End. Selecting a window
   returns to its first frame. Editing an active shape changes it throughout
   that window's range. Create separate windows for different geometry.
7. Save with Ctrl+S / Cmd+S or the save icon. Unsaved changes show `Name*`.

The window list shows each range, activity, and shape count. Other shapes active
on the displayed frame appear as outlines. The Hull toggle shows the bounding
box of all hitboxes in the clip; it can extend beyond the current frame's shapes.

## Multiple shapes and editing

A window can contain several shapes. Choosing a shape tool starts an additional
shape in the selected active window; it does not replace existing shapes.
Use **Next shape** to return to an existing shape for editing.

- Drag polygon vertices to adjust them; click an edge to insert a vertex.
- Drag the polygon interior to move the whole polygon.
- Delete/Backspace removes the selected vertex. Removing a vertex from a triangle
  removes the shape. With no selected vertex, Delete removes the whole shape.
- Primitive corner, center, radius, and capsule endpoint handles resize or move
  shapes. Drag the body to translate it.
- Esc cancels a polygon draft; Backspace removes its latest point.
- A complete polygon draft finishes before navigation. A draft with fewer than
  three points blocks navigation until completed or cancelled.
- Delete (close icon) beside New removes the selected window.

## Navigation and preview

| Action | Control |
| --- | --- |
| Previous / next frame | Skip icons or Left / Right |
| Scrub directly | Click or drag the timeline; green bands show active ranges |
| Play / pause | Play icon or Enter (finish any polygon first) |
| Pan | Middle drag or Space + left drag |
| Zoom at cursor | Mouse wheel |
| Fit sprite | Fit or R |
| Toggle grid / snapping / coordinate probe | G / N / P |
| Collision layers and mask | Gear icon or L; L / Esc closes |
| Save | Save icon or Ctrl+S / Cmd+S |

Playback follows authored frame durations and loop settings. Shapes are read-only
while previewing. Pan and zoom survive frame and clip navigation. Text input and
open dialogs capture shortcuts so typing does not scrub or modify shapes.

## Files and validation

New documents save to `data-root/character_collision/<name>.hitbox.json`, or beside
the animation if no data root is supplied. A matching hitbox file loads with the
animation. Explicitly loaded files save back to their original path. Closing or
replacing a modified document asks before discarding changes.

Saving validates inclusive ranges, unique window IDs, finite positive dimensions,
32-bit layers/masks, and convex nondegenerate polygons. Fix invalid shapes or
delete empty windows before saving. Concave polygons appear in a warning color.
Saves replace the destination atomically, preserving the last file on failure.

The existing hitbox schema remains:

```json
{
  "character_name": "hero",
  "clips": {
    "attack": {
      "hits": [{
        "id": "hit_1",
        "frames": [1, 3],
        "shapes": [{"type": "circle", "radius": 12, "offset": [16, 16]}],
        "collision_layer": 1,
        "collision_mask": 4294967295,
        "properties": {"damage": 10}
      }]
    }
  }
}
```

Imported custom properties and all shapes are retained. The editor currently
exposes geometry, ranges, and layers/masks; custom properties are edited in JSON.
