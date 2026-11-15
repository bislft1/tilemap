"""
Character Hitbox (Detection) Editor.

A dedicated visual editor for authoring per-clip active detection windows
and hitboxes (<name>.hitbox.json) over character animation frames.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from functools import partial
from pathlib import Path

import pygame
from pygame import Rect, Surface

from utils.font_manager import FontWeight, font_manager
from utils.shortcuts import is_cmd_or_ctrl
from widgets.filemanager import FileManager
from widgets.input import InputBox
from widgets.ui.button import Button
from widgets.ui.collision_layer_sidebar import CollisionLayerSidebar
from widgets.ui.confirm_dialog import ConfirmDialog
from widgets.ui.shape_canvas import ShapeCanvas
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
_BOTTOM_STRIP_H = 132
_TOOLBAR_H = 84


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
        self._scrubbing = False

        # Hitbox data state
        self.hitbox_data = CharacterHitboxesDraft(
            character_name=_safe_name(character_name)
        )
        self.current_hitbox_path: Path | None = None
        self.selected_window_id: str | None = None
        self.selected_shape_idx = 0
        self._canvas_owner: tuple[str, str, int] | None = None
        self.show_hull: bool = True
        self.tooltip = TooltipManager()

        # Child Widgets
        self.name_input = InputBox(Rect(rect.x + 60, rect.y + 8, 140, 28))
        self.name_input.text = character_name

        self.clip_tree = TreeWidget(self._clip_tree_rect())
        self.clip_tree.on_selection_changed = self._on_clip_selected

        self.window_tree = TreeWidget(self._window_tree_rect())
        self.window_tree.on_selection_changed = self._on_window_selected

        self.canvas = ShapeCanvas(self._canvas_rect())
        self.canvas.editable = False
        self.canvas.on_modified = self._on_canvas_shape_modified

        self.layer_sidebar = CollisionLayerSidebar(
            self.rect,
            max_layers=32,
            initial_mask=0xFFFFFFFF,
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
        self._saved_data = deepcopy(self.hitbox_data.to_dict())
        self.confirm_dialog = ConfirmDialog(rect)

    # -- Geometry & Layout -----------------------------------------------

    def _clip_tree_rect(self) -> Rect:
        available_h = self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H
        half_h = available_h // 2
        return Rect(
            self.rect.x, self.rect.y + _TOOLBAR_H + 24, _LEFT_COLUMN_W, half_h - 24
        )

    def _window_tree_rect(self) -> Rect:
        available_h = self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H
        half_h = available_h // 2
        y = self.rect.y + _TOOLBAR_H + half_h
        return Rect(self.rect.x, y + 60, _LEFT_COLUMN_W, available_h - half_h - 60)

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
        self.confirm_dialog.editor_rect = rect
        self._layout_buttons()

    # -- Button Setup ----------------------------------------------------

    def _init_buttons(self) -> None:
        self._buttons.clear()
        self._shape_buttons.clear()

        # 1. Toolbar Actions
        self._btn_load_anim = Button(
            Rect(0, 0, 76, 28),
            "Anim",
            icon_key="image",
            tooltip_text="Load animation file (.anim.json)",
            on_click=self._open_load_anim_dialog,
        )
        self._btn_load_hitbox = Button(
            Rect(0, 0, 76, 28),
            "Load",
            icon_key="folder",
            tooltip_text="Load hitbox file (.hitbox.json)",
            on_click=self._open_load_hitbox_dialog,
        )
        self._btn_save = Button(
            Rect(0, 0, 76, 28),
            "Save",
            icon_key="save",
            tooltip_text="Save hitbox data (Ctrl+S)",
            on_click=self._save_from_ui,
        )

        self._buttons.extend(
            [self._btn_load_anim, self._btn_load_hitbox, self._btn_save]
        )

        # Shapes
        for stype in ("Rectangle", "Circle", "Capsule", "Polygon"):
            b = Button(
                Rect(0, 0, 72, 28),
                stype,
                on_click=partial(self._select_shape_type, stype.lower()),
            )
            self._shape_buttons[stype.lower()] = b
            self._buttons.append(b)

        # Toggles
        self._btn_grid = Button(
            Rect(0, 0, 48, 28),
            "Grid",
            tooltip_text="Toggle Grid (G)",
            on_click=self._toggle_grid,
        )
        self._btn_fit = Button(
            Rect(0, 0, 48, 28),
            "Fit",
            tooltip_text="Fit View (R)",
            on_click=lambda: self.canvas.fit_view(),
        )
        self._btn_hull = Button(
            Rect(0, 0, 48, 28),
            "Hull",
            tooltip_text="Toggle Clip Hull Box",
            on_click=self._toggle_hull,
        )
        self._buttons.extend([self._btn_grid, self._btn_fit, self._btn_hull])

        # 2. Window action buttons (placed in left panel)
        self._btn_new_window = Button(
            Rect(0, 0, 56, 24),
            "New",
            icon_key="plus",
            tooltip_text="Create an empty window on this frame",
            on_click=self._new_window,
        )
        self._btn_del_window = Button(
            Rect(0, 0, 56, 24),
            "Delete",
            icon_key="close",
            tooltip_text="Delete selected window",
            on_click=self._delete_selected_window,
        )
        self._buttons.extend([self._btn_new_window, self._btn_del_window])

        # 3. Bottom Strip (Timeline) buttons
        self._btn_prev_frame = Button(
            Rect(0, 0, 36, 28),
            icon_key="skip-back",
            tooltip_text="Previous Frame (Left Arrow)",
            on_click=self._prev_frame,
        )
        self._play_btn = Button(
            Rect(0, 0, 56, 28),
            icon_key="play",
            tooltip_text="Play / Pause Animation (Enter; finish polygon first)",
            on_click=self._toggle_playback,
        )
        self._btn_next_frame = Button(
            Rect(0, 0, 36, 28),
            icon_key="skip-forward",
            tooltip_text="Next Frame (Right Arrow)",
            on_click=self._next_frame,
        )

        self._btn_set_start = Button(
            Rect(0, 0, 42, 28),
            "Start",
            tooltip_text="Set active window start to current frame",
            on_click=lambda: self._set_window_range(True),
        )
        self._btn_set_end = Button(
            Rect(0, 0, 42, 28),
            "End",
            tooltip_text="Set active window end to current frame",
            on_click=lambda: self._set_window_range(False),
        )

        self._buttons.extend(
            [
                self._btn_prev_frame,
                self._play_btn,
                self._btn_next_frame,
                self._btn_set_start,
                self._btn_set_end,
            ]
        )

        self._btn_cycle_shape = Button(
            Rect(0, 0, 94, 28),
            "Next shape",
            on_click=self._cycle_shape,
            tooltip_text="Select the next shape in this window",
        )
        self._buttons.append(self._btn_cycle_shape)
        self._layout_buttons()

    def _layout_buttons(self) -> None:
        # Top toolbar
        y = self.rect.y + 8
        self.name_input.resize(self.rect.x + 56, y, 130, 28)

        x = self.name_input.rect.right + 10
        for btn in (self._btn_load_anim, self._btn_load_hitbox, self._btn_save):
            btn.resize(x, y, btn.rect.w, 28)
            x += btn.rect.w + 6

        x = self.rect.x + _LEFT_COLUMN_W + 8
        y += 38  # Dedicated second toolbar row
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
        self._btn_new_window.resize(w_rect.x + 6, w_rect.y - 28, 76, 24)
        self._btn_del_window.resize(w_rect.x + 88, w_rect.y - 28, 76, 24)

        # Bottom timeline strip
        strip = self._bottom_strip_rect()
        sy = strip.y + 14
        sx = strip.x + _LEFT_COLUMN_W + 16

        self._btn_prev_frame.resize(sx, sy, 36, 28)
        sx += 42
        if self._play_btn:
            self._play_btn.resize(sx, sy, 42, 28)
            sx += 48
        self._btn_next_frame.resize(sx, sy, 36, 28)
        sx += 52

        # Frame range buttons
        self._btn_set_start.resize(sx, sy, 54, 28)
        sx += 60
        self._btn_set_end.resize(sx, sy, 54, 28)
        self._btn_cycle_shape.resize(strip.x + 8, sy, 120, 28)

    # -- Animation & Spritesheet Loading ---------------------------------

    def load_animation(self, anim_path: Path) -> None:
        try:
            loaded = load_animation_bundle(anim_path, data_root=self.data_root)
            if not self._flush_active_window():
                return
            self._stop_playback()
            self.loaded_anim = loaded
            self.hitbox_data = CharacterHitboxesDraft(
                character_name=_safe_name(anim_path.stem.replace(".anim", ""))
            )
            self.current_hitbox_path = None
            self.selected_window_id = None
            self._canvas_owner = None
            self.canvas.clear_shape()
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
            self._saved_data = deepcopy(self.hitbox_data.to_dict())
            self.toast.success(f"Animation loaded: {anim_path.name}")
        except Exception as e:
            self.toast.error(f"Failed to load animation: {e}")

    def _auto_load_matching_hitbox(self) -> None:
        hitbox_dir = self._get_hitbox_dir()
        target = hitbox_dir / f"{_safe_name(self.character_name)}.hitbox.json"
        if target.is_file():
            try:
                self.load_hitbox_file(target)
            except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
                self.toast.error(f"Matching hitbox file could not be loaded: {exc}")

    def _get_hitbox_dir(self) -> Path:
        if self.data_root is not None:
            return self.data_root / "character_collision"
        if self.loaded_anim is not None:
            return self.loaded_anim.json_path.parent
        return Path.cwd()

    def _update_frame_display(self, fit_view_first: bool = False) -> None:
        self._sync_canvas()
        if self.loaded_anim is None or self.current_clip is None:
            self.canvas.set_surface(None)
            return

        cel = self.loaded_anim.get_frame_surface(
            self.current_clip, self.current_frame_idx
        )
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
            if w.contains_frame(self.current_frame_idx):
                for idx, shape in enumerate(w.shapes):
                    if self._canvas_owner != (self.current_clip, w.id, idx):
                        ghosts.append(shape)
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
        if not self._flush_active_window():
            return
        self._stop_playback()
        self.current_clip = ids[0]
        self.current_frame_idx = 0
        self.selected_window_id = None

        self._refresh_window_tree()
        self._update_frame_display(fit_view_first=False)

    def _refresh_window_tree(self) -> None:
        if self.current_clip is None:
            self.window_tree.set_data([])
            return

        clip_data = self.hitbox_data.clips.setdefault(
            self.current_clip, ClipHitboxesDraft(clip=self.current_clip)
        )
        nodes = []
        for w in clip_data.windows:
            is_active = w.contains_frame(self.current_frame_idx)
            status = "active" if is_active else "inactive"
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
            label = f"{w.id} [{w.frame_start}..{w.frame_end}] {status}: {len(w.shapes)} shapes; {shape_summary}"
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

        if not self._flush_active_window():
            return
        self.selected_window_id = wid
        self.selected_shape_idx = 0
        self._stop_playback()
        w = self._get_active_window()
        if w is not None:
            frames = (
                self.loaded_anim.get_clip_frames(self.current_clip)
                if self.loaded_anim
                else []
            )
            self.current_frame_idx = (
                min(w.frame_start, len(frames) - 1) if frames else w.frame_start
            )
        self._refresh_window_tree()
        self._update_frame_display()

    def _sync_canvas(self) -> None:
        """Load only the selected shape that is active on the displayed frame."""
        self.canvas.clear_shape()
        self._canvas_owner = None
        w = self._get_active_window()
        self.canvas.editable = not self.is_playing and self.current_clip is not None
        if w is None:
            return
        self.layer_sidebar.set_layer(w.collision_layer)
        self.layer_sidebar.set_mask(w.collision_mask)
        if w.contains_frame(self.current_frame_idx):
            self.selected_shape_idx = min(self.selected_shape_idx, len(w.shapes))
            self._canvas_owner = (self.current_clip, w.id, self.selected_shape_idx)
            if self.selected_shape_idx < len(w.shapes):
                self.canvas.load_shape_data(w.shapes[self.selected_shape_idx])
        self._update_canvas_overlays()

    def _cycle_shape(self) -> None:
        if not self._flush_active_window():
            return
        w = self._get_active_window()
        if w and w.shapes:
            self.selected_shape_idx = (
                0
                if self.selected_shape_idx >= len(w.shapes)
                else (self.selected_shape_idx + 1) % len(w.shapes)
            )
            self._sync_canvas()

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

    def _flush_active_window(self) -> bool:
        if self.canvas.drawing_polygon and len(self.canvas.drawing_polygon) < 3:
            self.toast.warning(
                "Finish the polygon (3+ points), or press Esc to cancel before navigating"
            )
            return False
        self.canvas.finish_polygon()
        return True

    def _on_canvas_shape_modified(self) -> None:
        if self.current_clip is None or self.is_playing:
            return
        shape = self.canvas.get_shape_data()
        owner = self._canvas_owner
        if owner is None:
            if not shape:
                return
            self._new_window(clear_canvas=False)
            owner = self._canvas_owner
        if owner is None:
            return
        clip, wid, idx = owner
        windows = self.hitbox_data.clips[clip].windows
        w = next((w for w in windows if w.id == wid), None)
        if w is None:
            return
        if shape:
            if idx < len(w.shapes):
                # Retain extra shape fields from imported files.
                w.shapes[idx] = {**w.shapes[idx], **deepcopy(shape)}
            else:
                w.shapes.append(deepcopy(shape))
        elif idx < len(w.shapes):
            w.shapes.pop(idx)
            self.selected_shape_idx = len(w.shapes)
            self._canvas_owner = (clip, wid, self.selected_shape_idx)
        self._update_canvas_overlays()
        self._refresh_window_tree()

    def _on_layer_mask_changed(self, layer: int, mask: int) -> None:
        if self.is_playing:
            return
        w = self._get_active_window()
        if w is not None:
            w.collision_layer = layer
            w.collision_mask = mask

    def _new_window(self, clear_canvas: bool = True) -> None:
        if self.current_clip is None:
            self.toast.error("Load an animation and select a clip first")
            return
        if clear_canvas and not self._flush_active_window():
            return
        self._stop_playback()
        clip_data = self.hitbox_data.clips.setdefault(
            self.current_clip, ClipHitboxesDraft(clip=self.current_clip)
        )
        n = 1
        while any(w.id == f"hit_{n}" for w in clip_data.windows):
            n += 1
        wid = f"hit_{n}"
        clip_data.windows.append(
            HitWindowDraft(
                id=wid,
                frame_start=self.current_frame_idx,
                frame_end=self.current_frame_idx,
                collision_layer=self.layer_sidebar.get_layer(),
                collision_mask=self.layer_sidebar.get_mask(),
            )
        )
        self.selected_window_id = wid
        self.selected_shape_idx = 0
        self._canvas_owner = (self.current_clip, wid, 0)
        if clear_canvas:
            self.canvas.clear_shape()
        self.canvas.editable = True
        self._refresh_window_tree()
        self._update_canvas_overlays()

    def _delete_selected_window(self) -> None:
        if self.current_clip is None or self.selected_window_id is None:
            return
        clip_data = self.hitbox_data.clips.get(self.current_clip)
        if clip_data is None:
            return

        clip_data.windows = [
            w for w in clip_data.windows if w.id != self.selected_window_id
        ]
        self.selected_window_id = None
        self._sync_canvas()
        self._refresh_window_tree()
        self._update_canvas_overlays()
        self.toast.success("Window deleted")

    def _set_window_range(self, is_start: bool) -> None:
        w = self._get_active_window()
        if w is None:
            self.toast.error("No window selected")
            return

        if not self._flush_active_window():
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
        self._sync_canvas()
        self.toast.success(f"Window range: [{w.frame_start} .. {w.frame_end}]")

    # -- Frame Navigation & Playback -------------------------------------

    def _go_to_frame(self, frame: int) -> None:
        if self.loaded_anim is None or self.current_clip is None:
            return
        frames = self.loaded_anim.get_clip_frames(self.current_clip)
        if not frames or not self._flush_active_window():
            return
        self._stop_playback()
        self.current_frame_idx = max(0, min(len(frames) - 1, frame))
        self._refresh_window_tree()
        self._update_frame_display()

    def _prev_frame(self) -> None:
        frames = (
            self.loaded_anim.get_clip_frames(self.current_clip)
            if self.loaded_anim and self.current_clip
            else []
        )
        if frames:
            self._go_to_frame((self.current_frame_idx - 1) % len(frames))

    def _next_frame(self) -> None:
        frames = (
            self.loaded_anim.get_clip_frames(self.current_clip)
            if self.loaded_anim and self.current_clip
            else []
        )
        if frames:
            self._go_to_frame((self.current_frame_idx + 1) % len(frames))

    def _timeline_rect(self) -> Rect:
        strip = self._bottom_strip_rect()
        x = strip.x + _LEFT_COLUMN_W + 292
        return Rect(x, strip.y + 14, max(1, strip.right - x - 12), 28)

    def _scrub_to(self, x: int) -> None:
        frames = (
            self.loaded_anim.get_clip_frames(self.current_clip)
            if self.loaded_anim and self.current_clip
            else []
        )
        if frames:
            track = self._timeline_rect()
            self._go_to_frame(int((x - track.x) / track.w * len(frames)))

    def _stop_playback(self) -> None:
        self.is_playing = False
        self._playback_timer = 0.0
        if self._play_btn:
            self._play_btn.icon_key = "play"
            self._play_btn.active = False
        self.canvas.editable = self.current_clip is not None

    def _toggle_playback(self) -> None:
        if self.is_playing:
            self._stop_playback()
            self._sync_canvas()
            return
        if (
            not self.loaded_anim
            or not self.current_clip
            or not self.loaded_anim.get_clip_frames(self.current_clip)
        ):
            return
        if not self._flush_active_window():
            return
        self.canvas.cancel_interaction()
        self.is_playing = True
        self.canvas.editable = False
        self._playback_timer = 0.0
        if self._play_btn:
            self._play_btn.icon_key = "pause"
            self._play_btn.active = True

    def update(self, dt: float, screen: Surface | None = None) -> None:
        """Update animation playback frame timer and toast animations."""
        scr = screen or pygame.display.get_surface()
        if scr is not None:
            self.toast.update(scr, dt)

        if not self.is_playing or self.loaded_anim is None or self.current_clip is None:
            return

        frames = self.loaded_anim.get_clip_frames(self.current_clip)
        if not frames:
            return

        self._playback_timer += max(0.0, dt)
        changed = False
        # Respect authored frame durations; bound work after long app stalls.
        for _ in range(10000):
            frame_duration = (
                max(1.0, frames[self.current_frame_idx].duration_ms) / 1000.0
            )
            if self._playback_timer < frame_duration:
                break
            self._playback_timer -= frame_duration
            clip = self.loaded_anim.library.animations[self.current_clip]
            if self.current_frame_idx == len(frames) - 1 and not clip.loop:
                self._stop_playback()
                break
            self.current_frame_idx = (self.current_frame_idx + 1) % len(frames)
            changed = True
        if changed:
            self._refresh_window_tree()
            self._update_frame_display()

    # -- Shape & View Toggles --------------------------------------------

    def _select_shape_type(self, stype: str) -> None:
        if not self._flush_active_window():
            return
        self._stop_playback()
        w = self._get_active_window()
        if w and w.contains_frame(self.current_frame_idx):
            self.selected_shape_idx = len(w.shapes)
            self._canvas_owner = (self.current_clip, w.id, self.selected_shape_idx)
        else:
            self._canvas_owner = None
        self.canvas.clear_shape()
        self.canvas.set_shape_type(stype)  # type: ignore
        for k, btn in self._shape_buttons.items():
            btn.active = k == stype

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
        self.canvas.cancel_interaction()
        self._stop_playback()
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
        self.canvas.cancel_interaction()
        self._stop_playback()
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

    @property
    def is_dirty(self) -> bool:
        return (
            bool(self.canvas.drawing_polygon)
            or self.hitbox_data.to_dict() != self._saved_data
        )

    def _confirm_discard(self, action) -> None:
        self.canvas.cancel_interaction()
        self._scrubbing = False
        self._stop_playback()
        if self.is_dirty:
            self.confirm_dialog.show(
                "Unsaved hitboxes",
                "Discard unsaved changes? Cancel to return and save with Ctrl+S.",
                on_confirm=action,
                on_cancel=lambda: None,
            )
        else:
            action()

    def request_close(self, on_close) -> None:
        self._confirm_discard(on_close)

    def _on_file_selected(self, path: Path) -> None:
        kind = self._file_dialog_kind
        self._file_dialog = None
        self._file_dialog_kind = None

        def load():
            # Discard is explicit here; a short unfinished polygon must not
            # prevent the confirmed replacement of the old document.
            self.canvas.drawing_polygon.clear()
            try:
                if kind == "anim":
                    self.load_animation(path)
                elif kind == "hitbox":
                    self.load_hitbox_file(path)
            except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
                self.toast.error(f"Load failed: {exc}")

        self._confirm_discard(load)

    def load_hitbox_file(self, path: Path) -> None:
        text = Path(path).read_text(encoding="utf-8")
        raw = json.loads(text)
        draft = CharacterHitboxesDraft.from_dict(raw)
        draft.validate(for_save=False)
        if not self._flush_active_window():
            return
        self._stop_playback()
        self.hitbox_data = draft
        self.character_name = self.hitbox_data.character_name
        self.name_input.text = self.character_name
        self.current_hitbox_path = Path(path)
        self.selected_window_id = None
        self._sync_canvas()
        self._refresh_window_tree()
        self._update_canvas_overlays()
        self._saved_data = deepcopy(self.hitbox_data.to_dict())
        self.toast.success(f"Hitbox loaded: {path.name}")

    def _save_from_ui(self) -> None:
        try:
            self.save()
        except (ValueError, OSError) as exc:
            self.toast.error(f"Save failed: {exc}")

    def save(self) -> Path:
        if not self._flush_active_window():
            raise ValueError("Finish or cancel the polygon before saving")
        self.hitbox_data.validate()
        out_dir = self._get_hitbox_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{_safe_name(self.character_name)}.hitbox.json"
        save_path = self.current_hitbox_path or out_dir / filename

        data = self.hitbox_data.to_dict()
        # Replace atomically so an interrupted save cannot truncate the last file.
        import tempfile

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=save_path.parent, delete=False
            ) as f:
                temp_path = Path(f.name)
                json.dump(data, f, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(save_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self.current_hitbox_path = save_path
        self._saved_data = deepcopy(self.hitbox_data.to_dict())
        self.toast.success(f"Saved: {save_path.name}")
        return save_path

    # -- Event Handling --------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self.confirm_dialog.active:
            self.confirm_dialog.handle_event(event)
            return True
        if self._file_dialog is not None:
            return self._file_dialog.handle_event(event)

        if self.layer_sidebar.visible:
            if event.type == pygame.KEYDOWN and event.key in (
                pygame.K_l,
                pygame.K_ESCAPE,
            ):
                self.layer_sidebar.close()
                return True
            self.layer_sidebar.handle_event(event)
            return True

        if self.layer_sidebar.handle_toggle_event(event):
            self.canvas.cancel_interaction()
            return True

        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._timeline_rect().collidepoint(event.pos)
        ):
            self.name_input.is_focused = False
            self._scrubbing = True
            self._scrub_to(event.pos[0])
            return True
        if event.type == pygame.MOUSEMOTION and self._scrubbing:
            self._scrub_to(event.pos[0])
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._scrubbing:
            self._scrubbing = False
            return True

        if self.canvas.has_pointer_capture and event.type in (
            pygame.MOUSEMOTION,
            pygame.MOUSEBUTTONUP,
        ):
            return self.canvas.handle_event(event)
        if (
            event.type == pygame.KEYDOWN
            and event.key == pygame.K_s
            and is_cmd_or_ctrl(getattr(event, "mod", pygame.key.get_mods()))
        ):
            self._save_from_ui()
            return True

        old_name = self.name_input.text
        name_handled = self.name_input.handle_event(event)
        if self.name_input.text != old_name:
            self._on_name_changed(self.name_input.text)
        if name_handled:
            return True
        if self.name_input.is_focused and event.type in (
            pygame.KEYDOWN,
            pygame.KEYUP,
            pygame.TEXTINPUT,
        ):
            return True

        if event.type == pygame.WINDOWFOCUSLOST:
            self.canvas.cancel_interaction()
            self._scrubbing = False
            self._stop_playback()
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_l:
                self.canvas.cancel_interaction()
                self.layer_sidebar.toggle()
                return True
            if (
                event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                and not self.canvas.drawing_polygon
            ):
                self._toggle_playback()
                return True
            if event.key == pygame.K_LEFT:
                self._prev_frame()
                return True
            if event.key == pygame.K_RIGHT:
                self._next_frame()
                return True

        for btn in self._buttons:
            if btn.handle_event(event):
                return True

        if self.clip_tree.handle_event(event):
            return True

        if self.window_tree.handle_event(event):
            return True

        return bool(self.canvas.handle_event(event))

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
        self.confirm_dialog.draw(screen)

    def _ensure_fonts(self) -> None:
        if self._font is None:
            self._font = font_manager.get_font(
                FONTS.name, FONTS.size_md, FontWeight.REGULAR
            )
        if self._font_sm is None:
            self._font_sm = font_manager.get_font(
                FONTS.name, FONTS.size_sm, FontWeight.REGULAR
            )

    def _draw_toolbar(self, screen: Surface) -> None:
        tb_rect = Rect(self.rect.x, self.rect.y, self.rect.w, _TOOLBAR_H)
        pygame.draw.rect(screen, (28, 32, 40), tb_rect)
        pygame.draw.line(
            screen,
            COLORS.border,
            (tb_rect.x, tb_rect.bottom),
            (tb_rect.right, tb_rect.bottom),
        )

        if self._font_sm:
            lbl = self._font_sm.render(
                "Name*" if self.is_dirty else "Name:", True, COLORS.text_dim
            )
            screen.blit(lbl, (self.rect.x + 12, self.rect.y + 14))

        if self._font_sm:
            label = self._font_sm.render("Add shape:", True, COLORS.text_dim)
            screen.blit(label, (self.rect.x + 12, self.rect.y + 52))
        self.name_input.draw(screen)

        # Sync button active states
        for stype, btn in self._shape_buttons.items():
            btn.active = self.canvas.shape_type == stype
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
        col_rect = Rect(
            self.rect.x,
            self.rect.y + _TOOLBAR_H,
            _LEFT_COLUMN_W,
            self.rect.h - _TOOLBAR_H - _BOTTOM_STRIP_H,
        )
        pygame.draw.rect(screen, (24, 27, 34), col_rect)
        pygame.draw.line(
            screen,
            COLORS.border,
            (col_rect.right, col_rect.y),
            (col_rect.right, col_rect.bottom),
        )

        # Clips Header
        c_rect = self._clip_tree_rect()
        pygame.draw.rect(
            screen, (32, 36, 46), Rect(c_rect.x, c_rect.y - 24, c_rect.w, 24)
        )
        if self._font_sm:
            txt = self._font_sm.render("Animation Clips", True, COLORS.text)
            screen.blit(txt, (c_rect.x + 8, c_rect.y - 19))
        self.clip_tree.draw(screen)

        # Windows Header
        w_rect = self._window_tree_rect()
        header_y = w_rect.y - 60
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
        pygame.draw.line(
            screen, COLORS.border, (strip.x, strip.y), (strip.right, strip.y)
        )

        # Buttons
        self._btn_prev_frame.draw(screen)
        if self._play_btn:
            self._play_btn.draw(screen)
        self._btn_next_frame.draw(screen)
        self._btn_set_start.draw(screen)
        self._btn_set_end.draw(screen)
        self._btn_cycle_shape.draw(screen)

        track = self._timeline_rect()
        pygame.draw.rect(screen, COLORS.panel_alt, track, border_radius=3)
        frames = (
            self.loaded_anim.get_clip_frames(self.current_clip)
            if self.loaded_anim and self.current_clip
            else []
        )
        if frames:
            cell_w = track.w / len(frames)
            clip_data = self.hitbox_data.clips.get(self.current_clip)
            if clip_data:
                for window in clip_data.windows:
                    start = max(0, min(len(frames), window.frame_start))
                    end = max(start, min(len(frames), window.frame_end + 1))
                    color = (
                        (75, 140, 105)
                        if window.id == self.selected_window_id
                        else (48, 79, 66)
                    )
                    pygame.draw.rect(
                        screen,
                        color,
                        Rect(
                            track.x + start * cell_w,
                            track.y + 5,
                            max(0, (end - start) * cell_w),
                            track.h - 10,
                        ),
                    )
            for idx in range(0, len(frames), max(1, len(frames) // 100)):
                x = round(track.x + idx * cell_w)
                pygame.draw.line(screen, COLORS.border, (x, track.y), (x, track.bottom))
            x = round(track.x + (self.current_frame_idx + 0.5) * cell_w)
            pygame.draw.line(
                screen, COLORS.text, (x, track.y + 1), (x, track.bottom - 1), 2
            )
        pygame.draw.rect(screen, COLORS.border, track, 1, border_radius=3)

        # Frame Info Text
        if self._font:
            total_frames = (
                len(self.loaded_anim.get_clip_frames(self.current_clip))
                if (self.loaded_anim and self.current_clip)
                else 0
            )
            frame_str = (
                f"Frame: {self.current_frame_idx} / {total_frames - 1}"
                if total_frames > 0
                else "No Animation Loaded"
            )
            txt = self._font.render(frame_str, True, COLORS.text)
            screen.blit(txt, (strip.x + _LEFT_COLUMN_W + 16, strip.y + 50))

            w = self._get_active_window()
            if w is not None:
                is_active = w.contains_frame(self.current_frame_idx)
                status = "ACTIVE" if is_active else "INACTIVE"
                col = (100, 220, 140) if is_active else COLORS.text_dim
                w_str = f"{w.id}: [{w.frame_start}..{w.frame_end}] {status} | Shape {min(self.selected_shape_idx + 1, len(w.shapes))}/{len(w.shapes)}"
                w_txt = self._font.render(w_str, True, col)
                screen.blit(w_txt, (strip.x + _LEFT_COLUMN_W + 195, strip.y + 50))

        if self._font_sm:
            guides = [
                "Load Anim > select frame > New > choose shape. Frames and ranges are zero-based, inclusive.",
                "Polygon: click points; Enter/right-click closes; drag vertices/body; click edge to insert; Del removes.",
                "Start/End: extend range | Timeline: scrub | Arrows: frame | Enter: play | Space+drag: pan | N: snap",
            ]
            for idx, line in enumerate(guides):
                screen.blit(
                    self._font_sm.render(line, True, COLORS.text_dim),
                    (strip.x + 8, strip.y + 76 + idx * 16),
                )
