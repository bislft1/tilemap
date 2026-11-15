"""Headless pointer-driven regression tests for ownership and authoring."""

import json
from copy import deepcopy
from pathlib import Path

import pygame
import pytest
from pygame import Rect, Surface

from plugins.character_hitbox.anim_loader import load_animation_bundle
from plugins.character_hitbox.editor import CharacterHitboxEditor
from plugins.character_hitbox.models import CharacterHitboxesDraft
from utils.font_manager import font_manager
from widgets.ui.shape_canvas import ShapeCanvas, is_convex_polygon


@pytest.fixture(autouse=True)
def display():
    pygame.init()
    pygame.display.set_mode((1050, 800))
    font_manager.clear_cache()
    yield
    font_manager.clear_cache()
    pygame.quit()


def bundle(tmp_path, offset=(0, 0), durations=(100, 200, 300), loop=True):
    sheet = Surface((96 + offset[0], 32 + offset[1]), pygame.SRCALPHA)
    for n, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        sheet.fill(color, Rect(offset[0] + n * 32, offset[1], 32, 32))
    pygame.image.save(sheet, tmp_path / "sheet.png")
    path = tmp_path / "hero.anim.json"
    path.write_text(
        json.dumps(
            {
                "spritesheet_path": "sheet.png",
                "tile_size": [32, 32],
                "grid_offset": list(offset),
                "animations": {
                    name: {
                        "name": name,
                        "loop": loop,
                        "frames": [
                            {"variant_id": n, "duration_ms": ms}
                            for n, ms in enumerate(durations)
                        ],
                    }
                    for name in ("attack", "idle")
                },
            }
        )
    )
    return path


def editor(tmp_path):
    ed = CharacterHitboxEditor(Rect(0, 0, 1050, 800), data_root=tmp_path)
    ed.load_animation(bundle(tmp_path))
    ed.canvas.zoom = 3
    ed.canvas.offset_x = ed.canvas.offset_y = 60
    return ed


def key(canvas, code):
    canvas.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code, mod=0, unicode=""))


def pointer(target, kind, pos, button=1):
    data = {"pos": pos}
    if kind != pygame.MOUSEMOTION:
        data["button"] = button
    return target.handle_event(pygame.event.Event(kind, **data))


def polygon(ed, points=((0, 0), (20, 0), (20, 20), (0, 20))):
    ed._select_shape_type("polygon")
    for pt in points:
        pointer(ed, pygame.MOUSEBUTTONDOWN, ed.canvas.local_to_screen(pt))
        pointer(ed, pygame.MOUSEBUTTONUP, ed.canvas.local_to_screen(pt))
    key(ed, pygame.K_RETURN)
    return deepcopy(ed._get_active_window().shapes)


def test_new_on_next_frame_never_overwrites_previous_polygon(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    first = ed._get_active_window()
    ed._next_frame()
    assert not ed.canvas.get_shape_data()
    ed._new_window()
    assert not ed.canvas.get_shape_data()
    second = ed._get_active_window()
    assert second.shapes == []
    polygon(ed, ((3, 3), (15, 3), (15, 15)))
    assert first.shapes == original
    assert second.shapes != first.shapes
    ed._on_window_selected([first.id])
    assert ed.canvas.get_shape_data() == original[0]
    assert second.shapes[0]["vertices"] == [(3, 3), (15, 3), (15, 15)]
    path = ed.save()
    fresh = editor(tmp_path)
    fresh.load_hitbox_file(path)
    assert fresh.hitbox_data.to_dict() == json.loads(path.read_text())


def test_unbound_polygon_auto_binds_and_does_not_leak_between_frames_or_clips(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    ed._next_frame()
    assert ed.canvas.get_shape_data() == {}
    assert ed.canvas.polygon_vertices == []
    # Clicking an inactive frame starts a new polygon rather than moving the old one.
    polygon(ed, ((4, 4), (12, 4), (12, 12)))
    assert len(ed.hitbox_data.clips["attack"].windows) == 2
    ed._on_clip_selected(["idle"])
    assert ed.canvas.get_shape_data() == {}
    assert ed.canvas.ghost_shapes == []
    assert ed.hitbox_data.clips["attack"].windows[0].shapes == original
    ed._on_clip_selected(["attack"])
    ed._on_window_selected(["hit_1"])
    assert ed.canvas.get_shape_data() == original[0]


def test_range_allows_shared_geometry_only_on_active_frames(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    ed._next_frame()
    ed._set_window_range(False)
    assert ed.canvas.get_shape_data() == original[0]
    ed._next_frame()
    assert ed.canvas.get_shape_data() == {}
    assert ed.canvas.ghost_shapes == []
    ed._prev_frame()
    assert ed.canvas.get_shape_data() == original[0]
    assert (ed.canvas.zoom, ed.canvas.offset_x, ed.canvas.offset_y) == (3, 60, 60)


def test_empty_window_selection_and_delete_clear_stale_handles(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    ed.canvas.dragging_vertex_idx = 3
    ed._new_window()
    assert ed.canvas.dragging_vertex_idx is None
    assert ed.canvas.drawing_polygon == []
    ed._delete_selected_window()
    assert ed.canvas.get_shape_data() == {}
    assert ed.hitbox_data.clips["attack"].windows[0].shapes == original


def test_multiple_shapes_and_properties_survive_edit_and_save(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    w = ed._get_active_window()
    w.properties = {"damage": 12, "tag": "attack"}
    ed._select_shape_type("circle")
    origin = ed.canvas.local_to_screen((10, 10))
    end = ed.canvas.local_to_screen((14, 10))
    pointer(ed, pygame.MOUSEBUTTONDOWN, origin)
    pointer(ed, pygame.MOUSEMOTION, end)
    pointer(ed, pygame.MOUSEBUTTONUP, end)
    assert len(w.shapes) == 2
    circle = deepcopy(w.shapes[1])
    ed._cycle_shape()
    assert ed.canvas.shape_type == "polygon"
    key(ed, pygame.K_DELETE)
    assert w.shapes == [circle]
    ed._flush_active_window()
    ed._flush_active_window()
    assert w.shapes == [circle]
    raw = json.loads(ed.save().read_text())
    assert raw["clips"]["attack"]["hits"][0]["properties"] == w.properties
    assert raw["clips"]["attack"]["hits"][0]["collision_mask"] == 0xFFFFFFFF


def test_playback_respects_frame_durations_and_disables_editing(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    key(ed, pygame.K_SPACE)
    assert not ed.is_playing
    ed.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
    key(ed, pygame.K_RETURN)
    assert ed.is_playing and not ed.canvas.editable
    key(ed, pygame.K_DELETE)
    ed.update(0.31)
    assert ed.current_frame_idx == 2
    assert ed.hitbox_data.clips["attack"].windows[0].shapes == original
    ed.update(0.3)
    assert ed.current_frame_idx == 0
    key(ed, pygame.K_RETURN)
    assert not ed.is_playing and ed.canvas.editable


def test_short_polygon_blocks_navigation_until_cancelled(tmp_path):
    ed = editor(tmp_path)
    ed._select_shape_type("polygon")
    pointer(ed, pygame.MOUSEBUTTONDOWN, ed.canvas.local_to_screen((2, 2)))
    ed._next_frame()
    assert ed.current_frame_idx == 0
    assert len(ed.canvas.drawing_polygon) == 1
    with pytest.raises(ValueError):
        ed.save()
    key(ed, pygame.K_ESCAPE)
    ed._next_frame()
    assert ed.current_frame_idx == 1


def test_nonzero_polygon_offset_is_preserved_in_world_space(tmp_path):
    ed = editor(tmp_path)
    ed._new_window()
    w = ed._get_active_window()
    w.shapes = [
        {"type": "polygon", "vertices": [[0, 0], [10, 0], [10, 10]], "offset": [8, 9]},
        {"type": "circle", "radius": 4, "offset": [3, 3]},
    ]
    old = deepcopy(w.shapes)
    ed._sync_canvas()
    ed.save()
    assert w.shapes == old  # Merely loading/saving must not rewrite geometry.
    assert ed.canvas.polygon_vertices == [(8, 9), (18, 9), (18, 19)]


def test_load_save_path_and_invalid_save_leave_previous_file_intact(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    path = ed.save()
    custom = tmp_path / "custom.hitbox.json"
    path.rename(custom)
    ed.load_hitbox_file(custom)
    assert ed.save() == custom
    saved = custom.read_bytes()
    ed.hitbox_data.clips["attack"].windows[0].shapes[0]["vertices"] = [
        [0, 0],
        [1, 1],
        [2, 2],
    ]
    with pytest.raises(ValueError):
        ed.save()
    assert custom.read_bytes() == saved


def test_bad_load_is_transactional(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    original = ed.hitbox_data
    path = tmp_path / "bad.hitbox.json"
    path.write_text('{"clips":{"attack":{"hits":[{"frames":[3,1]}]}}}')
    with pytest.raises(ValueError):
        ed.load_hitbox_file(path)
    assert ed.hitbox_data is original


def test_grid_offset_slicing_and_invalid_variant(tmp_path):
    loaded = load_animation_bundle(bundle(tmp_path, offset=(7, 5)))
    assert loaded.get_frame_surface("attack", 1).get_at((0, 0))[:3] == (0, 255, 0)
    assert loaded.get_variant_surface(-1) is None
    path = bundle(tmp_path)
    raw = json.loads(path.read_text())
    raw["animations"]["attack"]["frames"][0]["variant_id"] = 9
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="outside"):
        load_animation_bundle(path)


def test_layout_draw_icons_and_text_focus(tmp_path):
    ed = editor(tmp_path)
    for width, height in ((800, 600), (1050, 800), (1280, 720)):
        ed.resize(Rect(0, 0, width, height))
        screen = Surface((width, height))
        ed.draw(screen)
        assert not ed._btn_new_window.rect.colliderect(ed.window_tree.rect)
        assert not ed._btn_new_window.rect.colliderect(ed.clip_tree.rect)
        assert not ed._btn_new_window.rect.colliderect(ed._btn_del_window.rect)
        for btn in ed._buttons:
            assert ed.rect.contains(btn.rect), (width, btn.text, btn.rect)
        assert ed._btn_prev_frame.icon_key == "skip-back"
        assert ed._btn_next_frame.icon_key == "skip-forward"
    ed.name_input.is_focused = True
    key(ed, pygame.K_RIGHT)
    assert ed.current_frame_idx == 0
    key(ed, pygame.K_g)
    assert ed.canvas.show_grid


def test_canvas_load_is_silent_and_vertex_zero_drag_continues_outside():
    canvas = ShapeCanvas(Rect(100, 100, 300, 300))
    calls = []
    canvas.on_modified = lambda: calls.append(1)
    canvas.zoom = 1
    canvas.load_shape_data(
        {"type": "polygon", "vertices": [[10, 10], [80, 10], [80, 80], [10, 80]]}
    )
    assert calls == []
    pointer(canvas, pygame.MOUSEBUTTONDOWN, (110, 110))
    pointer(canvas, pygame.MOUSEMOTION, (90, 90))
    pointer(canvas, pygame.MOUSEBUTTONUP, (90, 90))
    assert canvas.polygon_vertices[0] == (-10, -10)
    assert canvas.dragging_vertex_idx is None
    assert calls


def test_polygon_edge_insertion_body_move_and_delete(tmp_path):
    ed = editor(tmp_path)
    polygon(ed, ((0, 0), (60, 0), (60, 60), (0, 60)))
    c = ed.canvas
    pointer(ed, pygame.MOUSEBUTTONDOWN, c.local_to_screen((30, 0)))
    pointer(ed, pygame.MOUSEBUTTONUP, c.local_to_screen((30, 0)))
    assert len(c.polygon_vertices) == 5
    key(ed, pygame.K_DELETE)
    assert len(c.polygon_vertices) == 4
    pointer(ed, pygame.MOUSEBUTTONDOWN, c.local_to_screen((30, 30)))
    pointer(ed, pygame.MOUSEMOTION, c.local_to_screen((35, 35)))
    pointer(ed, pygame.MOUSEBUTTONUP, c.local_to_screen((35, 35)))
    assert c.polygon_vertices[0] == (5, 5)
    assert ed._get_active_window().shapes[0]["vertices"][0] == (5, 5)


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (1, 1), (2, 2)],
        [(0, 0), (0, 0), (1, 1)],
        [(0, 0), (10, 10), (0, 10), (10, 0)],
        [(0, 3), (10, 3), (2, 10), (5, 0), (8, 10)],
    ],
)
def test_invalid_polygon_validation(points):
    assert not is_convex_polygon(points)


def test_timeline_scrub_preserves_data_and_viewport(tmp_path):
    ed = editor(tmp_path)
    original = polygon(ed)
    track = ed._timeline_rect()
    pointer(ed, pygame.MOUSEBUTTONDOWN, (track.right - 2, track.centery))
    assert ed.current_frame_idx == 2
    assert ed.canvas.get_shape_data() == {}
    pointer(ed, pygame.MOUSEMOTION, (track.left + 2, track.centery))
    pointer(ed, pygame.MOUSEBUTTONUP, (track.left + 2, track.centery))
    assert ed.current_frame_idx == 0
    assert ed.canvas.get_shape_data() == original[0]
    assert (ed.canvas.zoom, ed.canvas.offset_x, ed.canvas.offset_y) == (3, 60, 60)


def test_close_and_document_replacement_guard_unsaved_work(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    closed = []
    ed.request_close(lambda: closed.append(True))
    assert ed.confirm_dialog.active
    key(ed, pygame.K_ESCAPE)
    assert not ed.confirm_dialog.active and closed == []
    ed.save()
    assert not ed.is_dirty
    ed.request_close(lambda: closed.append(True))
    assert closed == [True]
    ed._new_window()
    assert ed.is_dirty
    ed.request_close(lambda: closed.append(True))
    key(ed, pygame.K_RETURN)
    assert closed == [True, True]


def test_atomic_save_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    ed = editor(tmp_path)
    polygon(ed)
    path = ed.save()
    saved = path.read_bytes()
    before = set(path.parent.iterdir())

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        ed.save()
    assert path.read_bytes() == saved
    assert set(path.parent.iterdir()) == before


def test_name_edits_update_saved_character_name(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    ed.name_input.is_focused = True
    ed.name_input.select_all()
    ed.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, unicode="H", mod=0)
    )
    assert ed.character_name == "H"
    assert json.loads(ed.save().read_text())["character_name"] == "h"


def test_nonlooping_playback_stops_on_last_frame(tmp_path):
    ed = editor(tmp_path)
    ed.load_animation(bundle(tmp_path, loop=False))
    ed._toggle_playback()
    ed.update(1.0)
    assert ed.current_frame_idx == 2
    assert not ed.is_playing and ed.canvas.editable


@pytest.mark.parametrize("kind", ["rectangle", "circle", "capsule"])
def test_primitive_creation_resize_and_roundtrip(tmp_path, kind):
    ed = editor(tmp_path)
    ed._new_window()
    ed._select_shape_type(kind)
    c = ed.canvas
    pointer(ed, pygame.MOUSEBUTTONDOWN, c.local_to_screen((4, 4)))
    pointer(ed, pygame.MOUSEMOTION, c.local_to_screen((24, 24)))
    pointer(ed, pygame.MOUSEBUTTONUP, c.local_to_screen((24, 24)))
    assert c.get_shape_data()["type"] == kind
    if kind == "rectangle":
        handle, end = (24, 24), (28, 30)
    elif kind == "circle":
        handle, end = (4 + c.circle_radius, 4), (40, 4)
    else:
        handle, end = (24, 14), (30, 14)
    pointer(ed, pygame.MOUSEBUTTONDOWN, c.local_to_screen(handle))
    pointer(ed, pygame.MOUSEMOTION, c.local_to_screen(end))
    pointer(ed, pygame.MOUSEBUTTONUP, c.local_to_screen(end))
    expected = deepcopy(ed.hitbox_data.to_dict())
    path = ed.save()
    assert json.loads(path.read_text()) == json.loads(json.dumps(expected))
    assert not c.has_pointer_capture


def test_editor_releases_drag_over_window_tree_and_space_pans(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    c = ed.canvas
    pointer(ed, pygame.MOUSEBUTTONDOWN, c.local_to_screen((0, 0)))
    pointer(ed, pygame.MOUSEMOTION, ed.window_tree.rect.center)
    pointer(ed, pygame.MOUSEBUTTONUP, ed.window_tree.rect.center)
    assert not c.has_pointer_capture
    assert c.polygon_vertices[0] == c.screen_to_local(ed.window_tree.rect.center)
    key(ed, pygame.K_SPACE)
    start = c.rect.center
    pointer(ed, pygame.MOUSEBUTTONDOWN, start)
    pointer(ed, pygame.MOUSEMOTION, (start[0] + 12, start[1] + 10))
    pointer(ed, pygame.MOUSEBUTTONUP, (start[0] + 12, start[1] + 10))
    ed.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
    assert (c.offset_x, c.offset_y) == (72, 70)
    assert not ed.is_playing and not c.has_pointer_capture


def test_import_invalid_polygon_for_repair_but_block_invalid_output(tmp_path):
    ed = editor(tmp_path)
    polygon(ed)
    raw = ed.hitbox_data.to_dict()
    raw["clips"]["attack"]["hits"][0]["shapes"][0]["vertices"] = [
        [0, 0],
        [1, 1],
        [2, 2],
    ]
    path = tmp_path / "repair.hitbox.json"
    path.write_text(json.dumps(raw))
    ed.load_hitbox_file(path)
    ed._on_window_selected(["hit_1"])
    assert ed.canvas.has_shape
    with pytest.raises(ValueError, match="convex"):
        ed.save()
