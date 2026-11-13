"""Reusable right-click popup menu.

Reuses :class:`MenuAction` / :class:`MenuSeparator` from the menubar so the
same item definitions can drive both dropdown and context menus.

Long labels are ellipsized instead of widening the menu without limit, and
menus taller than the screen scroll with the mouse wheel.
"""

from __future__ import annotations

import pygame
from pygame import Rect, Surface

from utils.icon_manager import icon_manager

from .menubar import MenuAction, MenuSeparator
from .theme import COLORS, FONTS, fit_text


class ContextMenu:
    """Flat popup menu. Show with :meth:`popup`, dismiss on outside click or Esc."""

    ITEM_H = 26
    SEP_H = 12
    MIN_W = 160
    MAX_W = 280
    SCROLLBAR_W = 4

    def __init__(self):
        self.items: list = []
        self.rect = Rect(0, 0, 0, 0)
        self.item_rects: list[tuple[Rect, object]] = []
        self.is_open = False
        self.scroll_offset = 0
        self.max_scroll = 0

    @property
    def font(self):
        return FONTS.get_medium_font()

    def popup(self, items: list, pos: tuple[int, int], screen_size=None) -> None:
        self.items = list(items)
        width = self.MIN_W
        for action in self.items:
            if isinstance(action, MenuSeparator):
                continue
            label_w = self.font.render(action.label, True, COLORS.text).get_width()
            if action.shortcut:
                sh_w = FONTS.get_small_font().render(
                    action.shortcut, True, COLORS.text_dim
                ).get_width()
                width = max(width, label_w + sh_w + 44)
            else:
                width = max(width, label_w + 34)
        width = min(width, self.MAX_W)

        total_h = sum(
            self.SEP_H if isinstance(a, MenuSeparator) else self.ITEM_H
            for a in self.items
        )
        x, y = pos
        view_h = total_h
        if screen_size:
            x = min(x, screen_size[0] - width - 4)
            view_h = min(total_h, screen_size[1] - 16)
            y = min(y, screen_size[1] - view_h - 8)
            y = max(4, y)
        self.rect = Rect(max(0, x), max(0, y), width, view_h + 8)

        # virtual rects covering the full content; scrolling shifts them
        # under the clipped viewport
        self.item_rects = []
        iy = self.rect.y + 4
        for action in self.items:
            h = self.SEP_H if isinstance(action, MenuSeparator) else self.ITEM_H
            self.item_rects.append((Rect(self.rect.x + 2, iy, self.rect.width - 4, h), action))
            iy += h

        self.max_scroll = max(0, total_h - view_h)
        self.scroll_offset = 0
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def _scroll(self, delta: int) -> None:
        self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset + delta))

    def _visible_item_at(self, pos: tuple[int, int]):
        """Item under the mouse, ignoring the part clipped out of view."""
        for item_rect, action in self.item_rects:
            moved = item_rect.move(0, -self.scroll_offset)
            if not self.rect.contains(moved.clamp(self.rect)):
                continue
            if moved.collidepoint(pos):
                return action
        return None

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.is_open:
            return False
        mouse_pos = getattr(event, "pos", None) or pygame.mouse.get_pos()

        if event.type == pygame.MOUSEWHEEL:
            self._scroll(-int(event.y) * self.ITEM_H * 3)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            activate = event.button == 1
            action = self._visible_item_at(mouse_pos)
            self.close()
            if (
                activate
                and isinstance(action, MenuAction)
                and (action.is_enabled is None or action.is_enabled())
            ):
                action.callback()
            return True

        if event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True
            return True

        return True

    def draw(self, screen: Surface) -> None:
        if not self.is_open:
            return

        shadow_rect = self.rect.copy()
        shadow_rect.inflate_ip(4, 4)
        shadow = Surface((shadow_rect.w, shadow_rect.h), pygame.SRCALPHA)
        shadow.fill((*COLORS.bg, 160))
        screen.blit(shadow, shadow_rect.topleft)

        pygame.draw.rect(screen, COLORS.panel, self.rect)
        pygame.draw.rect(screen, COLORS.border, self.rect, 1)

        mouse_pos = pygame.mouse.get_pos()
        shortcut_font = FONTS.get_small_font()
        old_clip = screen.get_clip()
        screen.set_clip(self.rect)
        try:
            for item_rect, action in self.item_rects:
                moved = item_rect.move(0, -self.scroll_offset)
                if moved.bottom <= self.rect.y or moved.top >= self.rect.bottom:
                    continue

                if isinstance(action, MenuSeparator):
                    mid_y = moved.centery
                    pygame.draw.line(
                        screen,
                        COLORS.border_soft,
                        (moved.x + 8, mid_y),
                        (moved.right - 8, mid_y),
                        1,
                    )
                    continue

                disabled = action.is_enabled is not None and not action.is_enabled()
                hovered = (
                    moved.collidepoint(mouse_pos)
                    and self.rect.contains(moved.clamp(self.rect))
                    and not disabled
                )
                if hovered:
                    pygame.draw.rect(screen, COLORS.accent, moved, border_radius=3)
                    color = COLORS.text_on_accent
                    shortcut_color = COLORS.text_on_accent
                elif disabled:
                    color = COLORS.text_muted
                    shortcut_color = COLORS.text_muted
                else:
                    color = COLORS.text
                    shortcut_color = COLORS.text_dim

                label_x = moved.x + 10
                if action.is_checked and action.is_checked():
                    check_icon = icon_manager.get_icon("check", 14, COLORS.success)
                    if check_icon:
                        screen.blit(check_icon, (moved.x + 5, moved.y + 6))
                    label_x = moved.x + 24

                label_max_w = self.rect.right - self.SCROLLBAR_W - 6 - label_x
                if action.shortcut:
                    sh_w = shortcut_font.render(action.shortcut, True, color).get_width()
                    label_max_w -= sh_w + 10
                label_surf = self.font.render(
                    fit_text(self.font, action.label, label_max_w), True, color
                )
                screen.blit(label_surf, (label_x, moved.y + 5))

                if action.shortcut:
                    sh_surf = shortcut_font.render(action.shortcut, True, shortcut_color)
                    screen.blit(
                        sh_surf,
                        (moved.right - sh_surf.get_width() - 10, moved.y + 7),
                    )
        finally:
            screen.set_clip(old_clip)

        if self.max_scroll > 0:
            track = Rect(
                self.rect.right - self.SCROLLBAR_W - 2,
                self.rect.y + 3,
                self.SCROLLBAR_W,
                self.rect.h - 6,
            )
            pygame.draw.rect(screen, COLORS.border_soft, track, border_radius=2)
            content_h = track.h + self.max_scroll
            thumb_h = max(18, int(track.h * track.h / content_h))
            progress = self.scroll_offset / self.max_scroll
            thumb_y = track.y + int((track.h - thumb_h) * progress)
            pygame.draw.rect(
                screen,
                COLORS.text_muted,
                Rect(track.x, thumb_y, track.w, thumb_h),
                border_radius=2,
            )
