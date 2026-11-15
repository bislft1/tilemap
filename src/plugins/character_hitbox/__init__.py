"""
Character Hitbox (Detection) Editor Plugin.
"""

from .editor import CharacterHitboxEditor
from .models import CharacterHitboxesDraft, ClipHitboxesDraft, HitWindowDraft

__all__ = [
    "CharacterHitboxEditor",
    "CharacterHitboxesDraft",
    "ClipHitboxesDraft",
    "HitWindowDraft",
]
