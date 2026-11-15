"""
Data models for the Character Hitbox (Detection) Editor.

Represents per-clip active detection windows over animation frames,
serializing directly to and from <name>.hitbox.json format parsed by
tilemap-parser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def shape_bounds(shape: dict) -> tuple[float, float, float, float] | None:
    """Calculate sprite-local AABB (min_x, min_y, max_x, max_y) of a shape dict."""
    stype = shape.get("type")
    ox, oy = shape.get("offset", (0.0, 0.0))

    if stype == "rectangle":
        w = float(shape.get("width", 0.0))
        h = float(shape.get("height", 0.0))
        return (ox, oy, ox + w, oy + h)

    if stype == "circle":
        r = float(shape.get("radius", 0.0))
        return (ox - r, oy - r, ox + r, oy + r)

    if stype == "capsule":
        r = float(shape.get("radius", 0.0))
        h = float(shape.get("height", 0.0))
        return (ox - r, oy - r, ox + r, oy + h + r)

    if stype == "polygon":
        vs = shape.get("vertices", [])
        if not vs:
            return None
        xs = [v[0] + ox for v in vs]
        ys = [v[1] + oy for v in vs]
        return (min(xs), min(ys), max(xs), max(ys))

    return None


@dataclass
class HitWindowDraft:
    """One detection window active over an inclusive animation frame range."""

    id: str
    frame_start: int
    frame_end: int
    shapes: list[dict] = field(default_factory=list)
    collision_layer: int = 1
    collision_mask: int = 0xFFFFFFFF
    properties: dict[str, Any] = field(default_factory=dict)

    def contains_frame(self, frame: int) -> bool:
        return self.frame_start <= frame <= self.frame_end

    def bounds(self) -> tuple[float, float, float, float] | None:
        b: tuple[float, float, float, float] | None = None
        for s in self.shapes:
            sb = shape_bounds(s)
            if sb is None:
                continue
            if b is None:
                b = sb
            else:
                b = (min(b[0], sb[0]), min(b[1], sb[1]), max(b[2], sb[2]), max(b[3], sb[3]))
        return b

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "frames": [self.frame_start, self.frame_end],
            "shapes": self.shapes,
            "collision_layer": self.collision_layer,
            "collision_mask": self.collision_mask,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitWindowDraft:
        frames = data.get("frames", [0, 0])
        f_start = int(frames[0]) if len(frames) > 0 else 0
        f_end = int(frames[1]) if len(frames) > 1 else f_start
        props = dict(data.get("properties", {}))
        return cls(
            id=str(data.get("id", "hit_1")),
            frame_start=f_start,
            frame_end=f_end,
            shapes=list(data.get("shapes", [])),
            collision_layer=int(data.get("collision_layer", props.get("collision_layer", 1))),
            collision_mask=int(data.get("collision_mask", props.get("collision_mask", 0xFFFFFFFF))),
            properties=props,
        )


@dataclass
class ClipHitboxesDraft:
    """All detection windows defined for an animation clip."""

    clip: str
    windows: list[HitWindowDraft] = field(default_factory=list)

    def compute_hull(self) -> tuple[float, float, float, float] | None:
        hull: tuple[float, float, float, float] | None = None
        for w in self.windows:
            wb = w.bounds()
            if wb is None:
                continue
            if hull is None:
                hull = wb
            else:
                hull = (
                    min(hull[0], wb[0]),
                    min(hull[1], wb[1]),
                    max(hull[2], wb[2]),
                    max(hull[3], wb[3]),
                )
        return hull

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [w.to_dict() for w in self.windows],
        }

    @classmethod
    def from_dict(cls, clip_name: str, data: dict[str, Any]) -> ClipHitboxesDraft:
        hits = data.get("hits", [])
        windows = [HitWindowDraft.from_dict(h) for h in hits]
        return cls(clip=clip_name, windows=windows)


@dataclass
class CharacterHitboxesDraft:
    """Top-level hitbox container matching <name>.hitbox.json format."""

    character_name: str
    clips: dict[str, ClipHitboxesDraft] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_name": self.character_name,
            "clips": {name: clip.to_dict() for name, clip in self.clips.items() if clip.windows},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterHitboxesDraft:
        name = str(data.get("character_name", "character"))
        clips_data = data.get("clips", {})
        clips = {
            cname: ClipHitboxesDraft.from_dict(cname, cdata)
            for cname, cdata in clips_data.items()
        }
        return cls(character_name=name, clips=clips)
