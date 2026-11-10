"""
Standalone Image Viewer with Grid/Spritesheet Support
Opens images in a scrollable window with optional grid overlay and variant IDs for tilesets/spritesheets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pygame

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.standalone import load_standalone_theme  # noqa: E402
from widgets.ui.theme import COLORS, FONTS  # noqa: E402


def parse_size(text: str) -> tuple[int, int]:
    """Parse a size string formatted as 'N' or 'WxH' into (width, height)."""
    parts = text.lower().split("x")
    if len(parts) == 1:
        n = int(parts[0])
        return n, n
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    raise ValueError("size must be WIDTH or WIDTHxHEIGHT")


class ImageViewer:
    def __init__(
        self,
        image_path: Path,
        window_size: tuple[int, int] = (1000, 700),
        rows: int | None = None,
        cols: int | None = None,
        cell_size: tuple[int, int] | None = None,
        show_grid: bool | None = None,
        show_variants: bool = False,
    ):
        pygame.init()

        self.image_path = Path(image_path)
        self.window_size = window_size
        self.screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        pygame.display.set_caption(f"Image Viewer - {self.image_path.name}")

        try:
            self.original_image = pygame.image.load(str(self.image_path))
            self.image_size = self.original_image.get_size()
        except pygame.error as e:
            print(f"Error loading image: {e}")
            sys.exit(1)

        self.zoom_level = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        self.scroll_speed = 30

        # Calculate initial grid rows and cols
        if cell_size is not None:
            cw, ch = max(1, cell_size[0]), max(1, cell_size[1])
            self.grid_cols = max(1, self.image_size[0] // cw)
            self.grid_rows = max(1, self.image_size[1] // ch)
            self.cell_w_input_text = str(cw)
            self.cell_h_input_text = str(ch)
            auto_show_grid = True
        elif rows is not None or cols is not None:
            self.grid_rows = max(1, rows if rows is not None else 1)
            self.grid_cols = max(1, cols if cols is not None else 1)
            self.cell_w_input_text = str(max(1, self.image_size[0] // self.grid_cols))
            self.cell_h_input_text = str(max(1, self.image_size[1] // self.grid_rows))
            auto_show_grid = True
        else:
            self.grid_rows = 1
            self.grid_cols = 1
            self.cell_w_input_text = str(self.image_size[0])
            self.cell_h_input_text = str(self.image_size[1])
            auto_show_grid = False

        self.rows_input_text = str(self.grid_rows)
        self.cols_input_text = str(self.grid_cols)

        self.show_grid_overlay = auto_show_grid if show_grid is None else show_grid
        self.show_variant_ids = show_variants
        if self.show_variant_ids:
            self.show_grid_overlay = True

        self.focused_input: str | None = None  # "rows", "cols", "cell_w", "cell_h"
        self.hover_cell: tuple[int, int] | None = None
        self.show_controls = True

        self.font_main = FONTS.get_font(14)
        self.font_bold = FONTS.get_bold_font(14)
        self.font_small = FONTS.get_small_font()

        def _token(name: str, fallback: tuple) -> tuple:
            return getattr(COLORS, name, fallback)

        self.colors = {
            "bg": _token("bg", (30, 32, 36)),
            "panel": _token("panel", (40, 42, 46)),
            "border": _token("border", (60, 62, 65)),
            "text": _token("text", (230, 230, 230)),
            "text_dim": _token("text_muted", (140, 140, 140)),
            "accent": _token("accent", (80, 120, 200)),
            # functional overlay colour: stays high-contrast red by design
            "grid": (255, 0, 0),
            "input_bg": _token("panel_alt", (50, 52, 56)),
            "button": _token("accent_hover", (60, 80, 120)),
            "button_hover": _token("danger_hover", (80, 100, 140)),
            "hover_cell": (255, 230, 0),
        }

        self.running = True
        self.clock = pygame.time.Clock()

        self.update_display_image()

    @property
    def rows_input_focused(self) -> bool:
        return self.focused_input == "rows"

    @property
    def cols_input_focused(self) -> bool:
        return self.focused_input == "cols"

    def update_display_image(self):
        if self.zoom_level != 1.0:
            new_size = (
                int(self.image_size[0] * self.zoom_level),
                int(self.image_size[1] * self.zoom_level),
            )
            self.display_image = pygame.transform.smoothscale(
                self.original_image, new_size
            )
        else:
            self.display_image = self.original_image

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.VIDEORESIZE:
                self.window_size = (event.w, event.h)
                self.screen = pygame.display.set_mode(
                    self.window_size, pygame.RESIZABLE
                )

            elif event.type == pygame.KEYDOWN:
                if self.focused_input:
                    self.handle_input_keydown(event)
                else:
                    self.handle_general_keydown(event)

            elif event.type == pygame.MOUSEWHEEL:
                keys = pygame.key.get_pressed()
                if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
                    old_zoom = self.zoom_level
                    self.zoom_level *= 1.1 if event.y > 0 else 0.9
                    self.zoom_level = max(0.1, min(self.zoom_level, 10.0))
                    if old_zoom != self.zoom_level:
                        self.update_display_image()
                else:
                    self.scroll_y -= event.y * self.scroll_speed
                    self.clamp_scroll()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_mouse_click(event.pos)

    def handle_general_keydown(self, event):
        if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
            self.running = False
        elif event.key == pygame.K_h:
            self.show_controls = not self.show_controls
        elif event.key == pygame.K_g:
            self.show_grid_overlay = not self.show_grid_overlay
        elif event.key == pygame.K_v:
            self.show_variant_ids = not self.show_variant_ids
            if self.show_variant_ids:
                self.show_grid_overlay = True
        elif event.key == pygame.K_r:
            self.zoom_level = 1.0
            self.scroll_x = 0
            self.scroll_y = 0
            self.update_display_image()
        elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
            self.zoom_level *= 1.2
            self.zoom_level = min(self.zoom_level, 10.0)
            self.update_display_image()
        elif event.key == pygame.K_MINUS:
            self.zoom_level *= 0.8
            self.zoom_level = max(self.zoom_level, 0.1)
            self.update_display_image()

    def handle_input_keydown(self, event):
        inputs = ["rows", "cols", "cell_w", "cell_h"]
        if event.key == pygame.K_ESCAPE:
            self.focused_input = None
        elif event.key == pygame.K_RETURN:
            if self.focused_input in ("rows", "cols"):
                self.apply_grid()
            else:
                self.apply_cell()
            self.focused_input = None
        elif event.key == pygame.K_TAB:
            if self.focused_input in inputs:
                idx = (inputs.index(self.focused_input) + 1) % len(inputs)
                self.focused_input = inputs[idx]
            else:
                self.focused_input = "rows"
        elif event.key == pygame.K_BACKSPACE:
            if self.focused_input == "rows":
                self.rows_input_text = self.rows_input_text[:-1]
            elif self.focused_input == "cols":
                self.cols_input_text = self.cols_input_text[:-1]
            elif self.focused_input == "cell_w":
                self.cell_w_input_text = self.cell_w_input_text[:-1]
            elif self.focused_input == "cell_h":
                self.cell_h_input_text = self.cell_h_input_text[:-1]
        elif event.unicode and event.unicode.isdigit():
            if self.focused_input == "rows" and len(self.rows_input_text) < 4:
                self.rows_input_text += event.unicode
            elif self.focused_input == "cols" and len(self.cols_input_text) < 4:
                self.cols_input_text += event.unicode
            elif self.focused_input == "cell_w" and len(self.cell_w_input_text) < 5:
                self.cell_w_input_text += event.unicode
            elif self.focused_input == "cell_h" and len(self.cell_h_input_text) < 5:
                self.cell_h_input_text += event.unicode

    def apply_grid(self):
        try:
            rows = int(self.rows_input_text) if self.rows_input_text else 1
            cols = int(self.cols_input_text) if self.cols_input_text else 1
            self.grid_rows = max(1, min(rows, 1000))
            self.grid_cols = max(1, min(cols, 1000))
            self.rows_input_text = str(self.grid_rows)
            self.cols_input_text = str(self.grid_cols)
            self.cell_w_input_text = str(max(1, self.image_size[0] // self.grid_cols))
            self.cell_h_input_text = str(max(1, self.image_size[1] // self.grid_rows))
            self.show_grid_overlay = True
        except ValueError:
            self.rows_input_text = str(self.grid_rows)
            self.cols_input_text = str(self.grid_cols)

    def apply_cell(self):
        try:
            cw = int(self.cell_w_input_text) if self.cell_w_input_text else self.image_size[0]
            ch = int(self.cell_h_input_text) if self.cell_h_input_text else self.image_size[1]
            cw = max(1, min(cw, self.image_size[0]))
            ch = max(1, min(ch, self.image_size[1]))
            self.cell_w_input_text = str(cw)
            self.cell_h_input_text = str(ch)
            self.grid_cols = max(1, self.image_size[0] // cw)
            self.grid_rows = max(1, self.image_size[1] // ch)
            self.rows_input_text = str(self.grid_rows)
            self.cols_input_text = str(self.grid_cols)
            self.show_grid_overlay = True
        except ValueError:
            self.cell_w_input_text = str(max(1, self.image_size[0] // self.grid_cols))
            self.cell_h_input_text = str(max(1, self.image_size[1] // self.grid_rows))

    def handle_mouse_click(self, pos):
        if hasattr(self, "rows_input_rect") and self.rows_input_rect.collidepoint(pos):
            self.focused_input = "rows"
        elif hasattr(self, "cols_input_rect") and self.cols_input_rect.collidepoint(pos):
            self.focused_input = "cols"
        elif hasattr(self, "cell_w_input_rect") and self.cell_w_input_rect.collidepoint(pos):
            self.focused_input = "cell_w"
        elif hasattr(self, "cell_h_input_rect") and self.cell_h_input_rect.collidepoint(pos):
            self.focused_input = "cell_h"
        elif hasattr(self, "apply_grid_button_rect") and self.apply_grid_button_rect.collidepoint(pos):
            self.apply_grid()
        elif hasattr(self, "apply_cell_button_rect") and self.apply_cell_button_rect.collidepoint(pos):
            self.apply_cell()
        elif hasattr(self, "toggle_grid_button_rect") and self.toggle_grid_button_rect.collidepoint(pos):
            self.show_grid_overlay = not self.show_grid_overlay
        elif hasattr(self, "toggle_variants_button_rect") and self.toggle_variants_button_rect.collidepoint(pos):
            self.show_variant_ids = not self.show_variant_ids
            if self.show_variant_ids:
                self.show_grid_overlay = True
        else:
            self.focused_input = None

    def clamp_scroll(self):
        display_size = self.display_image.get_size()
        max_scroll_x = max(0, display_size[0] - self.window_size[0])
        max_scroll_y = max(0, display_size[1] - self.window_size[1] + 100)

        self.scroll_x = max(0, min(self.scroll_x, max_scroll_x))
        self.scroll_y = max(0, min(self.scroll_y, max_scroll_y))

    def draw(self):
        self.screen.fill(self.colors["bg"])

        image_rect = self.display_image.get_rect()
        image_rect.topleft = (-self.scroll_x, -self.scroll_y)
        self.screen.blit(self.display_image, image_rect)

        # Update hover state
        panel_height = 100 if self.show_controls else 0
        mouse_pos = pygame.mouse.get_pos()
        self.hover_cell = None
        if (
            self.show_grid_overlay
            and image_rect.collidepoint(mouse_pos)
            and mouse_pos[1] < self.window_size[1] - panel_height
        ):
            rel_x = mouse_pos[0] - image_rect.left
            rel_y = mouse_pos[1] - image_rect.top
            cell_w_disp = self.display_image.get_width() / self.grid_cols
            cell_h_disp = self.display_image.get_height() / self.grid_rows
            hc = int(rel_x / cell_w_disp)
            hr = int(rel_y / cell_h_disp)
            if 0 <= hc < self.grid_cols and 0 <= hr < self.grid_rows:
                self.hover_cell = (hc, hr)

        if self.show_grid_overlay and (self.grid_rows > 0 and self.grid_cols > 0):
            self.draw_grid_overlay(image_rect)

        if self.show_controls:
            self.draw_controls()

        pygame.display.flip()

    def draw_grid_overlay(self, image_rect):
        cell_width = self.display_image.get_width() / self.grid_cols
        cell_height = self.display_image.get_height() / self.grid_rows

        # Grid lines
        for i in range(1, self.grid_cols):
            x = image_rect.left + int(i * cell_width)
            if 0 <= x < self.window_size[0]:
                pygame.draw.line(
                    self.screen,
                    self.colors["grid"],
                    (x, max(0, image_rect.top)),
                    (x, min(self.window_size[1], image_rect.bottom)),
                    1,
                )

        for i in range(1, self.grid_rows):
            y = image_rect.top + int(i * cell_height)
            if 0 <= y < self.window_size[1]:
                pygame.draw.line(
                    self.screen,
                    self.colors["grid"],
                    (max(0, image_rect.left), y),
                    (min(self.window_size[0], image_rect.right), y),
                    1,
                )

        # Hover cell highlight
        if self.hover_cell is not None:
            hc, hr = self.hover_cell
            hx = image_rect.left + int(hc * cell_width)
            hy = image_rect.top + int(hr * cell_height)
            hw = int((hc + 1) * cell_width) - int(hc * cell_width)
            hh = int((hr + 1) * cell_height) - int(hr * cell_height)
            hover_rect = pygame.Rect(hx, hy, hw, hh)
            pygame.draw.rect(self.screen, self.colors["hover_cell"], hover_rect, 2)

        # Variant IDs overlay
        if self.show_variant_ids and (cell_width >= 16 and cell_height >= 14):
            panel_height = 100 if self.show_controls else 0
            visible_top = max(0, image_rect.top)
            visible_bottom = min(self.window_size[1] - panel_height, image_rect.bottom)
            visible_left = max(0, image_rect.left)
            visible_right = min(self.window_size[0], image_rect.right)

            if visible_bottom > visible_top and visible_right > visible_left:
                min_col = max(0, int((visible_left - image_rect.left) / cell_width))
                max_col = min(self.grid_cols, int((visible_right - image_rect.left) / cell_width) + 1)
                min_row = max(0, int((visible_top - image_rect.top) / cell_height))
                max_row = min(self.grid_rows, int((visible_bottom - image_rect.top) / cell_height) + 1)

                font = self.font_small if (cell_width < 36 or cell_height < 30) else self.font_main
                for r in range(min_row, max_row):
                    for c in range(min_col, max_col):
                        variant_id = r * self.grid_cols + c
                        cx = image_rect.left + int(c * cell_width)
                        cy = image_rect.top + int(r * cell_height)
                        cw = int((c + 1) * cell_width) - int(c * cell_width)
                        ch = int((r + 1) * cell_height) - int(r * cell_height)

                        txt_surf = font.render(str(variant_id), True, (255, 255, 255))
                        tw, th = txt_surf.get_size()
                        if tw <= cw and th <= ch:
                            bg_rect = pygame.Rect(cx + 2, cy + 2, tw + 4, th + 2)
                            badge_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
                            badge_surf.fill((0, 0, 0, 190))
                            self.screen.blit(badge_surf, bg_rect.topleft)
                            self.screen.blit(txt_surf, (cx + 4, cy + 3))

    def _draw_input_box(self, rect: pygame.Rect, text: str, is_focused: bool):
        border_color = self.colors["accent"] if is_focused else self.colors["border"]
        pygame.draw.rect(self.screen, border_color, rect, border_radius=4)
        pygame.draw.rect(self.screen, self.colors["input_bg"], rect.inflate(-2, -2), border_radius=4)
        display_text = text
        if is_focused and (pygame.time.get_ticks() // 500) % 2:
            display_text += "|"
        surf = self.font_main.render(display_text, True, self.colors["text"])
        self.screen.blit(surf, (rect.x + 5, rect.y + 3))

    def _draw_button(self, rect: pygame.Rect, text: str, active: bool = False) -> None:
        mouse_pos = pygame.mouse.get_pos()
        if rect.collidepoint(mouse_pos):
            color = self.colors["button_hover"]
        elif active:
            color = self.colors["accent"]
        else:
            color = self.colors["button"]
        pygame.draw.rect(self.screen, color, rect, border_radius=4)
        label = self.font_main.render(text, True, self.colors["text"])
        text_rect = label.get_rect(center=rect.center)
        self.screen.blit(label, text_rect)

    def draw_controls(self):
        panel_height = 100
        panel_rect = pygame.Rect(
            0, self.window_size[1] - panel_height, self.window_size[0], panel_height
        )

        panel_surface = pygame.Surface(
            (panel_rect.width, panel_rect.height), pygame.SRCALPHA
        )
        panel_surface.fill((*self.colors["panel"], 235))
        self.screen.blit(panel_surface, panel_rect)

        pygame.draw.line(
            self.screen,
            self.colors["border"],
            (0, panel_rect.top),
            (self.window_size[0], panel_rect.top),
            2,
        )

        # Row 1: Image & hover info
        y_pos = panel_rect.top + 8
        x_pos = 12

        info_text = f"{self.image_path.name} | {self.image_size[0]}×{self.image_size[1]} px | Zoom: {self.zoom_level:.1f}x"
        if self.hover_cell is not None and self.show_grid_overlay:
            hc, hr = self.hover_cell
            hv = hr * self.grid_cols + hc
            info_text += f" | Cell: ({hc}, {hr}) | Variant: #{hv}"
        info_surf = self.font_main.render(info_text, True, self.colors["text"])
        self.screen.blit(info_surf, (x_pos, y_pos))

        # Row 2: Grid and Cell Sizing Controls
        y_pos = panel_rect.top + 35
        x_pos = 12

        # Grid inputs
        grid_lbl = self.font_main.render("Grid:", True, self.colors["text"])
        self.screen.blit(grid_lbl, (x_pos, y_pos + 4))
        x_pos += 40

        self.rows_input_rect = pygame.Rect(x_pos, y_pos, 46, 24)
        self._draw_input_box(self.rows_input_rect, self.rows_input_text, self.focused_input == "rows")
        x_pos += 52

        mul_lbl = self.font_main.render("×", True, self.colors["text"])
        self.screen.blit(mul_lbl, (x_pos, y_pos + 4))
        x_pos += 16

        self.cols_input_rect = pygame.Rect(x_pos, y_pos, 46, 24)
        self._draw_input_box(self.cols_input_rect, self.cols_input_text, self.focused_input == "cols")
        x_pos += 52

        self.apply_grid_button_rect = pygame.Rect(x_pos, y_pos, 52, 24)
        self._draw_button(self.apply_grid_button_rect, "Apply")
        x_pos += 68

        # Cell sizing inputs
        cell_lbl = self.font_main.render("Cell:", True, self.colors["text"])
        self.screen.blit(cell_lbl, (x_pos, y_pos + 4))
        x_pos += 38

        self.cell_w_input_rect = pygame.Rect(x_pos, y_pos, 46, 24)
        self._draw_input_box(self.cell_w_input_rect, self.cell_w_input_text, self.focused_input == "cell_w")
        x_pos += 52

        mul_lbl2 = self.font_main.render("×", True, self.colors["text"])
        self.screen.blit(mul_lbl2, (x_pos, y_pos + 4))
        x_pos += 16

        self.cell_h_input_rect = pygame.Rect(x_pos, y_pos, 46, 24)
        self._draw_input_box(self.cell_h_input_rect, self.cell_h_input_text, self.focused_input == "cell_h")
        x_pos += 52

        self.apply_cell_button_rect = pygame.Rect(x_pos, y_pos, 52, 24)
        self._draw_button(self.apply_cell_button_rect, "Apply")
        x_pos += 68

        # Toggle buttons
        self.toggle_grid_button_rect = pygame.Rect(x_pos, y_pos, 90, 24)
        grid_status = "Grid: ON" if self.show_grid_overlay else "Grid: OFF"
        self._draw_button(self.toggle_grid_button_rect, grid_status, active=self.show_grid_overlay)
        x_pos += 98

        self.toggle_variants_button_rect = pygame.Rect(x_pos, y_pos, 110, 24)
        var_status = "Variants: ON" if self.show_variant_ids else "Variants: OFF"
        self._draw_button(self.toggle_variants_button_rect, var_status, active=self.show_variant_ids)

        # Row 3: Help / shortcut info
        y_pos = panel_rect.top + 70
        help_text = (
            "Controls: Arrows/Wheel=Scroll | Ctrl+Wheel=Zoom | R=Reset | "
            "G=Toggle Grid | V=Toggle Variants | H=Hide Controls | Q/ESC=Quit"
        )
        help_surf = self.font_small.render(help_text, True, self.colors["text_dim"])
        self.screen.blit(help_surf, (12, y_pos))

    def run(self):
        while self.running:
            self.handle_events()

            keys = pygame.key.get_pressed()
            if not self.focused_input:
                if keys[pygame.K_LEFT]:
                    self.scroll_x -= self.scroll_speed
                if keys[pygame.K_RIGHT]:
                    self.scroll_x += self.scroll_speed
                if keys[pygame.K_UP]:
                    self.scroll_y -= self.scroll_speed
                if keys[pygame.K_DOWN]:
                    self.scroll_y += self.scroll_speed

            self.clamp_scroll()
            self.draw()
            self.clock.tick(60)

        pygame.quit()


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Standalone Image & Tileset Viewer with Grid Sizing and Variant IDs"
    )
    parser.add_argument("image_path", help="Path to image file")
    parser.add_argument(
        "--cell",
        "--tile-size",
        dest="cell_size",
        default=None,
        help="Tile/cell size in px (e.g. 32 or 16x32) to compute grid",
    )
    parser.add_argument("--rows", type=int, default=None, help="Number of grid rows")
    parser.add_argument("--cols", type=int, default=None, help="Number of grid columns")
    parser.add_argument(
        "--variants",
        action="store_true",
        help="Display tile variant IDs (#0, #1, ...) on grid cells",
    )
    parser.add_argument(
        "--no-grid",
        action="store_true",
        help="Hide grid overlay initially",
    )
    parser.add_argument(
        "--size",
        default="1000x700",
        help="Window size as WIDTHxHEIGHT (default: 1000x700)",
    )

    args = parser.parse_args(argv)

    image_path = Path(args.image_path)
    if not image_path.exists():
        print(f"Error: Image file not found: {image_path}", file=sys.stderr)
        return 1

    cell_size = None
    if args.cell_size:
        try:
            cell_size = parse_size(args.cell_size)
        except ValueError as e:
            print(f"Error: invalid --cell / --tile-size: {e}", file=sys.stderr)
            return 2

    try:
        window_size = parse_size(args.size)
    except ValueError:
        window_size = (1000, 700)

    show_grid = False if args.no_grid else None

    load_standalone_theme()
    viewer = ImageViewer(
        image_path,
        window_size=window_size,
        rows=args.rows,
        cols=args.cols,
        cell_size=cell_size,
        show_grid=show_grid,
        show_variants=args.variants,
    )
    viewer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
