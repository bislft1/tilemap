"""
Animation and Spritesheet loading engine for the Character Hitbox Editor.

Handles robust path resolution, grid slicing, variant caching, and frame
retrieval for animated characters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pygame
from pygame import Rect, Surface

from plugins.sprite_animation.runtime_load import AnimationLibrary, parse_animation_library_file


class LoadedAnimation:
    """Holds parsed animation library, loaded spritesheet, and cached frame cels."""

    def __init__(
        self,
        library: AnimationLibrary,
        spritesheet: Surface,
        json_path: Path,
        spritesheet_path: Path,
    ):
        self.library = library
        self.spritesheet = spritesheet
        self.json_path = json_path
        self.spritesheet_path = spritesheet_path

        self.tile_w = int(library.tile_size[0])
        self.tile_h = int(library.tile_size[1])
        self.grid_offset_x = int(getattr(library, "grid_offset", [0, 0])[0]) if hasattr(library, "grid_offset") else 0
        self.grid_offset_y = int(getattr(library, "grid_offset", [0, 0])[1]) if hasattr(library, "grid_offset") else 0

        self._cel_cache: dict[int, Surface] = {}

    def get_variant_surface(self, variant_id: int) -> Surface | None:
        """Get or extract a single frame variant cel from the spritesheet."""
        if variant_id in self._cel_cache:
            return self._cel_cache[variant_id]

        tw, th = self.tile_w, self.tile_h
        if tw <= 0 or th <= 0 or self.spritesheet is None:
            return None

        avail_w = self.spritesheet.get_width() - self.grid_offset_x
        avail_h = self.spritesheet.get_height() - self.grid_offset_y
        if avail_w < tw or avail_h < th:
            return None

        cols = max(1, avail_w // tw)
        col = variant_id % cols
        row = variant_id // cols

        src = Rect(
            self.grid_offset_x + col * tw,
            self.grid_offset_y + row * th,
            tw,
            th,
        )

        if not self.spritesheet.get_rect().contains(src):
            return None

        cel = self.spritesheet.subsurface(src).copy()
        self._cel_cache[variant_id] = cel
        return cel

    def get_clip_names(self) -> list[str]:
        return list(self.library.animations.keys())

    def get_clip_frames(self, clip_name: str) -> list[Any]:
        clip = self.library.animations.get(clip_name)
        return clip.frames if clip is not None else []

    def get_frame_surface(self, clip_name: str, frame_index: int) -> Surface | None:
        frames = self.get_clip_frames(clip_name)
        if not frames or frame_index < 0 or frame_index >= len(frames):
            return None
        variant = frames[frame_index].variant_id
        return self.get_variant_surface(variant)


def load_animation_bundle(anim_path: Path, data_root: Path | None = None) -> LoadedAnimation:
    """Load an animation library and resolve its spritesheet surface."""
    p = Path(anim_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Animation file not found: {p}")

    library = parse_animation_library_file(p)
    sheet_ref = library.spritesheet_path
    if not sheet_ref:
        raise ValueError(f"Animation file {p.name} specifies no spritesheet_path")

    ref_path = Path(sheet_ref)
    candidates: list[Path] = []
    if ref_path.is_absolute():
        candidates.append(ref_path)
    else:
        candidates.append((p.parent / ref_path).resolve())
        candidates.append((p.parent.parent / ref_path).resolve())
        if data_root is not None:
            candidates.append((data_root / ref_path).resolve())
        for parent in p.parents:
            candidates.append((parent / ref_path).resolve())

    resolved_sheet_path: Path | None = None
    for cand in candidates:
        if cand.is_file():
            resolved_sheet_path = cand
            break

    if resolved_sheet_path is None:
        raise FileNotFoundError(
            f"Spritesheet not found for animation {p.name}: {sheet_ref!r} (checked {len(candidates)} paths)"
        )

    if not pygame.get_init():
        pygame.init()

    raw = pygame.image.load(str(resolved_sheet_path))
    if pygame.display.get_surface() is not None:
        try:
            surface = raw.convert_alpha() if raw.get_flags() & pygame.SRCALPHA else raw.convert()
        except pygame.error:
            surface = raw
    else:
        surface = raw

    return LoadedAnimation(
        library=library,
        spritesheet=surface,
        json_path=p,
        spritesheet_path=resolved_sheet_path,
    )
