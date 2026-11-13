"""Minimal inline file navigator.

A lightweight directory browser for quick single-file picks inside editor
viewports: parent/child navigation, type-to-filter and session recents.
Complements :class:`widgets.filemanager.FileManager` for fast picks where
the full dialog is overkill.

The panel stays open after a selection (rapid multi-pick), can be dragged
by its header, resized from the corner grip and closed with the ✕ button,
Esc, or an outside click. Hovering an image row shows a floating preview
card, clipped to the parent bounds so it never leaks outside them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pygame
from pygame import Rect, Surface

from utils.icon_manager import icon_manager
from utils.natural_sort import natural_key

from .theme import COLORS, FONTS, fit_text


class MiniFileNavigator:
    """Inline dir browser. Modal by contract: ``handle_event`` consumes all
    events while open, closing on Esc, the ✕ button or an outside click."""

    ITEM_H = 26
    PADDING = 10
    SCROLLBAR_W = 4
    CLOSE_BTN = 18
    MAX_RECENTS = 8
    MIN_W = 280
    MIN_H = 220
    MAX_W = 640
    MAX_H = 680
    GRIP = 16
    PREVIEW_SIZE = 160
    PREVIEW_DELAY_MS = 250
    MAX_PREVIEW_MB = 50

    def __init__(
        self,
        rect: Rect,
        initial_dir: Path,
        allowed_exts: list[str],
        on_select: Callable[[Path], None],
        on_cancel: Callable[[], None],
        *,
        data_root: Path | None = None,
        recents: list[Path] | None = None,
        title: str = "Open Image",
        bounds: Rect | None = None,
        current: Path | None = None,
    ):
        self.rect = Rect(rect)
        self.current_dir = Path(initial_dir)
        self.allowed_exts = [e.lower() for e in allowed_exts]
        self.on_select_callback = on_select
        self.on_cancel_callback = on_cancel
        self.data_root = Path(data_root) if data_root else None
        # shared with the owner (mutated in place so recents survive
        # close/reopen cycles)
        self.recents = recents if recents is not None else []
        self.title = title
        self.bounds = Rect(bounds) if bounds else None
        # file the owner currently has loaded — marked in the listing
        self.current = Path(current) if current else None
        self.filter_text = ""
        self.scroll_offset = 0
        self.max_scroll = 0
        self._selection = 0
        self._rows: list[tuple[str, Path | None, str]] = []
        self._list_rect = Rect(0, 0, 0, 0)
        self._filter_rect = Rect(0, 0, 0, 0)
        self._drag_pos: tuple[int, int] | None = None
        self._resize_start: tuple[int, int, int, int] | None = None
        self._hover_index: int | None = None
        self._hover_since = 0
        self._preview_images: dict[Path, Surface | None] = {}
        self._preview_scaled: dict[Path, Surface | None] = {}
        self._refresh()

    # ------------------------------------------------------------------
    # listing
    # ------------------------------------------------------------------

    @property
    def font(self):
        return FONTS.get_font(13)

    def _refresh(self) -> None:
        self._layout()  # ensure list_rect is valid for scroll/hit-testing
        needle = self.filter_text.strip().lower()
        rows: list[tuple[str, Path | None, str]] = []

        recents = []
        for path in self.recents:
            if path.parent == self.current_dir:
                continue  # already visible in the dir listing
            if needle and needle not in path.name.lower():
                continue
            recents.append(path)
        if recents:
            rows.append(("recents_header", None, "Recent"))
            for path in recents:
                rows.append(("recent", path, path.name))

        if self.current_dir.parent != self.current_dir:
            rows.append(("parent", self.current_dir.parent, ".."))

        try:
            entries = sorted(
                self.current_dir.iterdir(),
                key=lambda p: (not p.is_dir(), natural_key(p.name)),
            )
        except (PermissionError, OSError):
            entries = []
        for entry in entries:
            is_dir = entry.is_dir()
            if needle and needle not in entry.name.lower():
                continue
            if not is_dir and entry.suffix.lower() not in self.allowed_exts:
                continue
            rows.append(("dir" if is_dir else "file", entry, entry.name))

        self._rows = rows
        if needle:
            # when filtering, land on the first match — not the ".." row
            self._selection = self._first_selectable()
        else:
            self._selection = min(self._selection, max(0, len(rows) - 1))
        self._update_scroll()

    def _first_selectable(self) -> int:
        for i, (kind, _, _) in enumerate(self._rows):
            if kind not in ("recents_header", "parent"):
                return i
        return min(self._selection, max(0, len(self._rows) - 1))

    def _update_scroll(self) -> None:
        content_h = max(0, len(self._rows) * self.ITEM_H)
        view_h = max(0, self._list_rect.h)
        self.max_scroll = max(0, content_h - view_h)
        self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset))

    def _row_rect(self, index: int) -> Rect:
        return Rect(
            self._list_rect.x,
            self._list_rect.y + index * self.ITEM_H - self.scroll_offset,
            self._list_rect.w - 2,
            self.ITEM_H,
        )

    def _visible_index_at(self, pos: tuple[int, int]) -> int | None:
        if not self._list_rect.collidepoint(pos):
            return None
        idx = (pos[1] - self._list_rect.y + self.scroll_offset) // self.ITEM_H
        if 0 <= idx < len(self._rows):
            return int(idx)
        return None

    def _visible(self, index: int) -> bool:
        rect = self._row_rect(index)
        return rect.bottom > self._list_rect.y and rect.top < self._list_rect.bottom

    # ------------------------------------------------------------------
    # geometry / bounds
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        pad = self.PADDING
        x = self.rect.x + pad
        w = self.rect.w - pad * 2
        y = self.rect.y + pad

        self._close_btn_rect = Rect(
            self.rect.right - pad - self.CLOSE_BTN, self.rect.y + pad - 2,
            self.CLOSE_BTN, self.CLOSE_BTN,
        )
        count_font = FONTS.get_small_font()
        self._count_rect = Rect(
            x, y,
            self._close_btn_rect.left - 6 - x,
            count_font.get_height(),
        )
        y += 20

        self._path_rect = Rect(x, y, w, 18)
        y += 20

        self._filter_rect = Rect(x, y, w, 24)
        y += 28
        self._header_rect = Rect(
            self.rect.x, self.rect.y, self.rect.w, self._filter_rect.y - self.rect.y
        )

        footer_h = FONTS.get_small_font().get_height() + 12
        self._footer_y = self.rect.bottom - pad - footer_h
        self._list_rect = Rect(x, y, w, self.rect.bottom - pad - footer_h - y)
        self._grip_rect = Rect(
            self.rect.right - self.GRIP - 2,
            self.rect.bottom - self.GRIP - 2,
            self.GRIP - 2,
            self.GRIP - 2,
        )
        self._update_scroll()
        self._clamp_to_bounds()

    def _clamp_to_bounds(self) -> None:
        """Keep the whole panel inside the parent bounds (never leaked)."""
        b = self.bounds
        if b is None or b.w <= 0 or b.h <= 0:
            return
        w = min(self.rect.w, b.w - 8)
        h = min(self.rect.h, b.h - 8)
        if (w, h) != self.rect.size:
            self.rect.size = (max(120, int(w)), max(120, int(h)))
        x = min(max(self.rect.x, b.x + 2), max(b.x + 2, b.right - self.rect.w - 2))
        y = min(max(self.rect.y, b.y + 2), max(b.y + 2, b.bottom - self.rect.h - 2))
        self.rect.topleft = (x, y)

    def _display_path(self) -> str:
        if self.data_root:
            try:
                return str(self.current_dir.relative_to(self.data_root)) or "."
            except ValueError:
                pass
        return str(self.current_dir)

    def _file_info(self, kind: str, path: Path | None) -> str:
        if kind == "file" and path is not None:
            try:
                size_kb = path.stat().st_size / 1024
                return f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            except OSError:
                return ""
        if kind == "recent" and path is not None:
            return path.parent.name or str(path.parent)
        return ""

    # ------------------------------------------------------------------
    # floating preview (hover)
    # ------------------------------------------------------------------

    def _preview_for(self, path: Path) -> Surface | None:
        if path in self._preview_scaled:
            return self._preview_scaled[path]
        if path not in self._preview_images:
            surf: Surface | None = None
            try:
                if path.stat().st_size <= self.MAX_PREVIEW_MB * 1024 * 1024:
                    surf = pygame.image.load(str(path)).convert_alpha()
            except Exception:
                surf = None
            self._preview_images[path] = surf
            if len(self._preview_images) > 24:
                self._preview_images.clear()
                self._preview_images[path] = surf
        img = self._preview_images[path]
        if img is None:
            self._preview_scaled[path] = None
            return None
        w, h = img.get_size()
        scale = min(self.PREVIEW_SIZE / w, self.PREVIEW_SIZE / h, 1.0)
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        try:
            scaled = pygame.transform.smoothscale(img, size)
        except ValueError:
            scaled = pygame.transform.scale(img, size)
        self._preview_scaled[path] = scaled
        if len(self._preview_scaled) > 24:
            self._preview_scaled.clear()
            self._preview_scaled[path] = scaled
        return scaled

    def _hover_preview_row(self, mouse_pos: tuple[int, int]) -> tuple[int, Path] | None:
        """Row eligible for a floating preview, after the hover delay."""
        if self._drag_pos is not None or self._resize_start is not None:
            return None
        idx = self._visible_index_at(mouse_pos)
        if idx != self._hover_index:
            self._hover_index = idx
            self._hover_since = pygame.time.get_ticks()
            return None
        if idx is None or pygame.time.get_ticks() - self._hover_since < self.PREVIEW_DELAY_MS:
            return None
        kind, path, _ = self._rows[idx]
        if kind not in ("file", "recent") or path is None:
            return None
        if path.suffix.lower() not in self.allowed_exts:
            return None
        return idx, path

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _navigate(self, target: Path) -> None:
        self.current_dir = target
        self.filter_text = ""
        self.scroll_offset = 0
        self._selection = 0
        self._refresh()

    def _add_recent(self, path: Path) -> None:
        if path in self.recents:
            self.recents.remove(path)
        self.recents.insert(0, path)
        del self.recents[self.MAX_RECENTS:]

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        kind, path, _ = self._rows[index]
        if kind == "parent":
            self._navigate(path)
        elif kind == "dir":
            self._navigate(path)
        elif kind in ("file", "recent") and path is not None:
            # stays open: the panel is meant for picking several files
            # in a row
            self._add_recent(path)
            self.on_select_callback(path)

    def close(self) -> None:
        self.on_cancel_callback()

    def geometry(self) -> dict:
        """Size/position snapshot for persisting across open/close cycles."""
        return {
            "x": int(self.rect.x),
            "y": int(self.rect.y),
            "w": int(self.rect.w),
            "h": int(self.rect.h),
            "dir": str(self.current_dir),
        }

    def restore_geometry(self, geo: dict) -> None:
        """Apply a previously saved snapshot (validated + bounds-clamped)."""
        try:
            self.rect = Rect(
                int(geo["x"]), int(geo["y"]), int(geo["w"]), int(geo["h"])
            )
        except (KeyError, TypeError, ValueError):
            return
        self.rect.w = max(self.MIN_W, min(self.rect.w, self.MAX_W))
        self.rect.h = max(self.MIN_H, min(self.rect.h, self.MAX_H))
        self._layout()

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def _drag_to(self, pos: tuple[int, int]) -> None:
        self.rect.topleft = (
            int(pos[0] - self._drag_pos[0]),
            int(pos[1] - self._drag_pos[1]),
        )
        self._clamp_to_bounds()

    def _resize_to(self, pos: tuple[int, int]) -> None:
        sx, sy, sw, sh = self._resize_start
        new_w = min(max(sw + pos[0] - sx, self.MIN_W), self.MAX_W)
        new_h = min(max(sh + pos[1] - sy, self.MIN_H), self.MAX_H)
        self.rect.size = (int(new_w), int(new_h))
        self._clamp_to_bounds()

    def handle_event(self, event: pygame.event.Event) -> bool:
        mouse_pos = getattr(event, "pos", None) or pygame.mouse.get_pos()

        if self._drag_pos is not None:
            if event.type == pygame.MOUSEMOTION:
                self._drag_to(mouse_pos)
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._drag_pos = None
                return True

        if self._resize_start is not None:
            if event.type == pygame.MOUSEMOTION:
                self._resize_to(mouse_pos)
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._resize_start = None
                return True

        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = max(
                0, min(self.max_scroll, self.scroll_offset - int(event.y) * self.ITEM_H * 3)
            )
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._close_btn_rect.collidepoint(mouse_pos):
                self.close()
                return True
            if self._grip_rect.collidepoint(mouse_pos):
                self._resize_start = (
                    mouse_pos[0], mouse_pos[1], self.rect.w, self.rect.h
                )
                return True
            if self._header_rect.collidepoint(mouse_pos):
                self._drag_pos = (mouse_pos[0] - self.rect.x, mouse_pos[1] - self.rect.y)
                return True
            if not self.rect.collidepoint(mouse_pos):
                self.close()
                return True
            idx = self._visible_index_at(mouse_pos)
            if idx is not None:
                self._selection = idx
                self._activate(idx)
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True
            if event.key == pygame.K_UP:
                self._move_selection(-1)
                return True
            if event.key == pygame.K_DOWN:
                self._move_selection(1)
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._activate(self._selection)
                return True
            if event.key == pygame.K_BACKSPACE:
                if self.filter_text:
                    self.filter_text = self.filter_text[:-1]
                    self._selection = 0
                    self._refresh()
                else:
                    parent = self.current_dir.parent
                    if parent != self.current_dir:
                        self._navigate(parent)
                return True
            return True

        if event.type == pygame.TEXTINPUT:
            text = getattr(event, "text", "")
            if text and text.isprintable():
                self.filter_text += text
                self._selection = 0
                self._refresh()
            return True

        return True

    def _move_selection(self, delta: int) -> None:
        if not self._rows:
            return
        self._selection = (self._selection + delta) % len(self._rows)
        # section headers are not actionable targets
        for _ in range(len(self._rows)):
            if self._rows[self._selection][0] != "recents_header":
                break
            self._selection = (self._selection + delta) % len(self._rows)
        # keep the selection in view (capped to avoid oscillation when a
        # single row is taller than the viewport)
        for _ in range(len(self._rows)):
            if self._visible(self._selection) or self.max_scroll <= 0:
                break
            if self._row_rect(self._selection).top < self._list_rect.y:
                self.scroll_offset -= self.ITEM_H
            else:
                self.scroll_offset += self.ITEM_H
            self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset))
            if self.scroll_offset in (0, self.max_scroll):
                break

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------

    def draw(self, screen: Surface) -> None:
        self._layout()

        # shadow
        shadow_rect = self.rect.copy()
        shadow_rect.inflate_ip(6, 6)
        shadow = Surface((shadow_rect.w, shadow_rect.h), pygame.SRCALPHA)
        shadow.fill((*COLORS.bg, 150))
        screen.blit(shadow, shadow_rect.topleft)

        pygame.draw.rect(screen, COLORS.panel, self.rect, border_radius=6)
        pygame.draw.rect(screen, COLORS.border, self.rect, 1, border_radius=6)

        pad = self.PADDING
        mouse_pos = pygame.mouse.get_pos()

        # header: title left, entry count + close button right
        title_font = FONTS.get_bold_font(13)
        title_surf = title_font.render(self.title, True, COLORS.text)
        screen.blit(title_surf, (self.rect.x + pad, self.rect.y + pad - 1))

        n_dirs = sum(1 for k, _, _ in self._rows if k == "dir")
        n_files = sum(1 for k, _, _ in self._rows if k in ("file", "recent"))
        count = f"{n_dirs} dir · {n_files} img"
        count_font = FONTS.get_small_font()
        count_surf = count_font.render(
            fit_text(count_font, count, self._count_rect.w), True, COLORS.text_dim
        )
        screen.blit(
            count_surf,
            (self._count_rect.right - count_surf.get_width(), self._count_rect.y + 1),
        )

        # close button
        close_hover = self._close_btn_rect.collidepoint(mouse_pos)
        if close_hover:
            pygame.draw.rect(
                screen, COLORS.hover, self._close_btn_rect, border_radius=3
            )
        close_icon = icon_manager.get_icon(
            "close", 10, COLORS.text if close_hover else COLORS.text_dim
        )
        if close_icon:
            screen.blit(
                close_icon,
                close_icon.get_rect(center=self._close_btn_rect.center),
            )

        path_font = FONTS.get_small_font()
        path_surf = path_font.render(
            fit_text(path_font, self._display_path(), self._path_rect.w), True,
            COLORS.text_muted,
        )
        screen.blit(path_surf, (self._path_rect.x, self._path_rect.y + 2))

        # filter box
        pygame.draw.rect(
            screen, COLORS.bg, self._filter_rect, border_radius=3
        )
        pygame.draw.rect(
            screen, COLORS.border_soft, self._filter_rect, 1, border_radius=3
        )
        ftext_font = FONTS.get_font(12)
        filter_x = self._filter_rect.x + 8
        ft_surf = None
        if self.filter_text:
            ft_surf = ftext_font.render(
                fit_text(ftext_font, self.filter_text, self._filter_rect.w - 16),
                True, COLORS.text,
            )
            screen.blit(ft_surf, (filter_x, self._filter_rect.y + 5))
        else:
            ph = ftext_font.render("Filter… (type to narrow)", True, COLORS.text_muted)
            screen.blit(ph, (filter_x, self._filter_rect.y + 5))
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            caret_x = (
                filter_x + ft_surf.get_width()
                if ft_surf is not None
                else filter_x
            )
            pygame.draw.line(
                screen,
                COLORS.text,
                (caret_x, self._filter_rect.y + 5),
                (caret_x, self._filter_rect.bottom - 5),
                1,
            )

        # rows
        old_clip = screen.get_clip()
        screen.set_clip(self._list_rect)
        try:
            row_font = self.font
            dim_font = FONTS.get_small_font()
            for index, (kind, path, label) in enumerate(self._rows):
                row = self._row_rect(index)
                if row.bottom <= self._list_rect.y or row.top >= self._list_rect.bottom:
                    continue

                if kind == "recents_header":
                    screen.blit(
                        dim_font.render("RECENT", True, COLORS.text_muted),
                        (row.x + 2, row.y + 7),
                    )
                    pygame.draw.line(
                        screen,
                        COLORS.border_soft,
                        (row.x, row.y + self.ITEM_H - 4),
                        (row.right, row.y + self.ITEM_H - 4),
                        1,
                    )
                    continue

                selected = index == self._selection
                hovered = row.collidepoint(mouse_pos)
                if selected:
                    pygame.draw.rect(
                        screen, COLORS.hover, row, border_radius=3
                    )
                    pygame.draw.rect(
                        screen, COLORS.accent, row, 1, border_radius=3
                    )
                elif hovered:
                    pygame.draw.rect(screen, COLORS.hover, row, border_radius=3)

                is_current = (
                    path is not None
                    and self.current is not None
                    and path == self.current
                )
                if is_current:
                    # accent dot marks the file the owner has loaded
                    pygame.draw.circle(
                        screen, COLORS.accent, (row.x + 6, row.y + 13), 3
                    )
                tx = row.x + 8 + (9 if is_current else 0)
                if kind == "parent":
                    screen.blit(
                        row_font.render(label, True, COLORS.text_dim), (tx, row.y + 5)
                    )
                    continue

                if kind == "dir":
                    icon = icon_manager.get_icon("folder", 14, COLORS.text_dim)
                    if icon:
                        screen.blit(icon, (tx, row.y + 6))
                    tx += 20
                    name_color = COLORS.text
                elif kind == "recent":
                    icon = icon_manager.get_icon("load", 13, COLORS.text_muted)
                    if icon:
                        screen.blit(icon, (tx, row.y + 6))
                    tx += 19
                    name_color = COLORS.text_dim
                else:
                    name_color = COLORS.text

                # right-aligned info; reserve its width so long names
                # never overlap it
                info = self._file_info(kind, path)
                info_surf = None
                if info:
                    info_surf = dim_font.render(
                        fit_text(dim_font, info, row.w // 3), True, COLORS.text_muted
                    )
                right_pad = 10
                if info_surf is not None:
                    right_pad += info_surf.get_width() + 8
                if self.max_scroll > 0:
                    right_pad += self.SCROLLBAR_W + 4

                screen.blit(
                    row_font.render(
                        fit_text(row_font, label, row.right - right_pad - tx),
                        True, name_color,
                    ),
                    (tx, row.y + 5),
                )
                if info_surf is not None:
                    screen.blit(
                        info_surf,
                        (row.right - info_surf.get_width() - 10, row.y + 7),
                    )
        finally:
            screen.set_clip(old_clip)

        if self.max_scroll > 0:
            track = Rect(
                self._list_rect.right - self.SCROLLBAR_W - 2,
                self._list_rect.y,
                self.SCROLLBAR_W,
                self._list_rect.h,
            )
            pygame.draw.rect(screen, COLORS.border_soft, track, border_radius=2)
            content_h = track.h + self.max_scroll
            thumb_h = max(18, int(track.h * track.h / content_h))
            progress = self.scroll_offset / self.max_scroll if self.max_scroll else 0
            thumb_y = track.y + int((track.h - thumb_h) * progress)
            pygame.draw.rect(
                screen,
                COLORS.text_muted,
                Rect(track.x, thumb_y, track.w, thumb_h),
                border_radius=2,
            )

        # footer hint, separated from the list by a divider
        pygame.draw.line(
            screen,
            COLORS.border_soft,
            (self.rect.x + pad, self._footer_y),
            (self.rect.right - pad, self._footer_y),
            1,
        )
        hint = "Arrows navigate · Enter open · Backspace up · Esc close"
        hint_surf = FONTS.get_small_font().render(hint, True, COLORS.text_muted)
        hint_x = self.rect.x + pad + 18  # leave room for the corner grip
        screen.blit(hint_surf, (hint_x, self._footer_y + 6))

        # resize grip (bottom-right corner)
        grip_hover = self._grip_rect.collidepoint(mouse_pos)
        grip_color = COLORS.text_dim if grip_hover else COLORS.border
        for off in (4, 8, 12):
            pygame.draw.line(
                screen,
                grip_color,
                (self._grip_rect.right - off, self._grip_rect.bottom),
                (self._grip_rect.right, self._grip_rect.bottom - off),
                2,
            )

        # floating preview card, clipped to the parent bounds so it can
        # never leak outside them
        hover = self._hover_preview_row(mouse_pos)
        if hover is not None:
            self._draw_preview(screen, hover[1])

    def _draw_preview(self, screen: Surface, path: Path) -> None:
        bounds = self.bounds or Rect(0, 0, *pygame.display.get_surface().get_size())
        card_w = self.PREVIEW_SIZE + 40
        card_h = self.PREVIEW_SIZE + 44

        mx, my = pygame.mouse.get_pos()
        x = mx + 18
        if x + card_w > bounds.right - 4:
            x = mx - card_w - 18
        x = min(max(x, bounds.x + 2), bounds.right - card_w - 2)
        y = min(max(my - card_h // 2, bounds.y + 2), bounds.bottom - card_h - 2)
        card = Rect(int(x), int(y), card_w, card_h)

        old_clip = screen.get_clip()
        screen.set_clip(bounds)
        try:
            shadow = Surface((card.w + 6, card.h + 6), pygame.SRCALPHA)
            shadow.fill((*COLORS.bg, 150))
            screen.blit(shadow, (card.x - 3, card.y - 3))

            pygame.draw.rect(screen, COLORS.panel, card, border_radius=6)
            pygame.draw.rect(screen, COLORS.border, card, 1, border_radius=6)

            img = self._preview_for(path)
            img_area = Rect(card.x + 4, card.y + 4, card.w - 8, self.PREVIEW_SIZE)
            if img is not None:
                screen.blit(img, img.get_rect(center=img_area.center))
                orig = self._preview_images.get(path)
                dim = orig.get_size() if orig is not None else img.get_size()
                dim_font = FONTS.get_small_font()
                caption = fit_text(dim_font, f"{path.name}  ·  {dim[0]}×{dim[1]}px", card.w - 16)
                cap_surf = dim_font.render(caption, True, COLORS.text_dim)
                screen.blit(cap_surf, cap_surf.get_rect(midtop=(card.centerx, img_area.bottom + 6)))
            else:
                msg = FONTS.get_small_font().render("No preview", True, COLORS.text_muted)
                screen.blit(msg, msg.get_rect(center=img_area.center))
        finally:
            screen.set_clip(old_clip)
