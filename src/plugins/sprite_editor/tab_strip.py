"""Tab strip for the sprite editor: one tab per open document.

Follows the visual pattern of :class:`widgets.ui.sidebar_container` —
header background, accent underline on the active tab, truncated labels —
with per-tab close buttons and a trailing "+" for a new blank canvas.
"""

from __future__ import annotations

from collections.abc import Callable

import pygame
from pygame import Rect, Surface

from widgets.ui.draw_utils import truncate_text
from widgets.ui.theme import COLORS, FONTS, SHAPE

TAB_H = 26
NEW_BTN_W = 26
MIN_TAB_W = 76
MAX_TAB_W = 190
CLOSE_HIT = 18


class TabStrip:
    """Flat row of document tabs. Owned by the editor; switching, closing
    and creating go through the callbacks."""

    def __init__(
        self,
        rect: Rect,
        on_switch: Callable[[int], None],
        on_close: Callable[[int], None],
        on_new: Callable[[], None],
    ):
        self.rect = Rect(rect)
        self.on_switch = on_switch
        self.on_close = on_close
        self.on_new = on_new
        # [{"label": str, "dirty": bool}]
        self._tabs: list[dict] = []
        self._active_idx = 0
        self._tab_rects: list[Rect] = []
        self._close_rects: list[Rect] = []
        self._new_btn_rect = Rect(0, 0, 0, 0)

    def set_tabs(self, tabs: list[dict], active_idx: int) -> None:
        self._tabs = list(tabs)
        self._active_idx = max(0, min(active_idx, max(0, len(tabs) - 1)))
        self._layout()

    def resize(self, rect: Rect) -> None:
        self.rect = Rect(rect)
        self._layout()

    def _layout(self) -> None:
        n = len(self._tabs)
        bar = Rect(self.rect.x, self.rect.y, self.rect.w - NEW_BTN_W - 4, TAB_H)
        self._new_btn_rect = Rect(
            self.rect.right - NEW_BTN_W - 2, self.rect.y + 2, NEW_BTN_W - 4, TAB_H - 4
        )
        self._tab_rects = []
        self._close_rects = []
        if n == 0:
            return
        tab_w = min(MAX_TAB_W, max(MIN_TAB_W, bar.w // n))
        # compress to fit the bar when many tabs are open
        if tab_w * n > bar.w:
            tab_w = max(56, bar.w // n)
        x = bar.x
        for _ in self._tabs:
            r = Rect(x, self.rect.y + 2, tab_w, TAB_H - 4)
            self._tab_rects.append(r)
            self._close_rects.append(
                Rect(r.right - CLOSE_HIT - 2, r.y + 3, CLOSE_HIT, CLOSE_HIT)
            )
            x += tab_w

    def _tab_at(self, pos: tuple[int, int]) -> int | None:
        for i, r in enumerate(self._tab_rects):
            if r.collidepoint(pos):
                return i
        return None

    def _close_at(self, pos: tuple[int, int]) -> int | None:
        for i, r in enumerate(self._close_rects):
            if r.collidepoint(pos):
                return i
        return None

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self._tabs:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2):
            pos = getattr(event, "pos", pygame.mouse.get_pos())
            idx = self._close_at(pos)
            if idx is not None:
                self.on_close(idx)
                return True
            idx = self._tab_at(pos)
            if idx is not None:
                if event.button == 2:  # middle click closes
                    self.on_close(idx)
                elif idx != self._active_idx:
                    self.on_switch(idx)
                return True
            if self._new_btn_rect.collidepoint(pos):
                self.on_new()
                return True
        return False

    def draw(self, screen: Surface) -> None:
        bar = Rect(self.rect.x, self.rect.y, self.rect.w, TAB_H)
        pygame.draw.rect(screen, COLORS.header, bar)
        pygame.draw.line(
            screen, COLORS.border_soft, bar.bottomleft, bar.bottomright, 1
        )

        font = FONTS.get_small_font()
        mouse_pos = pygame.mouse.get_pos()
        for i, tab in enumerate(self._tabs):
            r = self._tab_rects[i]
            active = i == self._active_idx
            hovered = r.collidepoint(mouse_pos) and not active
            if active:
                bg = COLORS.selected
            elif hovered:
                bg = COLORS.hover
            else:
                bg = COLORS.header
            pygame.draw.rect(screen, bg, r, border_radius=3)
            if active:
                pygame.draw.rect(screen, COLORS.accent, Rect(r.x, r.bottom - 2, r.w, 2))
            elif not hovered:
                pygame.draw.line(screen, COLORS.border, r.bottomleft, r.bottomright, 1)

            # label with drawn dirty dot, leaving room for the close hit area
            dirty = bool(tab.get("dirty"))
            label = tab.get("label", "")
            label_x = r.x + 8 + (8 if dirty else 0)
            max_w = self._close_rects[i].x - label_x - 4
            display, _ = truncate_text(label, font, max_w)
            color = COLORS.text_on_selected if active else COLORS.text
            surf = font.render(display, True, color)
            screen.blit(surf, (label_x, r.centery - surf.get_height() // 2))
            if dirty:
                pygame.draw.circle(
                    screen,
                    COLORS.accent if active else COLORS.accent,
                    (r.x + 6, r.centery),
                    3,
                )

            # close ✕
            cr = self._close_rects[i]
            close_hover = cr.collidepoint(mouse_pos)
            x_color = COLORS.text if close_hover else COLORS.text_muted
            pygame.draw.line(
                screen, x_color, (cr.x + 5, cr.y + 5), (cr.right - 5, cr.bottom - 5), 2
            )
            pygame.draw.line(
                screen, x_color, (cr.right - 5, cr.y + 5), (cr.x + 5, cr.bottom - 5), 2
            )

        # "+" new-tab button
        hover = self._new_btn_rect.collidepoint(mouse_pos)
        bg = COLORS.hover if hover else COLORS.header
        pygame.draw.rect(screen, bg, self._new_btn_rect, border_radius=SHAPE.radius_sm)
        pygame.draw.rect(
            screen, COLORS.border_soft, self._new_btn_rect, 1, border_radius=SHAPE.radius_sm
        )
        plus = font.render("+", True, COLORS.text)
        screen.blit(plus, plus.get_rect(center=self._new_btn_rect.center))
