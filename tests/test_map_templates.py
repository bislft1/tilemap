"""Setup-template round-trip guarantees.

A template is the reuse primitive for new levels: everything except
placed content has to survive the template -> new level -> save ->
reload loop, and saving a template must not mutate the document it was
captured from.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest  # noqa: F401 - suite convention: fixtures file keeps pytest in scope

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from layers import Layer  # noqa: E402
from tilemap import Tilemap  # noqa: E402
from widgets.autotiler import AutotileGroup, AutotileRule  # noqa: E402

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeTileset:
    def __init__(self, stem: str, base: Path, sheet=(96, 32), tileset_type="tile"):
        import pygame

        self.path = Path(base) / f"{stem}.png"
        self.name = f"{stem}.png"
        self.surface = pygame.Surface(sheet, pygame.SRCALPHA)
        self.surface.fill((10, 20, 30, 255))
        self.tileset_type = tileset_type
        self.properties = {"name": stem}
        self.tile_properties = {3: {"solid": "yes"}}
        self.animation = None


class FakeTilesetWidget:
    """Mirrors the surface of the real widget's load contract."""

    def __init__(self):
        self.tilesets = []
        self.tileset_map = {}
        self.rule_hints: set[int] = set()

    def sync(self):
        self.tileset_map.clear()
        for i, ts in enumerate(self.tilesets):
            self.tileset_map[i] = ts

    def load_tileset_from_path(
        self, path, tileset_type, properties=None, tile_properties=None, animation=None
    ):
        import pygame

        ts = FakeTileset(Path(path).stem, path.parent, tileset_type=tileset_type)
        ts.path = Path(path)
        ts.properties = dict(properties or {})
        ts.tile_properties = {int(k): dict(v) for k, v in (tile_properties or {}).items()}
        ts.animation = animation
        self.tilesets.append(ts)
        self.tileset_map[len(self.tilesets) - 1] = ts

    def load_object_tileset_companions(self):
        return None


class FakeTileGrid:
    def __init__(self):
        self.zoom_level = 1.35
        self.scroll_x = 19
        self.scroll_y = 21


class FakeNotifications:
    def __init__(self):
        self.msgs = []

    def notify(self, text, color=(200, 200, 200), duration=3.0):
        self.msgs.append(str(text))

    def has(self, needle: str) -> bool:
        return any(needle in m for m in self.msgs)


def make_editor(map_dir: str) -> tuple[SimpleNamespace, Tilemap]:
    """Editor fake with a functioning save root (the paths
    save_template/save_map derive from the caller-provided dir)."""
    import pygame  # noqa: F401 - surfaces need an initialized pygame

    ed = SimpleNamespace()
    ed.data_root = Path(map_dir).parent
    ed.base_path = Path(map_dir).parent
    ed.notifications = FakeNotifications()
    ed.tileset_widget = None
    ed.autotiler = None
    ed.regex_automap_designer = None
    ed.tile_grid_widget = FakeTileGrid()
    ed.node_manager = None
    ed.node_selector = None
    ed.last_picked = None
    ed.active_alias = None
    tm = Tilemap(ed)
    ed.tilemap = tm
    return ed, tm


def make_rule(tileset_path: str, variant_ids=None) -> AutotileRule:
    return AutotileRule(
        name="grass",
        neighbors={(-1, 0), (1, 0), (0, -1), (0, 1)},
        tileset_path=tileset_path,
        variant_ids=list(variant_ids or [4]),
        tileset_index=0,
    )


def setup_populated_editor(tmp_path: Path):
    """Editor with 2 tilesets, 3 layers, rules, automap rules, content.

    Order matters: init_size first (it clears layers to one), then the
    authored layers+content, matching how a real working session looks.
    """
    ed, _ = make_editor(map_dir=str(tmp_path / "maps"))
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    ts_widget = FakeTilesetWidget()
    ts_widget.tilesets = [
        FakeTileset("terrain", assets),
        FakeTileset("rocks", assets, sheet=(64, 32)),
    ]
    ts_widget.sync()
    ed.tileset_widget = ts_widget

    designer = SimpleNamespace(
        groups=[
            AutotileGroup(
                "TerrainSet", rules=[make_rule(str(assets / "terrain.png"))]
            ),
            AutotileGroup(
                "Rocks", rules=[make_rule(str(assets / "rocks.png"), [2])]
            ),
        ],
    )
    designer.rules = [r for g in designer.groups for r in g.rules]
    ed.autotiler = designer
    ed.regex_automap_designer = SimpleNamespace(
        pattern_rules=[SimpleNamespace(name="pattern_a")],
        serialize_rules=lambda: [{"name": "pattern_a"}],
        deserialize_rules=lambda data: None,
    )

    tm = ed.tilemap
    tm.init_size((32, 32), (10, 10))
    tm.layer_manager.layers.clear()
    tm.layer_manager.create_layer("Ground", "tile")
    tm.layer_manager.create_layer("Stuff", "object")
    tm.layer_manager.create_layer("Backdrop", "image")
    tm.layer_manager.set_active_layer(0)

    tm.layer_manager.layers[0].tiles[(1, 1)] = {
        "pos": (1, 1),
        "ttype": 0,
        "variant": 2,
        "flip_h": True,
    }
    tm.layer_manager.layers[0].tiles[(2, 2)] = {
        "pos": (2, 2),
        "ttype": 1,
        "variant": 0,
    }
    tm.layer_manager.layers[1].objects[1] = {
        "area": {"x": 8, "y": 8, "w": 16, "h": 16},
        "ttype": 1,
        "tileset_type": "object",
        "variant": 0,
    }
    tm.layer_manager.layers[2].image_path = str(assets / "backdrop.png")
    tm.layer_manager.layers[2].image_rect = {"x": 0, "y": 0, "w": 32, "h": 32}

    tm.active_project_path = tmp_path / "castle.json"
    return ed, tm


def _load(path) -> dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# save_template: setup captured, content stripped, doc untouched
# ---------------------------------------------------------------------------


class TestSaveTemplate:
    def test_preserves_setup_and_strips_content(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)
        template_path = tmp_path / "castle.json"

        assert tm.save_template(template_path)

        payload = _load(template_path)
        tilesets = payload["resources"]["tilesets"]
        assert len(tilesets) == 2
        # tileset order is positional (ttype maps to list index); any
        # reordering here silently re-points painted tiles on next load
        assert tilesets[0]["path"].endswith("terrain.png")
        assert tilesets[1]["path"].endswith("rocks.png")
        assert tilesets[0]["properties"]["name"] == "terrain"
        assert tilesets[0]["tile_properties"]["3"] == {"solid": "yes"}

        groups = payload["project_state"]["groups"]
        assert [g["name"] for g in groups] == ["TerrainSet", "Rocks"]
        assert [r["variant_ids"] for g in groups for r in g["rules"]] == [[4], [2]]
        assert payload["project_state"]["automap_rules"] == [{"name": "pattern_a"}]

        layers = payload["data"]["layers"]
        assert [L["name"] for L in layers] == ["Ground", "Stuff", "Backdrop"]
        ground = next(L for L in layers if L["name"] == "Ground")
        assert ground["tiles"] == {}
        stuff = next(L for L in layers if L["name"] == "Stuff")
        assert stuff["objects"] == {}
        assert stuff["next_object_id"] == 1
        backdrop = next(L for L in layers if L["name"] == "Backdrop")
        assert "image_path" in backdrop
        assert "image_placements" not in backdrop

    def test_neutralizes_view_state(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)
        ed.tile_grid_widget.zoom_level = 2.5
        ed.tile_grid_widget.scroll_x = 40
        ed.tile_grid_widget.scroll_y = 50
        path = tmp_path / "view.json"

        tm.save_template(path)
        payload = _load(path)

        assert payload["meta"]["zoom_level"] == 1.0
        assert payload["meta"]["scroll"] == "0;0"
        assert payload["meta"]["offset"] == "0;0"

    def test_does_not_mark_document_clean(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        assert tm.has_unsaved_changes()

        ok = tm.save_template(tmp_path / "no_clean.json")

        assert ok
        # the template save is NOT a save of the map: dirty state and
        # path must be untouched so Ctrl+S still asks where to write
        assert tm.has_unsaved_changes()
        assert tm.active_project_path is not None

    def test_write_into_directory_reports_false(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)
        target = tmp_path / "blocker.json"
        target.mkdir()

        assert tm.save_template(target) is False

    def test_suffixless_path_gets_json(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        ok = tm.save_template(tmp_path / "named")

        assert ok
        assert (tmp_path / "named.json").exists()


# ---------------------------------------------------------------------------
# apply_template: restore setup, clean document, no sidecar leakage
# ---------------------------------------------------------------------------


class TestApplyTemplate:
    def _seed_template(self, tmp_path: Path) -> Path:
        """Build a template through the public save path.

        Round-trip discipline: what the writer emits is what the loader
        must read.
        """
        ed, _tm = setup_populated_editor(tmp_path)
        path = tmp_path / "seeded.json"
        ed.tilemap.save_template(path)
        return path

    def test_restores_setup_from_saved_template(self, tmp_path):
        template = self._seed_template(tmp_path)

        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        ed.autotiler = SimpleNamespace(groups=[AutotileGroup("EMPTY")], rules=[])

        tm.apply_template(template, (7, 5))

        assert [Path(ts.path).stem for ts in ed.tileset_widget.tilesets] == [
            "terrain",
            "rocks",
        ]
        assert [g.name for g in ed.autotiler.groups] == ["TerrainSet", "Rocks"]
        assert all(
            r.tileset_index in (0, 1)
            for group in ed.autotiler.groups
            for r in group.rules
        )

    def test_new_document_state_is_clean(self, tmp_path):
        template = self._seed_template(tmp_path)

        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        ed.autotiler = SimpleNamespace(groups=[AutotileGroup("EMPTY")], rules=[])

        tm.apply_template(template, (7, 5))

        assert tm.active_project_path is None
        assert tm.map_size == (7, 5)
        assert tm.has_unsaved_changes() is False
        assert all(not L.tiles and not L.objects for L in tm.layer_manager.layers)
        for layer in tm.layer_manager.layers:
            assert layer.next_object_id == 1

    def test_placeholder_holds_missing_file_positions(self, tmp_path):
        """Missing tileset files must stay in place so later indices don't
        shift and silently re-point painted tiles (same contract as normal
        map load)."""
        template = self._seed_template(tmp_path)

        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        ed.autotiler = SimpleNamespace(groups=[AutotileGroup("EMPTY")], rules=[])

        tm.apply_template(template, (7, 5))

        from utils.tileset_ops import is_placeholder

        assert len(ed.tileset_widget.tilesets) == 2
        assert all(
            is_placeholder(ts) for ts in ed.tileset_widget.tilesets
        ), "neither /tmp terrain.png nor rocks.png exists; both must come back as placeholders"
        order = [Path(ts.path).name for ts in ed.tileset_widget.tilesets]
        assert order[0].endswith("terrain.png")
        assert order[1].endswith("rocks.png")

    def test_node_sidecar_is_not_loaded(self, tmp_path):
        template = self._seed_template(tmp_path)
        loaded: list = []
        cleared: list = []

        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        ed.autotiler = SimpleNamespace(groups=[AutotileGroup("EMPTY")], rules=[])
        ed.node_manager = SimpleNamespace(
            load=lambda p: loaded.append(p),
            clear=lambda: cleared.append(True),
            save=lambda p: None,
        )

        tm.apply_template(template, (7, 5))

        assert loaded == []
        assert cleared == [True]

    def test_full_round_trip_template_to_saved_map(self, tmp_path):
        """template -> apply -> save -> reload: setup identical, content
        empty. This is the loop a real 'new level from template' session
        goes through, and the one where any schema drift would bite."""
        template = self._seed_template(tmp_path)
        template_payload = _load(template)

        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        ed.autotiler = SimpleNamespace(groups=[AutotileGroup("EMPTY")], rules=[])
        rules_store: list = []

        def _apply_rules(data) -> None:
            # real deserialize_rules mutates pattern_rules in place
            rules_store[:] = list(data)

        ed.regex_automap_designer = SimpleNamespace(
            pattern_rules=rules_store,
            serialize_rules=lambda: list(rules_store),
            deserialize_rules=_apply_rules,
        )

        tm.apply_template(template, (7, 5))
        # apply must push the template's automap rules into the designer
        assert ed.regex_automap_designer.pattern_rules, (
            "template automap rules lost at apply"
        )
        new_path = tmp_path / "maps" / "level_01.json"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        assert tm.save_map(new_path)

        saved = _load(new_path)
        assert saved["meta"]["tile_size"] == template_payload["meta"]["tile_size"]
        assert saved["meta"]["map_size"] == "7;5"
        # tileset paths are rewritten against the destination map dir,
        # so compare order and file names, not the stored relative path
        assert [
            Path(ts["path"]).name
            for ts in saved["resources"]["tilesets"]
        ] == [
            Path(ts["path"]).name
            for ts in template_payload["resources"]["tilesets"]
        ]
        assert [
            g["name"] for g in saved["project_state"]["groups"]
        ] == [g["name"] for g in template_payload["project_state"]["groups"]]
        assert saved["project_state"]["automap_rules"] == template_payload[
            "project_state"
        ]["automap_rules"]
        assert [L["name"] for L in saved["data"]["layers"]] == [
            L["name"] for L in template_payload["data"]["layers"]
        ]
        assert all(
            not L["tiles"] for L in saved["data"]["layers"]
        )


# ---------------------------------------------------------------------------
# new_level
# ---------------------------------------------------------------------------


class TestNewLevel:
    def test_keep_setup_clears_content_retains_meta(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        tm.new_level((32, 32), (5, 4), keep_setup=True)

        assert [L.name for L in tm.layer_manager.layers] == [
            "Ground",
            "Stuff",
            "Backdrop",
        ]
        assert all(not L.tiles for L in tm.layer_manager.layers)
        assert tm.map_size == (5, 4)
        assert tm.offset == (0, 0)
        assert tm.active_project_path is None
        assert len(ed.tileset_widget.tilesets) == 2
        assert tm.has_unsaved_changes() is False

    def test_blank_drops_setup_and_layers(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        tm.new_level((24, 24), (6, 6), keep_setup=False)

        assert ed.tileset_widget.tilesets == []
        assert [g.rules for g in ed.autotiler.groups] == [[]]
        assert [L.name for L in tm.layer_manager.layers] == ["Layer 1"]
        assert tm.tile_size == (24, 24)
        assert ed.last_picked is None

    def test_history_does_not_leak_across_levels(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        tm.history.save_state({"x": 1}, "painted")
        assert tm.history.can_undo

        tm.new_level((16, 16), (6, 6), keep_setup=True)

        assert not tm.history.can_undo
        assert not tm.history.can_redo

    def test_init_size_clears_history(self, tmp_path):
        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))

        tm.init_size((16, 16), (6, 6))
        tm.history.save_state({"x": 1}, "state")
        assert tm.history.can_undo

        tm.init_size((16, 16), (6, 6))

        assert not tm.history.can_undo

    def test_blank_resets_automap_rules(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)

        tm.new_level((16, 16), (6, 6), keep_setup=False)

        assert ed.regex_automap_designer.pattern_rules == []
        assert ed.regex_automap_designer.selected_rule_idx == -1


# ---------------------------------------------------------------------------
# rule path normalization
# ---------------------------------------------------------------------------


class TestRulePathNormalization:
    def test_apply_template_binds_rule_to_filesystem_truth(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)
        template = tmp_path / "rule.json"
        tm.save_template(template)

        tm.apply_template(template, (6, 6))

        rule = ed.autotiler.groups[0].rules[0]
        # absolute rule path survives arbitrary later save locations,
        # which is what _serialize_autotile_rule needs to rewrite safely
        assert Path(rule.tileset_path).is_absolute()
        assert Path(rule.tileset_path).name == "terrain.png"
        assert rule.tileset_index == 0

    def test_serialize_resolves_relative_rule_against_source_dir(self, tmp_path):
        ed, tm = setup_populated_editor(tmp_path)
        tm.active_project_path = tmp_path / "castle.json"

        rule = SimpleNamespace(
            tileset_path="./deep/thing.png",
            tileset_index=0,
            to_dict=lambda: {
                "name": "r",
                "neighbors": [],
                "tileset_path": "./deep/thing.png",
                "tileset_index": 0,
                "variant_ids": [0],
                "group_id": "r",
            },
        )

        out = tm._serialize_autotile_rule(rule, tmp_path / "somewhere")

        # ./deep/thing.png lives next to the map (tmp_path), not next to
        # save_dir (tmp_path/somewhere): rewrite climbs one level
        assert out["tileset_path"] == "../deep/thing.png"


# ---------------------------------------------------------------------------
# apply_map_payload defensive changes
# ---------------------------------------------------------------------------


class TestApplyMapPayloadHistory:
    def test_loading_a_map_clears_history(self, tmp_path):
        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        tm.init_size((16, 16), (4, 4))
        tm.history.save_state({"x": 1}, "stale")
        assert tm.history.can_undo

        payload = {
            "meta": {
                "tile_size": "16;16",
                "map_size": "4;4",
                "offset": "0;0",
                "render_scale": 1.0,
            },
            "resources": {"tilesets": []},
            "project_state": {"rules": []},
            "data": {"layers": []},
        }

        tm.apply_map_payload(tmp_path / "loaded.json", payload)

        assert not tm.history.can_undo

    def test_template_flag_suppresses_sidecar_load(self, tmp_path):
        ed, tm = make_editor(map_dir=str(tmp_path / "maps"))
        ed.tileset_widget = FakeTilesetWidget()
        tm.init_size((16, 16), (4, 4))
        sidecar_loaded: list = []
        ed.node_manager = SimpleNamespace(
            load=lambda p: sidecar_loaded.append(p),
            clear=lambda: None,
            save=lambda p: None,
        )

        payload = {
            "meta": {"tile_size": "16;16", "map_size": "4;4"},
            "resources": {"tilesets": []},
            "project_state": {"rules": []},
            "data": {"layers": []},
        }
        tm.apply_map_payload(tmp_path / "p.json", payload, load_nodes=False)

        assert sidecar_loaded == []


# ---------------------------------------------------------------------------
# Layer.clear_content contract
# ---------------------------------------------------------------------------


class TestClearContent:
    def test_clears_locked_layers_and_counters(self):
        layer = Layer("Locked stuff", "object", locked=True)
        layer.objects[1] = {"area": {}}
        layer.tiles[(0, 0)] = {"pos": (0, 0), "ttype": 0, "variant": 0}
        layer.next_object_id = 7

        layer.clear_content()

        assert layer.objects == {}
        assert layer.tiles == {}
        assert layer.next_object_id == 1

    def test_image_layer_resets_placements_and_counter(self):
        layer = Layer("bg", "image")
        layer.image_placements = [SimpleNamespace(pid=1, to_dict=lambda: {"pid": 1})]
        layer.next_placement_id = 9

        layer.clear_content()

        assert layer.image_placements == []
        assert layer.next_placement_id == 1
