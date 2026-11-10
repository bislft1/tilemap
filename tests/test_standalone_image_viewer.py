"""Tests for the standalone image viewer and tilemap-editor view command."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure dummy video driver for headless test runs
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from standalone_image_viewer import ImageViewer, main, parse_size

PY = sys.executable


@pytest.fixture
def sample_image(tmp_path):
    pygame.init()
    surf = pygame.Surface((128, 64))
    surf.fill((100, 150, 200))
    path = tmp_path / "test_sheet.png"
    pygame.image.save(surf, str(path))
    return path


class TestSizeParsing:
    def test_single_number(self):
        assert parse_size("32") == (32, 32)
        assert parse_size("16") == (16, 16)

    def test_width_and_height(self):
        assert parse_size("16x32") == (16, 32)
        assert parse_size("64X48") == (64, 48)

    def test_invalid_formats(self):
        with pytest.raises(ValueError):
            parse_size("16x32x48")
        with pytest.raises(ValueError):
            parse_size("abc")


class TestImageViewerLogic:
    def test_cell_sizing_calculation(self, sample_image):
        # 128x64 image with 32x32 cells -> 4 cols, 2 rows
        viewer = ImageViewer(sample_image, cell_size=(32, 32))
        assert viewer.grid_cols == 4
        assert viewer.grid_rows == 2
        assert viewer.show_grid_overlay is True
        assert viewer.cell_w_input_text == "32"
        assert viewer.cell_h_input_text == "32"
        assert viewer.rows_input_text == "2"
        assert viewer.cols_input_text == "4"

    def test_variants_enables_grid_overlay(self, sample_image):
        viewer = ImageViewer(sample_image, cell_size=(32, 32), show_variants=True)
        assert viewer.show_variant_ids is True
        assert viewer.show_grid_overlay is True

    def test_no_grid_explicit(self, sample_image):
        viewer = ImageViewer(sample_image, cell_size=(32, 32), show_grid=False)
        assert viewer.show_grid_overlay is False

    def test_apply_cell(self, sample_image):
        # 128x64 image. Start with 1x1 grid.
        viewer = ImageViewer(sample_image)
        assert viewer.grid_cols == 1
        assert viewer.grid_rows == 1

        viewer.cell_w_input_text = "16"
        viewer.cell_h_input_text = "16"
        viewer.apply_cell()

        assert viewer.grid_cols == 8
        assert viewer.grid_rows == 4
        assert viewer.rows_input_text == "4"
        assert viewer.cols_input_text == "8"
        assert viewer.show_grid_overlay is True

    def test_apply_grid(self, sample_image):
        viewer = ImageViewer(sample_image)
        viewer.rows_input_text = "4"
        viewer.cols_input_text = "2"
        viewer.apply_grid()

        assert viewer.grid_rows == 4
        assert viewer.grid_cols == 2
        # 128 // 2 = 64, 64 // 4 = 16
        assert viewer.cell_w_input_text == "64"
        assert viewer.cell_h_input_text == "16"
        assert viewer.show_grid_overlay is True

    def test_toggle_shortcuts(self, sample_image):
        viewer = ImageViewer(sample_image, show_variants=False, show_grid=False)
        assert viewer.show_variant_ids is False
        assert viewer.show_grid_overlay is False

        # Press 'v' to toggle variants (which should also enable grid)
        v_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v)
        viewer.handle_general_keydown(v_event)
        assert viewer.show_variant_ids is True
        assert viewer.show_grid_overlay is True

        # Press 'v' again to turn variants off
        viewer.handle_general_keydown(v_event)
        assert viewer.show_variant_ids is False

        # Press 'g' to toggle grid
        g_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)
        viewer.handle_general_keydown(g_event)
        assert viewer.show_grid_overlay is False

    def test_variant_id_indexing_formula(self, sample_image):
        viewer = ImageViewer(sample_image, cell_size=(16, 16))
        # 128x64 image with 16x16 cells -> 8 cols, 4 rows = 32 variants
        assert viewer.grid_cols == 8
        assert viewer.grid_rows == 4
        # row 2, col 3 -> 2 * 8 + 3 = 19
        row, col = 2, 3
        expected_variant = row * viewer.grid_cols + col
        assert expected_variant == 19

    def test_draw_renders_without_crash(self, sample_image):
        viewer = ImageViewer(sample_image, cell_size=(32, 32), show_variants=True)
        # Verify draw() call completes cleanly with dummy video driver
        viewer.draw()


class TestCliMainValidation:
    def test_missing_image_returns_error(self, tmp_path):
        non_existent = tmp_path / "nope.png"
        code = main([str(non_existent)])
        assert code == 1

    def test_invalid_cell_size_returns_error(self, sample_image):
        code = main([str(sample_image), "--cell", "invalid_size"])
        assert code == 2


class TestTilemapEditorViewCli:
    def _cli(self, *args):
        exe = Path(PY).parent / "tilemap-editor"
        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        return subprocess.run(
            [str(exe), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    def test_help_lists_view_and_viewer(self):
        proc = self._cli("--help")
        assert proc.returncode == 0
        assert "view" in proc.stdout

    def test_view_subcommand_help(self):
        proc = self._cli("view", "--help")
        assert proc.returncode == 0
        assert "--cell" in proc.stdout
        assert "--variants" in proc.stdout

    def test_viewer_alias_help(self):
        proc = self._cli("viewer", "--help")
        assert proc.returncode == 0
        assert "--cell" in proc.stdout
        assert "--variants" in proc.stdout

    def test_view_subcommand_forwards_errors(self, tmp_path):
        proc = self._cli("view", str(tmp_path / "nonexistent.png"))
        assert proc.returncode == 1
        assert "not found" in proc.stderr

