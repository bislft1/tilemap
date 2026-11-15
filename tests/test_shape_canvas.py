import math
import pygame
from pygame import Rect, Surface

from widgets.ui.shape_canvas import (
    ShapeCanvas,
    is_convex_polygon,
    point_in_polygon,
    point_to_segment_distance,
)


def test_is_convex_polygon():
    # Triangle is always convex
    tri = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
    assert is_convex_polygon(tri) is True

    # Convex quad (square)
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert is_convex_polygon(square) is True

    # Concave polygon (dart / arrow)
    concave = [(0.0, 0.0), (10.0, 0.0), (5.0, 3.0), (10.0, 10.0), (0.0, 10.0)]
    assert is_convex_polygon(concave) is False


def test_point_in_polygon():
    poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_polygon((5.0, 5.0), poly) is True
    assert point_in_polygon((15.0, 5.0), poly) is False
    assert point_in_polygon((-1.0, 5.0), poly) is False


def test_point_to_segment_distance():
    a = (0.0, 0.0)
    b = (10.0, 0.0)
    dist, closest = point_to_segment_distance((5.0, 3.0), a, b)
    assert math.isclose(dist, 3.0, abs_tol=1e-4)
    assert math.isclose(closest[0], 5.0, abs_tol=1e-4)
    assert math.isclose(closest[1], 0.0, abs_tol=1e-4)


def test_shape_canvas_coords_and_zoom():
    if not pygame.get_init():
        pygame.init()

    canvas = ShapeCanvas(Rect(100, 50, 400, 300))
    canvas.offset_x = 0.0
    canvas.offset_y = 0.0
    canvas.zoom = 2.0

    # Local (10, 20) -> screen: 100 + 10*2 = 120, 50 + 20*2 = 90
    sx, sy = canvas.local_to_screen((10.0, 20.0))
    assert sx == 120
    assert sy == 90

    lx, ly = canvas.screen_to_local((120, 90))
    assert math.isclose(lx, 10.0, abs_tol=1e-3)
    assert math.isclose(ly, 20.0, abs_tol=1e-3)


def test_shape_canvas_shape_data_io():
    canvas = ShapeCanvas(Rect(0, 0, 500, 500))

    # Rectangle
    rect_data = {"type": "rectangle", "width": 48.0, "height": 32.0, "offset": (10.0, 15.0)}
    canvas.load_shape_data(rect_data)
    assert canvas.shape_type == "rectangle"
    assert canvas.rect_w == 48.0
    assert canvas.rect_h == 32.0
    assert canvas.rect_x == 10.0
    assert canvas.rect_y == 15.0
    saved = canvas.get_shape_data()
    assert saved["type"] == "rectangle"
    assert saved["width"] == 48.0

    # Circle
    circle_data = {"type": "circle", "radius": 20.0, "offset": (30.0, 30.0)}
    canvas.load_shape_data(circle_data)
    assert canvas.shape_type == "circle"
    assert canvas.circle_radius == 20.0
    assert canvas.circle_x == 30.0
    assert canvas.circle_y == 30.0

    # Polygon
    poly_data = {
        "type": "polygon",
        "vertices": [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        "offset": (0.0, 0.0),
    }
    canvas.load_shape_data(poly_data)
    assert canvas.shape_type == "polygon"
    assert len(canvas.polygon_vertices) == 4
    out_poly = canvas.get_shape_data()
    assert len(out_poly["vertices"]) == 4


def test_shape_canvas_polygon_edge_split():
    canvas = ShapeCanvas(Rect(0, 0, 400, 400))
    canvas.offset_x = 0.0
    canvas.offset_y = 0.0
    canvas.zoom = 1.0

    poly_data = {
        "type": "polygon",
        "vertices": [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        "offset": (0.0, 0.0),
    }
    canvas.load_shape_data(poly_data)

    # Hover near top edge (50, 0)
    edge = canvas._find_polygon_edge_at((50, 2))
    assert edge is not None
    idx, pt = edge
    assert idx == 0  # between 0 and 1
    assert math.isclose(pt[0], 50.0, abs_tol=1e-1)
    assert math.isclose(pt[1], 0.0, abs_tol=1e-1)
