import json
from pathlib import Path

import pygame
import pytest
from pygame import Rect, Surface

from plugins.character_hitbox.editor import CharacterHitboxEditor
from plugins.character_hitbox.models import (
    CharacterHitboxesDraft,
    ClipHitboxesDraft,
    HitWindowDraft,
    shape_bounds,
)


def test_shape_bounds():
    rect = {"type": "rectangle", "width": 20.0, "height": 30.0, "offset": (5.0, 10.0)}
    assert shape_bounds(rect) == (5.0, 10.0, 25.0, 40.0)

    circle = {"type": "circle", "radius": 10.0, "offset": (20.0, 20.0)}
    assert shape_bounds(circle) == (10.0, 10.0, 30.0, 30.0)

    poly = {
        "type": "polygon",
        "vertices": [(0.0, 0.0), (15.0, 5.0), (5.0, 25.0)],
        "offset": (0.0, 0.0),
    }
    assert shape_bounds(poly) == (0.0, 0.0, 15.0, 25.0)


def test_hitbox_models_serialization():
    w = HitWindowDraft(
        id="blast_1",
        frame_start=1,
        frame_end=3,
        shapes=[
            {"type": "rectangle", "width": 16.0, "height": 16.0, "offset": (0.0, 0.0)}
        ],
        collision_layer=2,
        collision_mask=4,
        properties={"damage": 50},
    )
    assert w.contains_frame(0) is False
    assert w.contains_frame(1) is True
    assert w.contains_frame(2) is True
    assert w.contains_frame(3) is True
    assert w.contains_frame(4) is False

    w_dict = w.to_dict()
    assert w_dict["id"] == "blast_1"
    assert w_dict["frames"] == [1, 3]
    assert w_dict["collision_layer"] == 2

    w_restored = HitWindowDraft.from_dict(w_dict)
    assert w_restored.id == w.id
    assert w_restored.frame_start == 1
    assert w_restored.frame_end == 3
    assert w_restored.collision_layer == 2

    clip = ClipHitboxesDraft(clip="attack", windows=[w])
    hull = clip.compute_hull()
    assert hull == (0.0, 0.0, 16.0, 16.0)

    char_draft = CharacterHitboxesDraft(character_name="hero", clips={"attack": clip})
    dumped = char_draft.to_dict()
    assert dumped["character_name"] == "hero"
    assert "attack" in dumped["clips"]
    assert len(dumped["clips"]["attack"]["hits"]) == 1

    reloaded = CharacterHitboxesDraft.from_dict(dumped)
    assert reloaded.character_name == "hero"
    assert len(reloaded.clips["attack"].windows) == 1


def test_hitbox_editor_frame_stepping_preserves_viewport(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)

    # Set custom zoom and offset
    editor.canvas.zoom = 5.5
    editor.canvas.offset_x = 123.0
    editor.canvas.offset_y = 456.0

    # Step frames
    editor._prev_frame()
    assert editor.canvas.zoom == 5.5
    assert editor.canvas.offset_x == 123.0
    assert editor.canvas.offset_y == 456.0

    editor._next_frame()
    assert editor.canvas.zoom == 5.5
    assert editor.canvas.offset_x == 123.0
    assert editor.canvas.offset_y == 456.0


def test_hitbox_editor_window_crud_and_save(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(
        Rect(0, 0, 900, 700), character_name="test_bot", data_root=tmp_path
    )
    editor.current_clip = "idle"

    # Create new window
    editor._new_window()
    assert editor.selected_window_id == "hit_1"

    # Change window range
    editor.current_frame_idx = 4
    editor._set_window_range(is_start=False)
    w = editor._get_active_window()
    assert w is not None
    assert w.frame_start == 0
    assert w.frame_end == 4

    editor.canvas.load_shape_data(
        {"type": "rectangle", "width": 16, "height": 12, "offset": [2, 3]}
    )
    editor._on_canvas_shape_modified()

    # Save to file
    save_path = editor.save()
    assert save_path.is_file()
    assert save_path.name == "test_bot.hitbox.json"

    # Verify content
    data = json.loads(save_path.read_text(encoding="utf-8"))
    assert data["character_name"] == "test_bot"
    assert "idle" in data["clips"]
    assert len(data["clips"]["idle"]["hits"]) == 1
    assert data["clips"]["idle"]["hits"][0]["frames"] == [0, 4]

    # Reload into editor
    editor.load_hitbox_file(save_path)
    assert len(editor.hitbox_data.clips["idle"].windows) == 1
    assert editor.hitbox_data.clips["idle"].windows[0].frame_end == 4

    # Delete window
    editor.selected_window_id = "hit_1"
    editor._delete_selected_window()
    assert len(editor.hitbox_data.clips["idle"].windows) == 0


def test_load_real_animation_and_cels():
    from plugins.character_hitbox.anim_loader import load_animation_bundle

    anim_path = Path(
        "../tilemap-parser/examples/tiny-quest/data/animations/player.anim.json"
    )
    if not anim_path.is_file():
        pytest.skip("Optional real animation fixture is unavailable")

    bundle = load_animation_bundle(anim_path)
    assert bundle.tile_w == 32
    assert bundle.tile_h == 32
    assert "idle" in bundle.get_clip_names()

    cel = bundle.get_frame_surface("idle", 0)
    assert cel is not None
    assert cel.get_size() == (32, 32)


def test_parser_compatibility():
    import sys

    # Add tilemap-parser to sys.path
    parser_src = Path(__file__).resolve().parents[2] / "tilemap-parser" / "src"
    if str(parser_src) not in sys.path:
        sys.path.insert(0, str(parser_src))

    collision = pytest.importorskip(
        "tilemap_parser.parser.collision",
        reason="Optional sibling tilemap-parser checkout is unavailable",
    )
    if not hasattr(collision, "parse_character_hitboxes"):
        pytest.skip("Installed tilemap-parser does not expose hitbox parsing")
    parse_character_hitboxes = collision.parse_character_hitboxes

    draft = CharacterHitboxesDraft(
        character_name="hero",
        clips={
            "attack": ClipHitboxesDraft(
                clip="attack",
                windows=[
                    HitWindowDraft(
                        id="hit_slash",
                        frame_start=1,
                        frame_end=3,
                        shapes=[
                            {
                                "type": "rectangle",
                                "width": 24.0,
                                "height": 16.0,
                                "offset": (10.0, 5.0),
                            },
                            {"type": "circle", "radius": 12.0, "offset": (20.0, 15.0)},
                            {
                                "type": "polygon",
                                "vertices": [
                                    (0.0, 0.0),
                                    (10.0, 0.0),
                                    (10.0, 10.0),
                                    (0.0, 10.0),
                                ],
                                "offset": (0.0, 0.0),
                            },
                        ],
                        collision_layer=2,
                        collision_mask=4,
                        properties={"damage": 100},
                    )
                ],
            )
        },
    )

    data = draft.to_dict()
    parsed = parse_character_hitboxes(data)
    assert parsed.name == "hero"
    assert "attack" in parsed.clips
    assert len(parsed.clips["attack"].windows) == 1
    w = parsed.clips["attack"].windows[0]
    assert w.id == "hit_slash"
    assert w.frame_start == 1
    assert w.frame_end == 3
    assert len(w.shapes) == 3


def test_space_key_no_crash_on_input_box(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)
    # Simulate Space key down event
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, mod=0)
    # Should not raise AttributeError: 'InputBox' object has no attribute 'active'
    handled = editor.handle_event(event)
    assert handled is True
    assert editor.is_playing is False
    assert editor.canvas._space_held is True


def test_layer_sidebar_toggle(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)
    assert editor.layer_sidebar._visible is False

    # Simulate pressing 'L' key
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l, mod=0)
    handled = editor.handle_event(event)
    assert handled is True
    assert editor.layer_sidebar._visible is True

    # Press 'L' again to close
    handled = editor.handle_event(event)
    assert handled is True
    assert editor.layer_sidebar._visible is False


def test_toast_timer_dismissal(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    screen = Surface((800, 600))
    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)
    editor.toast.success("Test Toast", duration=1.0)
    assert len(editor.toast._toasts) == 1

    # Advance timer by 0.5s -> still active
    editor.update(0.5, screen=screen)
    assert len(editor.toast._toasts) == 1

    # Advance timer past duration -> dismissed!
    editor.update(2.0, screen=screen)
    assert len(editor.toast._toasts) == 0


def test_window_tree_rich_labels_and_multiple_new(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)
    editor.current_clip = "idle"

    # Click + New first time
    editor._new_window()
    assert editor.selected_window_id == "hit_1"

    # Click + New second time
    editor._new_window()
    assert editor.selected_window_id == "hit_2"

    nodes = editor.window_tree.roots
    assert len(nodes) == 2
    assert "hit_1 [0..0] active" in nodes[0].label
    assert "hit_2 [0..0] active" in nodes[1].label
    assert all(node.label.isascii() for node in nodes)


def test_canvas_shape_auto_bind_new_window(tmp_path: Path):
    if not pygame.get_init():
        pygame.init()

    editor = CharacterHitboxEditor(Rect(0, 0, 800, 600), data_root=tmp_path)
    editor.current_clip = "attack"
    editor.selected_window_id = None

    # Load polygon on canvas
    poly = {
        "type": "polygon",
        "vertices": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        "offset": (0.0, 0.0),
    }
    editor.canvas.load_shape_data(poly)
    # Loading is silent; a subsequent actual edit auto-creates a window.
    assert editor.selected_window_id is None
    editor._on_canvas_shape_modified()
    assert editor.selected_window_id == "hit_1"
    w = editor._get_active_window()
    assert w is not None
    assert w.shapes[0]["type"] == "polygon"
    assert len(w.shapes[0]["vertices"]) == 4
