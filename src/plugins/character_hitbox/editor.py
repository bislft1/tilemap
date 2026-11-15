"""
Character Hitbox (Detection) Editor.

A dedicated visual editor for authoring per-clip active detection windows
and hitboxes (<name>.hitbox.json) over character animation frames.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pygame
from pygame import Rect, Surface

from utils.font_manager import FontWeight, font_manager
from utils.shortcuts import is_cmd_or_ctrl
from widgets.filemanager import FileManager
from widgets.input import InputBox
from widgets.ui.button import Button
from widgets.ui.collision_layer_sidebar import CollisionLayerSidebar
from widgets.ui.draw_utils import draw_panel
from widgets.ui.shape_canvas import ShapeCanvas, is_convex_polygon
from widgets.ui.theme import COLORS, FONTS
from widgets.ui.toast import ToastManager
from widgets.ui.tooltip import TooltipManager
from widgets.ui.tree_widget import TreeNode, TreeWidget

from .anim_loader import LoadedAnimation, load_animation_bundle
from .models import (
    CharacterHitboxesDraft,
    ClipHitboxesDraft,
    HitWindowDraft,
)

_LEFT_COLUMN_W = 190
_BOTTOM_STRIP_H = 72
_TOOLBAR_H = 44


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]+", "-", name).strip("-").lower() or "character"


class CharacterHitboxEditor:
    """Dedicated Hitbox / Detection authoring editor."""

    def __init__(
        self,
        rect: Rect,
        character_name: str = "Character",
        data_root: Path | None = None,
        toast: ToastManager | None = None,
    ):
        self.rect = rect
        self.character_name = character_name
        self.data_root = data_root
        self.toast = toast or ToastManager()

        # Animation state
        self.loaded_anim: LoadedAnimation | None = None
        self.current_clip: str | None = None
        self.current_frame_idx: int = 0
        self.is_playing: bool = False
        self._playback_timer: float = 0.0
        self.playback_fps: float = 10.0

        # Hitbox data state
        self.hitbox_data = CharacterHitboxesDraft(character_name=_safe_name(character_name))
        self.current_hitbox_path: Path | None = None
        self.selected_window_id: str | None = None
        self.show_hull: bool = True
        self.tooltip = TooltipManager()

        # Child Widgets
        self.name_input = InputBox(Rect(rect.x + 60, rect.y + 8, 140, 28))
        self.name_input.text = character_name
        self.name_input.on_text_changed = self._on_name_changed

        self.clip_tree = TreeWidget(self._clip_tree_rect())
        self.clip_tree.on_selection_changed = self._on_clip_selected

        self.window_tree = TreeWidget(self._window_tree_rect())
        self.window_tree.on_selection_changed = self._on_window_selected

        self.canvas = ShapeCanvas(self._canvas_rect())
        self.canvas.on_modified = self._on_canvas_shape_modified

        self.layer_sidebar = CollisionLayerSidebar(
            self.rect,
            on_changed=self._on_layer_mask_changed,
        )

        # Toolbar & Bottom Strip buttons
        self._buttons: list[Button] = []
        self._shape_buttons: dict[str, Button] = {}
        self._play_btn: Button | None = None
        self._init_buttons()

        # Dialogs
        self._file_dialog: FileManager | None = None
        self._file_dialog_kind: str | None = None

        self._font = None
        self._font_sm = None

    # -- Geometry & Layout -----------------------------------------------

    def _clip_tree_rect(self) -> Rect:
        available_h = self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H
        half_h = available_h // 2
        return Rect(self.rect.x, self.rect.y + _TOOLBAR_H, _LEFT_COLUMN_W, half_h)

    def _window_tree_rect(self) -> Rect:
        available_h = self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H
        half_h = available_h // 2
        y = self.rect.y + _TOOLBAR_H + half_h
        return Rect(self.rect.x, y, _LEFT_COLUMN_W, available_h - half_h)

    def _canvas_rect(self) -> Rect:
        return Rect(
            self.rect.x + _LEFT_COLUMN_W,
            self.rect.y + _TOOLBAR_H,
            self.rect.w - _LEFT_COLUMN_W,
            self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H,
        )

    def _bottom_strip_rect(self) -> Rect:
        return Rect(
            self.rect.x,
            self.rect.bottom - _BOTTOM_STRIP_H,
            self.rect.w,
            _BOTTOM_STRIP_H,
        )

    def resize(self, rect: Rect) -> None:
        self.rect = rect
        self.clip_tree.rect = self._clip_tree_rect()
        self.window_tree.rect = self._window_tree_rect()
        self.canvas.resize(self._canvas_rect())
        self.layer_sidebar.resize(rect)
        self._layout_buttons()

    # -- Button Setup ----------------------------------------------------

    def _init_buttons(self) -> None:
        self._buttons.clear()
        self._shape_buttons.clear()

        # 1. Toolbar Actions
        self._btn_load_anim = Button(Rect(0, 0, 76, 28), "Anim", tooltip_text="Load animation file (.anim.json)", on_click=self._open_load_anim_dialog)
        self._btn_load_hitbox = Button(Rect(0, 0, 76, 28), "Load", tooltip_text="Load hitbox file (.hitbox.json)", on_click=self._open_load_hitbox_dialog)
        self._btn_save = Button(Rect(0, 0, 76, 28), "Save", tooltip_text="Save hitbox data (Ctrl+S)", on_click=self.save)

        self._buttons.extend([self._btn_load_anim, self._btn_load_hitbox, self._btn_save])

        # Shapes
        for stype in ("Rectangle", "Circle", "Capsule", "Polygon"):
            b = Button(Rect(0, 0, 72, 28), stype, on_click=lambda s=stype.lower(): self._select_shape_type(s))
            self._shape_buttons[stype.lower()] = b
            self._buttons.append(b)

        # Toggles
        self._btn_grid = Button(Rect(0, 0, 48, 28), "Grid", tooltip_text="Toggle Grid (G)", on_click=self._toggle_grid)
        self._btn_fit = Button(Rect(0, 0, 48, 28), "Fit", tooltip_text="Fit View (R)", on_click=lambda: self.canvas.fit_view())
        self._btn_hull = Button(Rect(0, 0, 48, 28), "Hull", tooltip_text="Toggle Clip Hull Box", on_click=self._toggle_hull)
        self._buttons.extend([self._btn_grid, self._btn_fit, self._btn_hull])

        # 2. Window action buttons (placed in left panel)
        self._btn_new_window = Button(Rect(0, 0, 56, 24), "+ New", tooltip_text="Create new window from canvas shape", on_click=self._new_window)
        self._btn_del_window = Button(Rect(0, 0, 56, 24), "- Del", tooltip_text="Delete selected window", on_click=self._delete_selected_window)
        self._buttons.extend([self._btn_new_window, self._btn_del_window])

        # 3. Bottom Strip (Timeline) buttons
        self._btn_prev_frame = Button(Rect(0, 0, 36, 28), "<", tooltip_text="Previous Frame (Left Arrow)", on_click=self._prev_frame)
        self._play_btn = Button(Rect(0, 0, 56, 28), "Play", tooltip_text="Play / Pause Animation (Space)", on_click=self._toggle_playback)
        self._btn_next_frame = Button(Rect(0, 0, 36, 28), ">", tooltip_text="Next Frame (Right Arrow)", on_click=self._next_frame)

        self._btn_set_start = Button(Rect(0, 0, 42, 28), "S>", tooltip_text="Set active window start to current frame", on_click=lambda: self._set_window_range(True))
        self._btn_set_end = Button(Rect(0, 0, 42, 28), "E>", tooltip_text="Set active window end to current frame", on_click=lambda: self._set_window_range(False))

        self._buttons.extend([
            self._btn_prev_frame,
            self._play_btn,
            self._btn_next_frame,
            self._btn_set_start,
            self._btn_set_end,
        ])

        self._layout_buttons()

    def _layout_buttons(self) -> None:
        # Top toolbar
        y = self.rect.y + 8
        self.name_input.resize(self.rect.x + 56, y, 130, 28)

        x = self.name_input.rect.right + 10
        for btn in (self._btn_load_anim, self._btn_load_hitbox, self._btn_save):
            btn.resize(x, y, btn.rect.w, 28)
            x += btn.rect.w + 6

        x += 12  # separator gap
        for stype in ("rectangle", "circle", "capsule", "polygon"):
            b = self._shape_buttons[stype]
            b.resize(x, y, b.rect.w, 28)
            x += b.rect.w + 4

        x += 12
        for btn in (self._btn_grid, self._btn_fit, self._btn_hull):
            btn.resize(x, y, btn.rect.w, 28)
            x += btn.rect.w + 4

        # Window Action buttons (positioned above window tree)
        w_rect = self._window_tree_rect()
        self._btn_new_window.resize(w_rect.x + 6, w_rect.y - 28, 54, 24)
        self._btn_del_window.resize(w_rect.x + 66, w_rect.y - 28, 54, 24)

        # Bottom timeline strip
        strip = self._bottom_strip_rect()
        sy = strip.y + 14
        sx = strip.x + _LEFT_COLUMN_W + 16

        self._btn_prev_frame.resize(sx, sy, 36, 28)
        sx += 42
        if self._play_btn:
            self._play_btn.resize(sx, sy, 54, 28)
            sx += 60
        self._btn_next_frame.resize(sx, sy, 36, 28)
        sx += 52

        # Frame range buttons
        self._btn_set_start.resize(sx, sy, 40, 28)
        sx += 46
        self._btn_set_end.resize(sx, sy, 40, 28)

    # -- Animation & Spritesheet Loading ---------------------------------

    def load_animation(self, anim_path: Path) -> None:
        try:
            loaded = load_animation_bundle(anim_path, data_root=self.data_root)
            self.loaded_anim = loaded
            self.character_name = anim_path.stem.replace(".anim", "")
            self.name_input.text = self.character_name
            self.hitbox_data.character_name = _safe_name(self.character_name)

            # Auto-select first clip
            clips = loaded.get_clip_names()
            self.current_clip = clips[0] if clips else None
            self.current_frame_idx = 0

            # Try to auto-load matching hitbox file if it exists
            self._auto_load_matching_hitbox()

            self._refresh_clip_tree()
            self._refresh_window_tree()
            self._update_frame_display(fit_view_first=True)
            self.toast.success(f"Animation loaded: {anim_path.name}")
        except Exception as e:
            self.toast.error(f"Failed to load animation: {e}")

    def _auto_load_matching_hitbox(self) -> None:
        hitbox_dir = self._get_hitbox_dir()
        target = hitbox_dir / f"{_safe_name(self.character_name)}.hitbox.json"
        if target.is_file():
            try:
                self.load_hitbox_file(target)
            except Exception:
                pass

    def _get_hitbox_dir(self) -> Path:
        if self.data_root is not None:
            return self.data_root / "character_collision"
        if self.loaded_anim is not None:
            return self.loaded_anim.json_path.parent
        return Path.cwd()

    def _update_frame_display(self, fit_view_first: bool = False) -> None:
        if self.loaded_anim is None or self.current_clip is None:
            self.canvas.set_surface(None)
            return

        cel = self.loaded_anim.get_frame_surface(self.current_clip, self.current_frame_idx)
        # Preserve zoom & pan when keep_viewport is True!
        self.canvas.set_surface(cel, keep_viewport=not fit_view_first)

        # Update ghost shapes and clip hull
        self._update_canvas_overlays()

    def _update_canvas_overlays(self) -> None:
        if self.current_clip is None:
            self.canvas.hull_rect = None
            self.canvas.ghost_shapes = []
            return

        clip_data = self.hitbox_data.clips.get(self.current_clip)
        if clip_data is None:
            self.canvas.hull_rect = None
            self.canvas.ghost_shapes = []
            return

        self.canvas.hull_rect = clip_data.compute_hull() if self.show_hull else None

        # Ghost shapes: shapes from other windows active on this frame
        ghosts: list[dict] = []
        for w in clip_data.windows:
            if w.id != self.selected_window_id and w.contains_frame(self.current_frame_idx):
                ghosts.extend(w.shapes)
        self.canvas.ghost_shapes = ghosts

    # -- Clip & Window Selection -----------------------------------------

    def _refresh_clip_tree(self) -> None:
        if self.loaded_anim is None:
            self.clip_tree.set_data([])
            return

        nodes = [
            TreeNode(id=name, label=name, data=name)
            for name in self.loaded_anim.get_clip_names()
        ]
        self.clip_tree.set_data(nodes)
        if self.current_clip:
            self.clip_tree.selected_ids = {self.current_clip}

    def _on_clip_selected(self, ids: list[str]) -> None:
        if not ids or ids[0] == self.current_clip:
            return
        self._flush_active_window()
        self.current_clip = ids[0]
        self.current_frame_idx = 0
        self.selected_window_id = None

        self._refresh_window_tree()
        self._update_frame_display(fit_view_first=False)

    def _refresh_window_tree(self) -> None:
        if self.current_clip is None:
            self.window_tree.set_data([])
            return

        clip_data = self.hitbox_data.clips.setdefault(self.current_clip, ClipHitboxesDraft(clip=self.current_clip))
        nodes = []
        for w in clip_data.windows:
            is_active = w.contains_frame(self.current_frame_idx)
            bullet = "●" if is_active else "○"
            shape_summary = "empty"
            if w.shapes:
                stype = w.shapes[0].get("type", "unknown")
                if stype == "polygon":
                    vs = w.shapes[0].get("vertices", [])
                    shape_summary = f"Poly ({len(vs)}v)"
                elif stype == "rectangle":
                    rw = int(w.shapes[0].get("width", 0))
                    rh = int(w.shapes[0].get("height", 0))
                    shape_summary = f"Rect ({rw}x{rh})"
                elif stype == "circle":
                    r = int(w.shapes[0].get("radius", 0))
                    shape_summary = f"Circle (r={r})"
                elif stype == "capsule":
                    r = int(w.shapes[0].get("radius", 0))
                    shape_summary = f"Capsule (r={r})"
            label = f"{bullet} {w.id} [{w.frame_start}..{w.frame_end}] {shape_summary}"
            nodes.append(TreeNode(id=w.id, label=label, data=w))
        self.window_tree.set_data(nodes)

        if self.selected_window_id:
            self.window_tree.selected_ids = {self.selected_window_id}

    def _on_window_selected(self, ids: list[str]) -> None:
        if not ids:
            return
        wid = ids[0]
        if wid == self.selected_window_id:
            return

        self._flush_active_window()
        self.selected_window_id = wid
        w = self._get_active_window()
        if w is not None:
            if w.shapes:
                self.canvas.load_shape_data(w.shapes[0])
            self.layer_sidebar.set_layer(w.collision_layer)
            self.layer_sidebar.set_mask(w.collision_mask)
            self._update_canvas_overlays()

    def _get_active_window(self) -> HitWindowDraft | None:
        if self.current_clip is None or self.selected_window_id is None:
            return None
        clip_data = self.hitbox_data.clips.get(self.current_clip)
        if clip_data is None:
            return None
        for w in clip_data.windows:
            if w.id == self.selected_window_id:
                return w
        return None

    def _flush_active_window(self) -> None:
        w = self._get_active_window()
        if w is not None:
            shape = self.canvas.get_shape_data()
            if shape:
                w.shapes = [shape]
            w.collision_layer = self.layer_sidebar.get_layer()
            w.collision_mask = self.layer_sidebar.get_mask()

    def _on_canvas_shape_modified(self) -> None:
        if self.current_clip is None:
            return
        w = self._get_active_window()
        shape = self.canvas.get_shape_data()
        if w is None:
            # If no window is selected yet, auto-create window hit_1 for current frame from this shape
            clip_data = self.hitbox_data.clips.setdefault(self.current_clip, ClipHitboxesDraft(clip=self.current_clip))
            wid = "hit_1"
            if any(win.id == wid for win in clip_data.windows):
                n = len(clip_data.windows) + 1
                while any(win.id == f"hit_{n}" for win in clip_data.windows):
                    n += 1
                wid = f"hit_{n}"
            new_w = HitWindowDraft(
                id=wid,
                frame_start=self.current_frame_idx,
                frame_end=self.current_frame_idx,
                shapes=[shape] if shape else [],
                collision_layer=self.layer_sidebar.get_layer(),
                collision_mask=self.layer_sidebar.get_mask(),
            )
            clip_data.windows.append(new_w)
            self.selected_window_id = wid
            self._refresh_window_tree()
            self._update_canvas_overlays()
            self.toast.success(f"Bound shape to new window {wid}")
            return

        if shape:
            w.shapes = [shape]
            self._update_canvas_overlays()
            self._refresh_window_tree()

    def _on_layer_mask_changed(self, layer: int, mask: int) -> None:
        w = self._get_active_window()
        if w is not None:
            w.collision_layer = layer
            w.collision_mask = mask

    def _new_window(self) -> None:
        if self.current_clip is None:
            self.toast.error("Select or load an animation clip first")
            return

        self._flush_active_window()
        clip_data = self.hitbox_data.clips.setdefault(self.current_clip, ClipHitboxesDraft(clip=self.current_clip))

        # Auto generate window ID
        n = len(clip_data.windows) + 1
        while any(w.id == f"hit_{n}" for w in clip_data.windows):
            n += 1
        wid = f"hit_{n}"

        active_w = self._get_active_window()
        cur_shape = self.canvas.get_shape_data()

        # If previous window already has this exact shape, generate a fresh distinct shape
        # so clicking + New multiple times doesn't stack identical shapes invisibly
        if active_w is not None and active_w.shapes and cur_shape:
            if self.canvas.shape_type == "polygon":
                shape = {
                    "type": "polygon",
                    "vertices": [(8.0, 8.0), (24.0, 8.0), (24.0, 24.0), (8.0, 24.0)],
                    "offset": (0.0, 0.0),
                }
            elif self.canvas.shape_type == "circle":
                shape = {"type": "circle", "radius": 12.0, "offset": (16.0, 16.0)}
            elif self.canvas.shape_type == "capsule":
                shape = {"type": "capsule", "radius": 8.0, "height": 16.0, "offset": (16.0, 8.0)}
            else:
                shape = {"type": "rectangle", "width": 24.0, "height": 24.0, "offset": (4.0, 4.0)}
            self.canvas.load_shape_data(shape)
        else:
            shape = cur_shape or {"type": "rectangle", "width": 24.0, "height": 24.0, "offset": (4.0, 4.0)}

        new_w = HitWindowDraft(
            id=wid,
            frame_start=self.current_frame_idx,
            frame_end=self.current_frame_idx,
            shapes=[shape] if shape else [],
            collision_layer=self.layer_sidebar.get_layer(),
            collision_mask=self.layer_sidebar.get_mask(),
        )
        clip_data.windows.append(new_w)
        self.selected_window_id = wid
        self._refresh_window_tree()
        self._update_canvas_overlays()
        self.toast.success(f"Created {wid} on frame {self.current_frame_idx}")

    def _delete_selected_window(self) -> None:
        if self.current_clip is None or self.selected_window_id is None:
            return
        clip_data = self.hitbox_data.clips.get(self.current_clip)
        if clip_data is None:
            return

        clip_data.windows = [w for w in clip_data.windows if w.id != self.selected_window_id]
        self.selected_window_id = None
        self._refresh_window_tree()
        self._update_canvas_overlays()
        self.toast.success("Window deleted")

    def _set_window_range(self, is_start: bool) -> None:
        w = self._get_active_window()
        if w is None:
            self.toast.error("No window selected")
            return

        if is_start:
            w.frame_start = self.current_frame_idx
            if w.frame_start > w.frame_end:
                w.frame_end = w.frame_start
        else:
            w.frame_end = self.current_frame_idx
            if w.frame_start > w.frame_end:
                w.frame_start = w.frame_end

        self._refresh_window_tree()
        self._update_canvas_overlays()
        self.toast.success(f"Window range: [{w.frame_start} .. {w.frame_end}]")

    # -- Frame Navigation & Playback -------------------------------------

    def _prev_frame(self) -> None:
        if self.loaded_anim is None or self.current_clip is None:
            return
        frames = self.loaded_anim.get_clip_frames(self.current_clip)
        if not frames:
            return
        self.current_frame_idx = (self.current_frame_idx - 1) % len(frames)
        self._refresh_window_tree()
        self._update_frame_display(fit_view_first=False)

    def _next_frame(self) -> None:
        if self.loaded_anim is None or self.current_clip is None:
            return
        frames = self.loaded_anim.get_clip_frames(self.current_clip)
        if not frames:
            return
        self.current_frame_idx = (self.current_frame_idx + 1) % len(frames)
        self._refresh_window_tree()
        self._update_frame_display(fit_view_first=False)

    def _toggle_playback(self) -> None:
        self.is_playing = not self.is_playing
        if self._play_btn:
            self._play_btn.text = "Pause" if self.is_playing else "Play"
            self._play_btn.active = self.is_playing

    def update(self, dt: float, screen: Surface | None = None) -> None:
        """Update animation playback frame timer and toast animations."""
        scr = screen or pygame.display.get_surface()
        if scr is not None:
            self.toast.update(scr, dt)

        if not self.is_playing or self.loaded_anim is None or self.current_clip is None:
            return

        frames = self.loaded_anim.get_clip_frames(self.current_clip)
        if len(frames) <= 1:
            return

        frame_duration = 1.0 / max(1.0, self.playback_fps)
        self._playback_timer += dt
        if self._playback_timer >= frame_duration:
            self._playback_timer -= frame_duration
            self.current_frame_idx = (self.current_frame_idx + 1) % len(frames)
            self._refresh_window_tree()
            self._update_frame_display(fit_view_first=False)

    # -- Shape & View Toggles --------------------------------------------

    def _select_shape_type(self, stype: str) -> None:
        self.canvas.set_shape_type(stype)  # type: ignore
        for k, btn in self._shape_buttons.items():
            btn.active = (k == stype)

    def _toggle_grid(self) -> None:
        self.canvas.show_grid = not self.canvas.show_grid
        self._btn_grid.active = self.canvas.show_grid

    def _toggle_hull(self) -> None:
        self.show_hull = not self.show_hull
        self._btn_hull.active = self.show_hull
        self._update_canvas_overlays()

    def _on_name_changed(self, text: str) -> None:
        self.character_name = text.strip() or "character"
        self.hitbox_data.character_name = _safe_name(self.character_name)

    # -- File Dialogs & Save/Load ----------------------------------------

    def _open_load_anim_dialog(self) -> None:
        sw, sh = pygame.display.get_surface().get_size()
        base = self.data_root or Path.cwd()
        self._file_dialog_kind = "anim"
        self._file_dialog = FileManager(
            rect=Rect((sw - 800) // 2, (sh - 600) // 2, 800, 600),
            initial_dir=base,
            allowed_exts=[".anim.json"],
            on_select=self._on_file_selected,
            on_cancel=lambda: setattr(self, "_file_dialog", None),
            mode="open",
            draw_overlay=True,
        )

    def _open_load_hitbox_dialog(self) -> None:
        sw, sh = pygame.display.get_surface().get_size()
        base = self._get_hitbox_dir()
        base.mkdir(parents=True, exist_ok=True)
        self._file_dialog_kind = "hitbox"
        self._file_dialog = FileManager(
            rect=Rect((sw - 800) // 2, (sh - 600) // 2, 800, 600),
            initial_dir=base,
            allowed_exts=[".hitbox.json"],
            on_select=self._on_file_selected,
            on_cancel=lambda: setattr(self, "_file_dialog", None),
            mode="open",
            draw_overlay=True,
        )

    def _on_file_selected(self, path: Path) -> None:
        try:
            if self._file_dialog_kind == "anim":
                self.load_animation(path)
            elif self._file_dialog_kind == "hitbox":
                self.load_hitbox_file(path)
        finally:
            self._file_dialog = None
            self._file_dialog_kind = None

    def load_hitbox_file(self, path: Path) -> None:
        text = Path(path).read_text(encoding="utf-8")
        raw = json.loads(text)
        self.hitbox_data = CharacterHitboxesDraft.from_dict(raw)
        self.character_name = self.hitbox_data.character_name
        self.name_input.text = self.character_name
        self.current_hitbox_path = Path(path)
        self.selected_window_id = None
        self._refresh_window_tree()
        self._update_canvas_overlays()
        self.toast.success(f"Hitbox loaded: {path.name}")

    def save(self) -> Path:
        self._flush_active_window()
        out_dir = self._get_hitbox_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{_safe_name(self.character_name)}.hitbox.json"
        save_path = out_dir / filename

        # Validate polygons for convexity
        for cname, clip in self.hitbox_data.clips.items():
            for w in clip.windows:
                for s in w.shapes:
                    if s.get("type") == "polygon" and not is_convex_polygon(s.get("vertices", [])):
                        self.toast.warning(f"Clip '{cname}' {w.id}: concave polygon (SAT expects convex)")

        data = self.hitbox_data.to_dict()
        save_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.current_hitbox_path = save_path
        self.toast.success(f"Saved: {filename}")
        return save_path

    # -- Event Handling --------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self._file_dialog is not None:
            return self._file_dialog.handle_event(event)

        if self.layer_sidebar.handle_event(event):
            return True

        if self.layer_sidebar.handle_toggle_event(event):
            return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_l and not self.name_input.is_focused:
            if not is_cmd_or_ctrl(pygame.key.get_mods()):
                self.layer_sidebar.toggle()
                return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_s and is_cmd_or_ctrl(pygame.key.get_mods()):
                self.save()
                return True
            if event.key == pygame.K_SPACE and not self.name_input.is_focused:
                self._toggle_playback()
                return True
            if event.key == pygame.K_LEFT:
                self._prev_frame()
                return True
            if event.key == pygame.K_RIGHT:
                self._next_frame()
                return True

        if self.name_input.handle_event(event):
            return True

        for btn in self._buttons:
            if btn.handle_event(event):
                return True

        if self.clip_tree.handle_event(event):
            return True

        if self.window_tree.handle_event(event):
            return True

        if self.canvas.handle_event(event):
            return True

        return False

    # -- Drawing ---------------------------------------------------------

    def draw(self, screen: Surface) -> None:
        self._ensure_fonts()

        # Canvas & panels
        self.canvas.draw(screen)

        # Toolbar
        self._draw_toolbar(screen)

        # Left Column (Clips & Windows)
        self._draw_left_column(screen)

        # Bottom Strip
        self._draw_bottom_strip(screen)

        # Sidebar & Toggle
        self.layer_sidebar.draw_toggle_button(screen)
        self.layer_sidebar.draw(screen)

        # Toast notifications
        self.toast.draw(screen)

        # Tooltips overlay
        self.tooltip.hide()
        mouse = pygame.mouse.get_pos()
        for btn in self._buttons:
            if btn.rect.collidepoint(mouse) and getattr(btn, "tooltip_text", ""):
                self.tooltip.show(btn.tooltip_text, (mouse[0] + 12, mouse[1] + 12))
                break
        self.tooltip.draw(screen)

        # Dialog overlay
        if self._file_dialog is not None:
            self._file_dialog.draw(screen)

    def _ensure_fonts(self) -> None:
        if self._font is None:
            self._font = font_manager.get_font(FONTS.name, FONTS.size_md, FontWeight.REGULAR)
        if self._font_sm is None:
            self._font_sm = font_manager.get_font(FONTS.name, FONTS.size_sm, FontWeight.REGULAR)

    def _draw_toolbar(self, screen: Surface) -> None:
        tb_rect = Rect(self.rect.x, self.rect.y, self.rect.w, _TOOLBAR_H)
        pygame.draw.rect(screen, (28, 32, 40), tb_rect)
        pygame.draw.line(screen, COLORS.border, (tb_rect.x, tb_rect.bottom), (tb_rect.right, tb_rect.bottom))

        if self._font_sm:
            lbl = self._font_sm.render("Name:", True, COLORS.text_dim)
            screen.blit(lbl, (self.rect.x + 12, self.rect.y + 14))

        self.name_input.draw(screen)

        # Sync button active states
        for stype, btn in self._shape_buttons.items():
            btn.active = (self.canvas.shape_type == stype)
        self._btn_grid.active = self.canvas.show_grid
        self._btn_hull.active = self.show_hull

        for btn in (
            self._btn_load_anim,
            self._btn_load_hitbox,
            self._btn_save,
            *self._shape_buttons.values(),
            self._btn_grid,
            self._btn_fit,
            self._btn_hull,
        ):
            btn.draw(screen)

    def _draw_left_column(self, screen: Surface) -> None:
        col_rect = Rect(self.rect.x, self.rect.y + _TOOLBAR_H, _LEFT_COLUMN_W, self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H)
        pygame.draw.rect(screen, (24, 27, 34), col_rect)
        pygame.draw.line(screen, COLORS.border, (col_rect.right, col_rect.y), (col_rect.right, col_rect.bottom))

        # Clips Header
        c_rect = self._clip_tree_rect()
        pygame.draw.rect(screen, (32, 36, 46), Rect(c_rect.x, c_rect.y, c_rect.w, 24))
        if self._font_sm:
            txt = self._font_sm.render("Animation Clips", True, COLORS.text)
            screen.blit(txt, (c_rect.x + 8, c_rect.y + 5))
        self.clip_tree.draw(screen)

        # Windows Header
        w_rect = self._window_tree_rect()
        header_y = w_rect.y - 32
        pygame.draw.rect(screen, (32, 36, 46), Rect(w_rect.x, header_y, w_rect.w, 32))
        if self._font_sm:
            txt = self._font_sm.render("Windows", True, COLORS.text)
            screen.blit(txt, (w_rect.x + 8, header_y + 8))

        self._btn_new_window.draw(screen)
        self._btn_del_window.draw(screen)
        self.window_tree.draw(screen)

    def _draw_bottom_strip(self, screen: Surface) -> None:
        strip = self._bottom_strip_rect()
        pygame.draw.rect(screen, (24, 27, 34), strip)
        pygame.draw.line(screen, COLORS.border, (strip.x, strip.y), (strip.right, strip.y))

        # Buttons
        self._btn_prev_frame.draw(screen)
        if self._play_btn:
            self._play_btn.draw(screen)
        self._btn_next_frame.draw(screen)
        self._btn_set_start.draw(screen)
        self._btn_set_end.draw(screen)

        # Frame Info Text
        if self._font:
            total_frames = len(self.loaded_anim.get_clip_frames(self.current_clip)) if (self.loaded_anim and self.current_clip) else 0
            frame_str = f"Frame: {self.current_frame_idx + 1} / {total_frames}" if total_frames > 0 else "No Animation Loaded"
            txt = self._font.render(frame_str, True, COLORS.text)
            screen.blit(txt, (strip.x + _LEFT_COLUMN_W + 280, strip.y + 18))

            w = self._get_active_window()
            if w is not None:
                is_active = w.contains_frame(self.current_frame_idx)
                status = "ACTIVE" if is_active else "INACTIVE"
                col = (100, 220, 140) if is_active else COLORS.text_dim
                w_str = f"Window {w.id}: [{w.frame_start} .. {w.frame_end}] ({status})"
                w_txt = self._font.render(w_str, True, col)
                screen.blit(w_txt, (strip.x + _LEFT_COLUMN_W + 430, strip.y + 18))
