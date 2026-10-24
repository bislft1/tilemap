from pathlib import Path
from typing import TYPE_CHECKING

import pygame
from pygame import Rect

from utils.serialization import deserialize_point

from .input import DigitInput
from .ui.button import Button
from .ui.context_menu import ContextMenu
from .ui.menubar import MenuAction, MenuSeparator
from .ui.theme import COLORS, FONTS, SPACING
from .widget_base import WidgetBase

if TYPE_CHECKING:
    from editor import Editor


TITLE_H = 30
START_ROW_H = 34
INFO_H = 22
CELL_H = 70
INPUT_H = 60
BTN_W = 120
BTN_H = 35


class MapSetup(WidgetBase):
    """New-level dialog.

    Offers explicit start points instead of the legacy half-state where
    "Create" cleared layers but silently kept tilesets and autotile
    rules: Blank (everything cleared), Current setup (content cleared,
    setup kept) and saved setup templates.
    """

    def __init__(self, editor: "Editor", center_rect: Rect):
        super().__init__(center_rect, padding=20, border_width=1)
        self.editor = editor
        self.visible = True
        self.error_message = ""

        self.font = FONTS.get_title_font()
        self.font_sm = FONTS.get_medium_font()
        self.font_info = FONTS.get_font(13)

        self.inputs: list[DigitInput] = []
        fields = [
            ("Map Width", "map_w", "30"),
            ("Map Height", "map_h", "20"),
            ("Tile Width", "tile_w", "32"),
            ("Tile Height", "tile_h", "32"),
        ]

        for i, (lbl, key, default) in enumerate(fields):
            self.inputs.append(
                DigitInput(Rect(0, 0, 0, 0), lbl, key, default, tab_index=i)
            )
        self._by_key = {i.key: i for i in self.inputs}

        self.start_mode = "blank"
        self.template_path: Path | None = None
        self._info_line = "Empty map: no tilesets, rules, or layers carried over."

        self._templates: list[Path] = []
        self._template_info: dict = {}

        self.btn_start_from = Button(
            Rect(0, 0, 0, 30),
            "Start from: Blank",
            font=self.font_sm,
            on_click=self._open_start_menu,
        )
        self._start_menu = ContextMenu()

        self.btn_create = Button(
            Rect(0, 0, BTN_W, BTN_H),
            "Create",
            accent=True,
            font=self.font,
            on_click=self.submit,
        )
        self.btn_open = Button(
            Rect(0, 0, BTN_W, BTN_H),
            "Open map",
            accent=True,
            font=self.font_sm,
            on_click=self._open_map,
        )

        self.refresh_templates()
        self._relayout()
        self.focus_first_field()

    # ------------------------------------------------------------------
    # start-point selection
    # ------------------------------------------------------------------

    def refresh_templates(self):
        self._templates = self.editor.list_templates()

    def _open_start_menu(self):
        if self._start_menu.is_open:
            self._start_menu.close()
            return

        can_keep = self.editor.tilemap.has_reusable_setup()
        items: list = [
            MenuAction(
                "Blank",
                callback=lambda: self._select_start("blank"),
                shortcut="",
                is_checked=lambda: self.start_mode == "blank",
            ),
            MenuAction(
                "Current setup",
                callback=lambda: self._select_start("keep"),
                shortcut="",
                is_checked=lambda: self.start_mode == "keep",
                is_enabled=lambda: can_keep,
            ),
            MenuSeparator(),
        ]
        for path in self._templates:
            items.append(
                MenuAction(
                    path.stem,
                    callback=lambda p=path: self._select_template(p),
                    shortcut="",
                    # both loop values must be bound: `checked` closes over
                    # the dialog's live selection, `tp` over this menu row
                    is_checked=lambda sel=self.template_path, tp=path: sel == tp,
                )
            )
        items.append(MenuSeparator())
        items.append(
            MenuAction("Refresh templates", callback=self.refresh_templates)
        )

        pos = (self.btn_start_from.rect.x, self.btn_start_from.rect.bottom + 4)
        self._start_menu.popup(items, pos, screen_size=(self.editor.width, self.editor.height))

    def _select_start(self, mode: str):
        self._start_menu.close()
        self.error_message = ""
        self.start_mode = mode
        self.template_path = None
        self._template_info = {}

        if mode == "blank":
            self._set_tile_values(32, 32, locked=False)
            self._set_map_values(30, 20)
            self._info_line = (
                "Empty map: no tilesets, rules, or layers carried over."
            )
        else:  # keep
            tm = self.editor.tilemap
            self._set_tile_values(tm.tile_size[0], tm.tile_size[1], locked=True)
            self._set_map_values(tm.map_size[0], tm.map_size[1])
            ts_count, layer_count = self._current_setup_counts()
            self._info_line = (
                f"Keeps setup: {ts_count} tileset(s), {layer_count} layer(s), "
                f"tile size {tm.tile_size[0]}x{tm.tile_size[1]} (locked). "
                "Content is cleared."
            )

        self.btn_start_from.text = (
            "Start from: Blank" if mode == "blank" else "Start from: current"
        )
        self.focus_first_field()

    def _select_template(self, path: Path):
        self._start_menu.close()
        self.error_message = ""
        try:
            payload = self.editor.tilemap.read_map_payload(path)
        except Exception as e:
            # Refuse rather than silently revert: the user picked a file
            # that cannot deliver what the dialog promises. Show which
            # file broke and why instead of an unexplained "Blank".
            self.error_message = f"Template '{path.name}' is unusable: {e}"
            self._start_menu.close()
            return

        meta = payload["meta"]
        try:
            tile_w, tile_h = deserialize_point(meta["tile_size"])
            map_w, map_h = deserialize_point(meta.get("map_size", "40;40"))
        except ValueError as e:
            self.error_message = f"Template '{path.name}' bad meta: {e}"
            return

        resources = payload.get("resources", {})
        tilesets = (
            resources.get("tilesets", [])
            if isinstance(resources, dict)
            else list(resources)
        )
        layers = payload.get("data", {}).get("layers", []) or []

        self.start_mode = "template"
        self.template_path = path
        self._template_info = {}
        self._set_tile_values(tile_w, tile_h, locked=True)
        self._set_map_values(map_w, map_h)
        self.btn_start_from.text = f"Start from: {path.stem}"
        self._info_line = (
            f"Template: {len(tilesets)} tileset(s), {len(layers)} layer(s), "
            f"tile size {tile_w}x{tile_h} (locked). Content is cleared."
        )
        self.focus_first_field()

    def _set_tile_values(self, w: int, h: int, *, locked: bool):
        self._by_key["tile_w"].text = str(w)
        self._by_key["tile_h"].text = str(h)
        self._by_key["tile_w"].input_box.read_only = locked
        self._by_key["tile_h"].input_box.read_only = locked

    def _set_map_values(self, w: int, h: int):
        self._by_key["map_w"].text = str(w)
        self._by_key["map_h"].text = str(h)

    def _current_setup_counts(self) -> tuple[int, int]:
        tm = self.editor.tilemap
        ts_widget = getattr(self.editor, "tileset_widget", None)
        ts_count = len(ts_widget.tilesets) if ts_widget else 0
        return ts_count, len(tm.layer_manager.layers)

    # ------------------------------------------------------------------
    # dialog plumbing
    # ------------------------------------------------------------------

    def focus_first_field(self):
        focusable = [i for i in self.inputs if not i.input_box.read_only]
        for o in self.inputs:
            o.is_focused = False
            o.selection_start = None
        if focusable:
            focusable[0].is_focused = True
            focusable[0].cursor_pos = len(focusable[0].text)

    def _relayout(self):
        cols = 2
        cell_w = self.content_rect.width // cols
        start_x = self.content_rect.x
        start_y = self.content_rect.y + TITLE_H + START_ROW_H + SPACING["md"]

        for i, inp in enumerate(self.inputs):
            row, col = divmod(i, cols)
            r = Rect(
                start_x + col * cell_w,
                start_y + row * CELL_H,
                cell_w - SPACING["sm"],
                INPUT_H,
            )
            inp.resize(r)

        rows = (len(self.inputs) + cols - 1) // cols
        last_input_bottom = start_y + (rows - 1) * CELL_H + INPUT_H

        cx = self.rect.centerx
        self.btn_start_from.rect = Rect(
            self.content_rect.x,
            self.content_rect.y + TITLE_H,
            self.content_rect.width,
            30,
        )
        btn_create_y = last_input_bottom + SPACING["xl"]
        self.btn_create.rect = Rect(cx - BTN_W // 2, btn_create_y, BTN_W, BTN_H)
        btn_open_y = btn_create_y + BTN_H + SPACING["md"]
        self.btn_open.rect = Rect(cx - BTN_W // 2, btn_open_y, BTN_W, BTN_H)

    def resize(self, center_rect: Rect):
        super().resize(center_rect.x, center_rect.y, center_rect.w, center_rect.h)
        self._relayout()

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.visible:
            return False

        if self._start_menu.handle_event(event):
            return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.visible = False
            return True

        if self.btn_create.handle_event(event):
            return True
        if self.btn_start_from.handle_event(event):
            return True
        if self.btn_open.handle_event(event):
            return True

        if (
            event.type == pygame.KEYDOWN
            and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
            and any(inp.is_focused for inp in self.inputs)
        ):
            self.submit()
            return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            focusable = [i for i in self.inputs if not i.input_box.read_only]
            if not focusable:
                return True
            focused = [i for i in focusable if i.is_focused]
            shift_held = pygame.key.get_mods() & pygame.KMOD_SHIFT

            if focused:
                current_idx = focused[0].tab_index
                if shift_held:
                    next_idx = (current_idx - 1) % len(self.inputs)
                else:
                    next_idx = (current_idx + 1) % len(self.inputs)
                # walk forward until we land on an editable input
                while self._by_key[
                    ["map_w", "map_h", "tile_w", "tile_h"][next_idx]
                ].input_box.read_only:
                    next_idx = (
                        next_idx + (len(self.inputs) - 1 if shift_held else 1)
                    ) % len(self.inputs)
            else:
                next_idx = 0 if not shift_held else len(self.inputs) - 1

            for o in self.inputs:
                o.is_focused = False
            target = self._by_key[["map_w", "map_h", "tile_w", "tile_h"][next_idx]]
            if not target.input_box.read_only:
                target.is_focused = True
                target.cursor_pos = len(target.text)
                target.selection_start = None
            return True

        for inp in self.inputs:
            if inp.handle_event(event):
                if inp.is_focused:
                    for o in self.inputs:
                        if o != inp:
                            o.is_focused = False
                return True
        return True

    def submit(self):
        try:
            vals = {i.key: i.get_value() for i in self.inputs}
            if any(v <= 0 for v in vals.values()):
                raise ValueError("Values must be > 0")
        except ValueError as e:
            self.error_message = str(e)
            return

        template_missing = self.start_mode == "template" and (
            not self.template_path or not self.template_path.exists()
        )
        if template_missing:
            self.error_message = "Selected template file is missing."
            return

        if self.editor.tilemap.has_unsaved_changes():
            self.editor.confirm_dialog.show(
                title="Discard unsaved changes?",
                message=(
                    "Creating a new level replaces the current map. "
                    "Unsaved changes will be lost."
                ),
                on_confirm=lambda: self._apply_new_level(vals),
                on_cancel=lambda: None,
            )
            return

        self._apply_new_level(vals)

    def _apply_new_level(self, vals: dict[str, int]):
        tm = self.editor.tilemap
        map_size = (vals["map_w"], vals["map_h"])
        try:
            if self.start_mode == "template":
                tm.apply_template(self.template_path, map_size)
            elif self.start_mode == "keep":
                tm.new_level(tm.tile_size, map_size, keep_setup=True)
            else:
                tm.new_level(
                    (vals["tile_w"], vals["tile_h"]), map_size, keep_setup=False
                )
        except Exception as e:
            from utils.error_handler import error_handler

            error_handler.capture(e, context="apply_new_level")
            self.error_message = f"Could not create level: {e}"
            return

        self.editor.post_map_setup()
        self.visible = False

    def _open_map(self):
        self.visible = False
        self.editor.perform_load()

    def draw(self, screen: pygame.Surface):
        if not self.visible:
            return

        self.draw_base(screen)

        title = self.font.render("New Level", True, COLORS.text)
        screen.blit(title, (self.content_rect.x, self.content_rect.y))

        self.btn_start_from.draw(screen)

        info = self.font_info.render(self._info_line, True, COLORS.text_dim)
        screen.blit(info, (self.content_rect.x, self.btn_start_from.rect.bottom + 4))

        for inp in self.inputs:
            inp.draw(screen)

        self.btn_create.draw(screen)
        self.btn_open.draw(screen)

        if self.error_message:
            err = FONTS.get_font(12).render(
                self.error_message, True, COLORS.danger
            )
            screen.blit(err, (self.content_rect.x, self.btn_create.rect.y - 20))

        self._start_menu.draw(screen)
