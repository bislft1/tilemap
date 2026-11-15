"""
Shared Shape & Polygon Canvas Widget.

Provides an interactive 2D canvas with pan, zoom, grid snapping, and
visual editing for both geometric primitives (rectangle, circle, capsule)
and arbitrary 2D polygons (vertex dragging, edge insertion, body translation,
convexity validation).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Literal

import pygame
from pygame import Rect, Surface

from utils.font_manager import FontWeight, font_manager
from utils.shortcuts import is_cmd_or_ctrl
from widgets.ui.theme import COLORS

ShapeType = Literal["rectangle", "circle", "capsule", "polygon"]

_HANDLE_RADIUS = 6
_HANDLE_HOVER_RADIUS = 8
_EDGE_INSERT_THRESHOLD = 8


def is_convex_polygon(vertices: list[tuple[float, float]]) -> bool:
    """Signed cross-product winding check for polygon convexity."""
    n = len(vertices)
    if n < 3:
        return False
    if n == 3:
        return True

    sign = 0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        x3, y3 = vertices[(i + 2) % n]
        cross = (x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2)
        if abs(cross) < 1e-7:
            continue
        if sign == 0:
            sign = 1 if cross > 0 else -1
        elif (cross > 0) != (sign > 0):
            return False
    return True


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray casting algorithm to test point inclusion in polygon."""
    n = len(polygon)
    if n < 3:
        return False
    x, y = point
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
    return inside


def point_to_segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, tuple[float, float]]:
    """Distance from point p to segment ab, returning (dist, closest_point)."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-7:
        return math.hypot(px - ax, py - ay), a

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    closest = (ax + t * dx, ay + t * dy)
    dist = math.hypot(px - closest[0], py - closest[1])
    return dist, closest


class ShapeCanvas:
    """Interactive shape and polygon authoring canvas."""

    def __init__(self, rect: Rect):
        self.rect = rect
        self.surface: Surface | None = None

        # Viewport transform
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0
        self.zoom: float = 3.0
        self.min_zoom: float = 0.25
        self.max_zoom: float = 32.0

        # Panning state
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_start_offset = (0.0, 0.0)
        self._space_held = False

        # Grid settings
        self.show_grid = True
        self.snap_to_grid = False
        self.grid_size = 8
        self.show_probe = False

        # Shape Data
        self.shape_type: ShapeType = "rectangle"

        # Primitive definitions (sprite-local coords)
        self.rect_x: float = 0.0
        self.rect_y: float = 0.0
        self.rect_w: float = 32.0
        self.rect_h: float = 32.0

        self.circle_x: float = 16.0
        self.circle_y: float = 16.0
        self.circle_radius: float = 16.0

        self.capsule_x: float = 16.0
        self.capsule_y: float = 8.0
        self.capsule_radius: float = 8.0
        self.capsule_height: float = 16.0

        # Polygon definitions
        self.polygon_vertices: list[tuple[float, float]] = []
        self.drawing_polygon: list[tuple[float, float]] = []

        # Interaction / Dragging state
        self.hover_handle: str | None = None
        self.dragging_handle: str | None = None

        self.hover_vertex_idx: int | None = None
        self.selected_vertex_idx: int | None = None
        self.dragging_vertex_idx: int | None = None

        self.hover_edge: tuple[int, tuple[float, float]] | None = None  # (index, closest_point)
        self._dragging_body = False
        self._drag_start_local = (0.0, 0.0)
        self._orig_polygon_vertices: list[tuple[float, float]] = []
        self._orig_shape_offset = (0.0, 0.0)

        # Overlays
        self.hull_rect: tuple[float, float, float, float] | None = None
        self.ghost_shapes: list[dict] = []

        # Callbacks
        self.on_modified: Callable[[], None] | None = None

        self._font = None
        self._font_sm = None

    # -- Coordinate Transformations --------------------------------------

    def local_to_screen(self, local_pos: tuple[float, float]) -> tuple[int, int]:
        sx = round(self.rect.x + self.offset_x + local_pos[0] * self.zoom)
        sy = round(self.rect.y + self.offset_y + local_pos[1] * self.zoom)
        return (sx, sy)

    def screen_to_local(self, screen_pos: tuple[int, int]) -> tuple[float, float]:
        lx = (screen_pos[0] - self.rect.x - self.offset_x) / self.zoom
        ly = (screen_pos[1] - self.rect.y - self.offset_y) / self.zoom
        return (lx, ly)

    def snap_local(self, local_pos: tuple[float, float]) -> tuple[float, float]:
        if not self.snap_to_grid:
            return local_pos
        gs = float(self.grid_size)
        return (round(local_pos[0] / gs) * gs, round(local_pos[1] / gs) * gs)

    # -- Viewport Control ------------------------------------------------

    def set_surface(self, surface: Surface | None, keep_viewport: bool = True) -> None:
        self.surface = surface
        if not keep_viewport:
            self.fit_view()

    def fit_view(self, target_bounds: tuple[float, float, float, float] | None = None, margin: float = 0.8) -> None:
        """Fit view to target bounds or surface bounds."""
        if target_bounds is not None:
            l, t, r, b = target_bounds
            w, h = r - l, b - t
        elif self.surface is not None:
            sw, sh = self.surface.get_size()
            l, t, w, h = 0.0, 0.0, float(sw), float(sh)
        else:
            w, h = 64.0, 64.0
            l, t = 0.0, 0.0

        if w <= 0 or h <= 0 or self.rect.w <= 0 or self.rect.h <= 0:
            self.center_view()
            return

        zoom_x = (self.rect.w / w) * margin
        zoom_y = (self.rect.h / h) * margin
        self.zoom = max(self.min_zoom, min(self.max_zoom, min(zoom_x, zoom_y)))

        cx = l + w / 2.0
        cy = t + h / 2.0
        self.offset_x = self.rect.w / 2.0 - cx * self.zoom
        self.offset_y = self.rect.h / 2.0 - cy * self.zoom

    def center_view(self) -> None:
        sw, sh = self.surface.get_size() if self.surface else (64, 64)
        self.offset_x = (self.rect.w - sw * self.zoom) / 2.0
        self.offset_y = (self.rect.h - sh * self.zoom) / 2.0

    def zoom_at(self, screen_pos: tuple[int, int], factor: float) -> None:
        old_zoom = self.zoom
        new_zoom = max(self.min_zoom, min(self.max_zoom, self.zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-4:
            return

        lx, ly = self.screen_to_local(screen_pos)
        self.zoom = new_zoom
        # Preserve position under mouse
        self.offset_x = screen_pos[0] - self.rect.x - lx * self.zoom
        self.offset_y = screen_pos[1] - self.rect.y - ly * self.zoom

    def resize(self, rect: Rect) -> None:
        self.rect = rect

    # -- Shape Data I/O --------------------------------------------------

    def set_shape_type(self, shape_type: ShapeType) -> None:
        if self.shape_type != shape_type:
            self.shape_type = shape_type
            self.drawing_polygon.clear()
            self._notify_modified()

    def get_shape_data(self) -> dict:
        if self.shape_type == "rectangle":
            return {
                "type": "rectangle",
                "width": round(self.rect_w, 2),
                "height": round(self.rect_h, 2),
                "offset": (round(self.rect_x, 2), round(self.rect_y, 2)),
            }
        if self.shape_type == "circle":
            return {
                "type": "circle",
                "radius": round(self.circle_radius, 2),
                "offset": (round(self.circle_x, 2), round(self.circle_y, 2)),
            }
        if self.shape_type == "capsule":
            return {
                "type": "capsule",
                "radius": round(self.capsule_radius, 2),
                "height": round(self.capsule_height, 2),
                "offset": (round(self.capsule_x, 2), round(self.capsule_y, 2)),
            }
        if self.shape_type == "polygon":
            return {
                "type": "polygon",
                "vertices": [(round(v[0], 2), round(v[1], 2)) for v in self.polygon_vertices],
                "offset": (0.0, 0.0),
            }
        return {}

    def load_shape_data(self, data: dict) -> None:
        if not data:
            return
        stype = data.get("type", "rectangle")
        self.shape_type = stype
        offset = data.get("offset", (0.0, 0.0))

        if stype == "rectangle":
            self.rect_w = float(data.get("width", 32.0))
            self.rect_h = float(data.get("height", 32.0))
            self.rect_x = float(offset[0])
            self.rect_y = float(offset[1])
        elif stype == "circle":
            self.circle_radius = float(data.get("radius", 16.0))
            self.circle_x = float(offset[0])
            self.circle_y = float(offset[1])
        elif stype == "capsule":
            self.capsule_radius = float(data.get("radius", 8.0))
            self.capsule_height = float(data.get("height", 16.0))
            self.capsule_x = float(offset[0])
            self.capsule_y = float(offset[1])
        elif stype == "polygon":
            vs = data.get("vertices", [])
            self.polygon_vertices = [(float(v[0]), float(v[1])) for v in vs]
            self.drawing_polygon.clear()

        self._notify_modified()

    def _notify_modified(self) -> None:
        if self.on_modified is not None:
            self.on_modified()

    # -- Event Handling --------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        mouse = pygame.mouse.get_pos()
        in_bounds = self.rect.collidepoint(mouse)

        # 1. Panning & Viewport Keys
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self._space_held = True
                return True
            if event.key == pygame.K_g:
                self.show_grid = not self.show_grid
                return True
            if event.key == pygame.K_p:
                self.show_probe = not self.show_probe
                return True
            if event.key == pygame.K_r:
                self.fit_view()
                return True

            # Polygon drawing hotkeys
            if self.shape_type == "polygon":
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if len(self.drawing_polygon) >= 3:
                        self.polygon_vertices = list(self.drawing_polygon)
                        self.drawing_polygon.clear()
                        self._notify_modified()
                        return True
                elif event.key == pygame.K_ESCAPE:
                    if self.drawing_polygon:
                        self.drawing_polygon.clear()
                        return True
                elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                    if self.drawing_polygon:
                        self.drawing_polygon.pop()
                        return True
                    if self.selected_vertex_idx is not None and len(self.polygon_vertices) > 3:
                        self.polygon_vertices.pop(self.selected_vertex_idx)
                        self.selected_vertex_idx = None
                        self._notify_modified()
                        return True
                    elif self.selected_vertex_idx is not None and len(self.polygon_vertices) <= 3:
                        self.polygon_vertices.clear()
                        self.selected_vertex_idx = None
                        self._notify_modified()
                        return True

        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_SPACE:
                self._space_held = False
                return True

        # 2. Mouse Wheel Zooming
        if event.type == pygame.MOUSEWHEEL and in_bounds:
            factor = 1.15 if event.y > 0 else (1.0 / 1.15)
            self.zoom_at(mouse, factor)
            return True

        # 3. Middle Mouse or Space+Click Panning
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2 or (event.button == 1 and self._space_held):
                if in_bounds:
                    self._panning = True
                    self._pan_start = mouse
                    self._pan_start_offset = (self.offset_x, self.offset_y)
                    return True

        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2 or (event.button == 1 and self._panning):
                if self._panning:
                    self._panning = False
                    return True

        if event.type == pygame.MOUSEMOTION:
            if self._panning:
                dx = mouse[0] - self._pan_start[0]
                dy = mouse[1] - self._pan_start[1]
                self.offset_x = self._pan_start_offset[0] + dx
                self.offset_y = self._pan_start_offset[1] + dy
                return True

        # If not inside canvas and not actively dragging, don't handle
        if not in_bounds and not self.dragging_handle and not self.dragging_vertex_idx is not None and not self._dragging_body:
            return False

        # Route to shape specific interaction
        if self.shape_type == "polygon":
            return self._handle_polygon_event(event, mouse)
        else:
            return self._handle_primitive_event(event, mouse)

    # -- Primitive Shape Interaction -------------------------------------

    def _handle_primitive_event(self, event: pygame.event.Event, mouse: tuple[int, int]) -> bool:
        local_mouse = self.screen_to_local(mouse)

        if event.type == pygame.MOUSEMOTION:
            if self.dragging_handle:
                self._drag_primitive_handle(local_mouse)
                self._notify_modified()
                return True

            if self._dragging_body:
                dx = local_mouse[0] - self._drag_start_local[0]
                dy = local_mouse[1] - self._drag_start_local[1]
                self._apply_primitive_offset(dx, dy)
                self._notify_modified()
                return True

            # Update hover handle
            self.hover_handle = self._find_primitive_handle_at(mouse)
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            handle = self._find_primitive_handle_at(mouse)
            if handle:
                self.dragging_handle = handle
                return True

            if self._point_in_primitive(local_mouse):
                self._dragging_body = True
                self._drag_start_local = local_mouse
                self._save_primitive_orig()
                return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging_handle or self._dragging_body:
                self.dragging_handle = None
                self._dragging_body = False
                return True

        return False

    def _find_primitive_handle_at(self, screen_pos: tuple[int, int]) -> str | None:
        if self.shape_type == "rectangle":
            handles = {
                "tl": (self.rect_x, self.rect_y),
                "tr": (self.rect_x + self.rect_w, self.rect_y),
                "bl": (self.rect_x, self.rect_y + self.rect_h),
                "br": (self.rect_x + self.rect_w, self.rect_y + self.rect_h),
            }
            for name, pos in handles.items():
                sp = self.local_to_screen(pos)
                if math.hypot(screen_pos[0] - sp[0], screen_pos[1] - sp[1]) <= _HANDLE_HOVER_RADIUS:
                    return name

        elif self.shape_type == "circle":
            sp_center = self.local_to_screen((self.circle_x, self.circle_y))
            if math.hypot(screen_pos[0] - sp_center[0], screen_pos[1] - sp_center[1]) <= _HANDLE_HOVER_RADIUS:
                return "center"
            sp_rad = self.local_to_screen((self.circle_x + self.circle_radius, self.circle_y))
            if math.hypot(screen_pos[0] - sp_rad[0], screen_pos[1] - sp_rad[1]) <= _HANDLE_HOVER_RADIUS:
                return "radius"

        elif self.shape_type == "capsule":
            sp_top = self.local_to_screen((self.capsule_x, self.capsule_y))
            sp_bot = self.local_to_screen((self.capsule_x, self.capsule_y + self.capsule_height))
            if math.hypot(screen_pos[0] - sp_top[0], screen_pos[1] - sp_top[1]) <= _HANDLE_HOVER_RADIUS:
                return "top"
            if math.hypot(screen_pos[0] - sp_bot[0], screen_pos[1] - sp_bot[1]) <= _HANDLE_HOVER_RADIUS:
                return "bottom"
            sp_rad = self.local_to_screen((self.capsule_x + self.capsule_radius, self.capsule_y + self.capsule_height / 2))
            if math.hypot(screen_pos[0] - sp_rad[0], screen_pos[1] - sp_rad[1]) <= _HANDLE_HOVER_RADIUS:
                return "radius"

        return None

    def _drag_primitive_handle(self, local_pos: tuple[float, float]) -> None:
        snapped = self.snap_local(local_pos)
        x, y = snapped

        if self.shape_type == "rectangle":
            h = self.dragging_handle
            rx, ry, rw, rh = self.rect_x, self.rect_y, self.rect_w, self.rect_h
            if h == "tl":
                self.rect_x = min(x, rx + rw - 1)
                self.rect_y = min(y, ry + rh - 1)
                self.rect_w = (rx + rw) - self.rect_x
                self.rect_h = (ry + rh) - self.rect_y
            elif h == "tr":
                self.rect_w = max(1.0, x - rx)
                self.rect_y = min(y, ry + rh - 1)
                self.rect_h = (ry + rh) - self.rect_y
            elif h == "bl":
                self.rect_x = min(x, rx + rw - 1)
                self.rect_w = (rx + rw) - self.rect_x
                self.rect_h = max(1.0, y - ry)
            elif h == "br":
                self.rect_w = max(1.0, x - rx)
                self.rect_h = max(1.0, y - ry)

        elif self.shape_type == "circle":
            if self.dragging_handle == "center":
                self.circle_x, self.circle_y = x, y
            elif self.dragging_handle == "radius":
                self.circle_radius = max(2.0, math.hypot(x - self.circle_x, y - self.circle_y))

        elif self.shape_type == "capsule":
            if self.dragging_handle == "top":
                bot_y = self.capsule_y + self.capsule_height
                self.capsule_x = x
                self.capsule_y = min(y, bot_y - 2)
                self.capsule_height = bot_y - self.capsule_y
            elif self.dragging_handle == "bottom":
                self.capsule_x = x
                self.capsule_height = max(2.0, y - self.capsule_y)
            elif self.dragging_handle == "radius":
                self.capsule_radius = max(2.0, abs(x - self.capsule_x))

    def _point_in_primitive(self, local_pos: tuple[float, float]) -> bool:
        lx, ly = local_pos
        if self.shape_type == "rectangle":
            return self.rect_x <= lx <= self.rect_x + self.rect_w and self.rect_y <= ly <= self.rect_y + self.rect_h
        if self.shape_type == "circle":
            return math.hypot(lx - self.circle_x, ly - self.circle_y) <= self.circle_radius
        if self.shape_type == "capsule":
            cx, cy = self.capsule_x, self.capsule_y
            ch, cr = self.capsule_height, self.capsule_radius
            if cy <= ly <= cy + ch:
                return abs(lx - cx) <= cr
            if ly < cy:
                return math.hypot(lx - cx, ly - cy) <= cr
            return math.hypot(lx - cx, ly - (cy + ch)) <= cr
        return False

    def _save_primitive_orig(self) -> None:
        if self.shape_type == "rectangle":
            self._orig_shape_offset = (self.rect_x, self.rect_y)
        elif self.shape_type == "circle":
            self._orig_shape_offset = (self.circle_x, self.circle_y)
        elif self.shape_type == "capsule":
            self._orig_shape_offset = (self.capsule_x, self.capsule_y)

    def _apply_primitive_offset(self, dx: float, dy: float) -> None:
        ox, oy = self._orig_shape_offset
        nx = ox + dx
        ny = oy + dy
        if self.snap_to_grid:
            gs = float(self.grid_size)
            nx = round(nx / gs) * gs
            ny = round(ny / gs) * gs

        if self.shape_type == "rectangle":
            self.rect_x, self.rect_y = nx, ny
        elif self.shape_type == "circle":
            self.circle_x, self.circle_y = nx, ny
        elif self.shape_type == "capsule":
            self.capsule_x, self.capsule_y = nx, ny

    # -- Polygon Interaction ---------------------------------------------

    def _handle_polygon_event(self, event: pygame.event.Event, mouse: tuple[int, int]) -> bool:
        local_mouse = self.screen_to_local(mouse)
        snapped_mouse = self.snap_local(local_mouse)

        if event.type == pygame.MOUSEMOTION:
            if self.dragging_vertex_idx is not None:
                idx = self.dragging_vertex_idx
                self.polygon_vertices[idx] = snapped_mouse
                self._notify_modified()
                return True

            if self._dragging_body:
                dx = snapped_mouse[0] - self._drag_start_local[0]
                dy = snapped_mouse[1] - self._drag_start_local[1]
                self.polygon_vertices = [
                    (v[0] + dx, v[1] + dy) for v in self._orig_polygon_vertices
                ]
                self._notify_modified()
                return True

            # Update hover state
            self.hover_vertex_idx = self._find_polygon_vertex_at(mouse)
            if self.hover_vertex_idx is None and not self.drawing_polygon:
                self.hover_edge = self._find_polygon_edge_at(mouse)
            else:
                self.hover_edge = None
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                # If we are drawing a new polygon
                if self.drawing_polygon or not self.polygon_vertices:
                    # Check if clicked on first vertex to close
                    if len(self.drawing_polygon) >= 3:
                        first_screen = self.local_to_screen(self.drawing_polygon[0])
                        if math.hypot(mouse[0] - first_screen[0], mouse[1] - first_screen[1]) <= _HANDLE_HOVER_RADIUS:
                            self.polygon_vertices = list(self.drawing_polygon)
                            self.drawing_polygon.clear()
                            self._notify_modified()
                            return True

                    self.drawing_polygon.append(snapped_mouse)
                    return True

                # If existing polygon: check vertex drag
                v_idx = self._find_polygon_vertex_at(mouse)
                if v_idx is not None:
                    self.dragging_vertex_idx = v_idx
                    self.selected_vertex_idx = v_idx
                    return True

                # Check edge split insertion
                edge = self._find_polygon_edge_at(mouse)
                if edge is not None:
                    idx, pt = edge
                    self.polygon_vertices.insert(idx + 1, pt)
                    self.dragging_vertex_idx = idx + 1
                    self.selected_vertex_idx = idx + 1
                    self.hover_edge = None
                    self._notify_modified()
                    return True

                # Check body drag
                if point_in_polygon(local_mouse, self.polygon_vertices):
                    self._dragging_body = True
                    self._drag_start_local = snapped_mouse
                    self._orig_polygon_vertices = list(self.polygon_vertices)
                    self.selected_vertex_idx = None
                    return True

            elif event.button == 3:
                # Right click completes drawing
                if len(self.drawing_polygon) >= 3:
                    self.polygon_vertices = list(self.drawing_polygon)
                    self.drawing_polygon.clear()
                    self._notify_modified()
                    return True
                elif self.drawing_polygon:
                    self.drawing_polygon.clear()
                    return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging_vertex_idx is not None or self._dragging_body:
                self.dragging_vertex_idx = None
                self._dragging_body = False
                return True

        return False

    def _find_polygon_vertex_at(self, screen_pos: tuple[int, int]) -> int | None:
        for idx, v in enumerate(self.polygon_vertices):
            sp = self.local_to_screen(v)
            if math.hypot(screen_pos[0] - sp[0], screen_pos[1] - sp[1]) <= _HANDLE_HOVER_RADIUS:
                return idx
        return None

    def _find_polygon_edge_at(self, screen_pos: tuple[int, int]) -> tuple[int, tuple[float, float]] | None:
        n = len(self.polygon_vertices)
        if n < 3:
            return None
        local_mouse = self.screen_to_local(screen_pos)
        thresh_local = _EDGE_INSERT_THRESHOLD / self.zoom

        best_edge = None
        min_dist = float("inf")
        for i in range(n):
            a = self.polygon_vertices[i]
            b = self.polygon_vertices[(i + 1) % n]
            dist, pt = point_to_segment_distance(local_mouse, a, b)
            if dist <= thresh_local and dist < min_dist:
                min_dist = dist
                best_edge = (i, pt)
        return best_edge

    # -- Rendering -------------------------------------------------------

    def draw(self, screen: Surface) -> None:
        self._ensure_fonts()

        # Clip rendering to widget rect
        clip_prev = screen.get_clip()
        screen.set_clip(self.rect)

        # Background
        pygame.draw.rect(screen, (22, 24, 28), self.rect)

        # Grid
        if self.show_grid:
            self._draw_grid(screen)

        # Base Surface / Sprite cel
        if self.surface is not None:
            sw, sh = self.surface.get_size()
            topleft = self.local_to_screen((0.0, 0.0))
            scaled_w = round(sw * self.zoom)
            scaled_h = round(sh * self.zoom)
            if scaled_w > 0 and scaled_h > 0:
                scaled = pygame.transform.scale(self.surface, (scaled_w, scaled_h))
                screen.blit(scaled, topleft)
                pygame.draw.rect(screen, (60, 65, 75), Rect(topleft[0], topleft[1], scaled_w, scaled_h), 1)

        # Ghost / Inactive Shapes
        self._draw_ghost_shapes(screen)

        # Clip Union Hull
        if self.hull_rect is not None:
            self._draw_hull(screen, self.hull_rect)

        # Active Shape
        self._draw_active_shape(screen)

        # Overlays / Probe
        self._draw_status_overlay(screen)

        # Border
        pygame.draw.rect(screen, COLORS.border, self.rect, 1)

        screen.set_clip(clip_prev)

    def _ensure_fonts(self) -> None:
        if self._font is None:
            self._font = font_manager.get_font("Arial", 12, FontWeight.REGULAR)
        if self._font_sm is None:
            self._font_sm = font_manager.get_font("Arial", 10, FontWeight.REGULAR)

    def _draw_grid(self, screen: Surface) -> None:
        grid_step = self.grid_size * self.zoom
        if grid_step < 6:
            return

        start_x = self.rect.x + (self.offset_x % grid_step)
        start_y = self.rect.y + (self.offset_y % grid_step)

        grid_color = (36, 40, 48)
        x = start_x
        while x < self.rect.right:
            pygame.draw.line(screen, grid_color, (x, self.rect.y), (x, self.rect.bottom))
            x += grid_step

        y = start_y
        while y < self.rect.bottom:
            pygame.draw.line(screen, grid_color, (self.rect.x, y), (self.rect.right, y))
            y += grid_step

        # Origin crosshair
        origin = self.local_to_screen((0.0, 0.0))
        if self.rect.collidepoint(origin):
            pygame.draw.line(screen, (70, 80, 100), (origin[0] - 8, origin[1]), (origin[0] + 8, origin[1]), 2)
            pygame.draw.line(screen, (70, 80, 100), (origin[0], origin[1] - 8), (origin[0], origin[1] + 8), 2)

    def _draw_active_shape(self, screen: Surface) -> None:
        fill_color = (80, 180, 255, 60)
        stroke_color = (110, 200, 255)
        convex_ok = True

        if self.shape_type == "rectangle":
            tl = self.local_to_screen((self.rect_x, self.rect_y))
            w = round(self.rect_w * self.zoom)
            h = round(self.rect_h * self.zoom)
            r = Rect(tl[0], tl[1], w, h)

            overlay = Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
            overlay.fill(fill_color)
            screen.blit(overlay, r)
            pygame.draw.rect(screen, stroke_color, r, 2)

            # Handles
            for name, pos in [
                ("tl", (self.rect_x, self.rect_y)),
                ("tr", (self.rect_x + self.rect_w, self.rect_y)),
                ("bl", (self.rect_x, self.rect_y + self.rect_h)),
                ("br", (self.rect_x + self.rect_w, self.rect_y + self.rect_h)),
            ]:
                sp = self.local_to_screen(pos)
                is_hover = (self.hover_handle == name)
                color = (255, 220, 80) if is_hover else (255, 255, 255)
                radius = _HANDLE_HOVER_RADIUS if is_hover else _HANDLE_RADIUS
                pygame.draw.circle(screen, color, sp, radius)
                pygame.draw.circle(screen, (20, 20, 20), sp, radius, 1)

        elif self.shape_type == "circle":
            center = self.local_to_screen((self.circle_x, self.circle_y))
            rad = round(self.circle_radius * self.zoom)
            if rad > 0:
                s = Surface((rad * 2, rad * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, fill_color, (rad, rad), rad)
                screen.blit(s, (center[0] - rad, center[1] - rad))
                pygame.draw.circle(screen, stroke_color, center, rad, 2)

            # Handles
            pygame.draw.circle(screen, (255, 220, 80) if self.hover_handle == "center" else (255, 255, 255), center, _HANDLE_RADIUS)
            pygame.draw.circle(screen, (20, 20, 20), center, _HANDLE_RADIUS, 1)

            rad_pt = self.local_to_screen((self.circle_x + self.circle_radius, self.circle_y))
            pygame.draw.circle(screen, (255, 220, 80) if self.hover_handle == "radius" else (255, 255, 255), rad_pt, _HANDLE_RADIUS)
            pygame.draw.circle(screen, (20, 20, 20), rad_pt, _HANDLE_RADIUS, 1)

        elif self.shape_type == "capsule":
            cx, cy = self.capsule_x, self.capsule_y
            ch, cr = self.capsule_height, self.capsule_radius
            top_sp = self.local_to_screen((cx, cy))
            bot_sp = self.local_to_screen((cx, cy + ch))
            rad_px = round(cr * self.zoom)

            if rad_px > 0:
                # Capsule body rect
                body_r = Rect(top_sp[0] - rad_px, top_sp[1], rad_px * 2, max(1, bot_sp[1] - top_sp[1]))
                body_surf = Surface((body_r.w, body_r.h), pygame.SRCALPHA)
                body_surf.fill(fill_color)
                screen.blit(body_surf, body_r)

                cap_surf = Surface((rad_px * 2, rad_px * 2), pygame.SRCALPHA)
                pygame.draw.circle(cap_surf, fill_color, (rad_px, rad_px), rad_px)
                screen.blit(cap_surf, (top_sp[0] - rad_px, top_sp[1] - rad_px))
                screen.blit(cap_surf, (bot_sp[0] - rad_px, bot_sp[1] - rad_px))

                # Strokes
                pygame.draw.line(screen, stroke_color, (top_sp[0] - rad_px, top_sp[1]), (bot_sp[0] - rad_px, bot_sp[1]), 2)
                pygame.draw.line(screen, stroke_color, (top_sp[0] + rad_px, top_sp[1]), (bot_sp[0] + rad_px, bot_sp[1]), 2)
                pygame.draw.circle(screen, stroke_color, top_sp, rad_px, 2)
                pygame.draw.circle(screen, stroke_color, bot_sp, rad_px, 2)

            # Handles
            pygame.draw.circle(screen, (255, 220, 80) if self.hover_handle == "top" else (255, 255, 255), top_sp, _HANDLE_RADIUS)
            pygame.draw.circle(screen, (20, 20, 20), top_sp, _HANDLE_RADIUS, 1)
            pygame.draw.circle(screen, (255, 220, 80) if self.hover_handle == "bottom" else (255, 255, 255), bot_sp, _HANDLE_RADIUS)
            pygame.draw.circle(screen, (20, 20, 20), bot_sp, _HANDLE_RADIUS, 1)

        elif self.shape_type == "polygon":
            # 1. Existing Polygon
            if len(self.polygon_vertices) >= 3:
                convex_ok = is_convex_polygon(self.polygon_vertices)
                poly_stroke = stroke_color if convex_ok else (240, 100, 90)
                poly_fill = fill_color if convex_ok else (240, 100, 90, 60)

                screen_pts = [self.local_to_screen(v) for v in self.polygon_vertices]

                min_x = min(p[0] for p in screen_pts)
                min_y = min(p[1] for p in screen_pts)
                max_x = max(p[0] for p in screen_pts)
                max_y = max(p[1] for p in screen_pts)
                pw, ph = max(1, max_x - min_x + 2), max(1, max_y - min_y + 2)

                poly_surf = Surface((pw, ph), pygame.SRCALPHA)
                rel_pts = [(p[0] - min_x, p[1] - min_y) for p in screen_pts]
                pygame.draw.polygon(poly_surf, poly_fill, rel_pts)
                screen.blit(poly_surf, (min_x, min_y))

                pygame.draw.polygon(screen, poly_stroke, screen_pts, 2)

                # Vertices
                for idx, pt in enumerate(screen_pts):
                    is_hover = (self.hover_vertex_idx == idx)
                    is_sel = (self.selected_vertex_idx == idx)
                    v_col = (255, 220, 80) if is_hover else ((110, 220, 140) if is_sel else (255, 255, 255))
                    v_rad = _HANDLE_HOVER_RADIUS if (is_hover or is_sel) else _HANDLE_RADIUS
                    pygame.draw.circle(screen, v_col, pt, v_rad)
                    pygame.draw.circle(screen, (20, 20, 20), pt, v_rad, 1)

                # Edge split insertion indicator
                if self.hover_edge is not None:
                    _, insert_pt = self.hover_edge
                    sp_insert = self.local_to_screen(insert_pt)
                    pygame.draw.circle(screen, (100, 255, 180), sp_insert, 5)
                    pygame.draw.circle(screen, (20, 20, 20), sp_insert, 5, 1)

            # 2. Polygon in progress
            if self.drawing_polygon:
                draw_pts = [self.local_to_screen(v) for v in self.drawing_polygon]
                for i in range(len(draw_pts) - 1):
                    pygame.draw.line(screen, (255, 200, 80), draw_pts[i], draw_pts[i + 1], 2)

                mouse = pygame.mouse.get_pos()
                snapped_mouse_sp = self.local_to_screen(self.snap_local(self.screen_to_local(mouse)))
                pygame.draw.line(screen, (200, 200, 200), draw_pts[-1], snapped_mouse_sp, 1)

                for idx, pt in enumerate(draw_pts):
                    col = (80, 255, 120) if idx == 0 else (255, 200, 80)
                    pygame.draw.circle(screen, col, pt, 5)
                    pygame.draw.circle(screen, (20, 20, 20), pt, 5, 1)

    def _draw_ghost_shapes(self, screen: Surface) -> None:
        ghost_color = (140, 150, 170, 40)
        ghost_stroke = (120, 130, 150)
        for g in self.ghost_shapes:
            stype = g.get("type", "rectangle")
            ox, oy = g.get("offset", (0.0, 0.0))
            if stype == "rectangle":
                tl = self.local_to_screen((ox, oy))
                w = round(g.get("width", 32) * self.zoom)
                h = round(g.get("height", 32) * self.zoom)
                pygame.draw.rect(screen, ghost_stroke, Rect(tl[0], tl[1], w, h), 1)
            elif stype == "circle":
                c = self.local_to_screen((ox, oy))
                r = round(g.get("radius", 16) * self.zoom)
                pygame.draw.circle(screen, ghost_stroke, c, r, 1)
            elif stype == "polygon":
                vs = g.get("vertices", [])
                if len(vs) >= 3:
                    pts = [self.local_to_screen(v) for v in vs]
                    pygame.draw.polygon(screen, ghost_stroke, pts, 1)

    def _draw_hull(self, screen: Surface, hull: tuple[float, float, float, float]) -> None:
        l, t, r, b = hull
        tl = self.local_to_screen((l, t))
        br = self.local_to_screen((r, b))
        hull_rect = Rect(tl[0], tl[1], max(1, br[0] - tl[0]), max(1, br[1] - tl[1]))

        # Dashed line
        dash, gap = 6, 4
        color = (110, 190, 255)
        for (p1, p2) in [
            (hull_rect.topleft, hull_rect.topright),
            (hull_rect.topright, hull_rect.bottomright),
            (hull_rect.bottomright, hull_rect.bottomleft),
            (hull_rect.bottomleft, hull_rect.topleft),
        ]:
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if length < 1:
                continue
            dx, dy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length
            dist = 0.0
            while dist < length:
                seg_end = min(dist + dash, length)
                a = (round(p1[0] + dx * dist), round(p1[1] + dy * dist))
                b = (round(p1[0] + dx * seg_end), round(p1[1] + dy * seg_end))
                pygame.draw.line(screen, color, a, b, 1)
                dist += dash + gap

    def _draw_status_overlay(self, screen: Surface) -> None:
        if not self._font:
            return

        lines = [f"Shape: {self.shape_type.upper()} | Zoom: {self.zoom:.1f}x"]
        if self.shape_type == "polygon":
            if self.drawing_polygon:
                lines.append(f"Drawing Polygon: {len(self.drawing_polygon)} pts (Enter/Right-click to finish)")
            elif len(self.polygon_vertices) >= 3:
                convex = is_convex_polygon(self.polygon_vertices)
                lines.append(f"Polygon: {len(self.polygon_vertices)} vertices ({'CONVEX' if convex else 'CONCAVE WARNING'})")
            else:
                lines.append("Click canvas to place polygon vertices")

        if self.show_probe:
            mouse = pygame.mouse.get_pos()
            if self.rect.collidepoint(mouse):
                lx, ly = self.screen_to_local(mouse)
                lines.append(f"Cursor Local: ({lx:.1f}, {ly:.1f})")

        y = self.rect.y + 8
        for line in lines:
            txt = self._font.render(line, True, COLORS.text_dim)
            screen.blit(txt, (self.rect.x + 10, y))
            y += txt.get_height() + 4
