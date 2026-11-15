"""
Data models for the Character Hitbox (Detection) Editor.

Represents per-clip active detection windows over animation frames,
serializing directly to and from <name>.hitbox.json format parsed by
tilemap-parser.
"""

from __future__ import annotations

import math
from copy import deepcopy
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
                b = (
                    min(b[0], sb[0]),
                    min(b[1], sb[1]),
                    max(b[2], sb[2]),
                    max(b[3], sb[3]),
                )
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
            shapes=deepcopy(data.get("shapes", [])),
            collision_layer=int(
                data.get("collision_layer", props.get("collision_layer", 1))
            ),
            collision_mask=int(
                data.get("collision_mask", props.get("collision_mask", 0xFFFFFFFF))
            ),
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

    def validate(self, *, for_save: bool = True) -> None:
        """Reject invalid geometry and ambiguous IDs before replacing saved data."""
        from widgets.ui.shape_canvas import is_convex_polygon

        for cname, clip in self.clips.items():
            ids = set()
            for window in clip.windows:
                context = f"{cname}/{window.id}"
                if not window.id or window.id in ids:
                    raise ValueError(
                        f"{context}: window IDs must be nonempty and unique per clip"
                    )
                ids.add(window.id)
                if window.frame_start < 0 or window.frame_end < window.frame_start:
                    raise ValueError(f"{context}: invalid inclusive frame range")
                if (
                    not 0 < window.collision_layer <= 0xFFFFFFFF
                    or not 0 <= window.collision_mask <= 0xFFFFFFFF
                ):
                    raise ValueError(f"{context}: layer/mask must be 32-bit values")
                if for_save and not window.shapes:
                    raise ValueError(
                        f"{context}: draw a shape or delete the empty window"
                    )
                for shape in window.shapes:

                    def number(value):
                        return (
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(value)
                        )

                    offset = shape.get("offset", [0, 0])
                    if (
                        not isinstance(offset, (list, tuple))
                        or len(offset) != 2
                        or not all(number(v) for v in offset)
                    ):
                        raise ValueError(
                            f"{context}: offset must contain two finite numbers"
                        )
                    kind = shape.get("type")
                    dims = {
                        "rectangle": ("width", "height"),
                        "circle": ("radius",),
                        "capsule": ("radius", "height"),
                    }
                    if kind == "polygon":
                        vertices = shape.get("vertices", [])
                        if (
                            not isinstance(vertices, (list, tuple))
                            or any(
                                not isinstance(v, (list, tuple))
                                or len(v) != 2
                                or not all(number(n) for n in v)
                                for v in vertices
                            )
                            or (for_save and not is_convex_polygon(vertices))
                        ):
                            raise ValueError(
                                f"{context}: polygons must be convex, nondegenerate, and have 3+ distinct vertices"
                            )
                    elif kind in dims:
                        if any(
                            not number(shape.get(key)) or shape[key] <= 0
                            for key in dims[kind]
                        ):
                            raise ValueError(
                                f"{context}: shape dimensions must be finite and positive"
                            )
                    else:
                        raise ValueError(f"{context}: unsupported shape type {kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_name": self.character_name,
            "clips": {
                name: clip.to_dict()
                for name, clip in self.clips.items()
                if clip.windows
            },
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
