"""
Standalone CLI launcher for Character Hitbox (Detection) Editor.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pygame

from .editor import CharacterHitboxEditor


def parse_window_size(size_str: str) -> tuple[int, int]:
    try:
        w, h = map(int, size_str.lower().split("x"))
        return (w, h)
    except Exception:
        return (1000, 800)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Character Hitbox Editor - define per-clip active detection windows",
    )
    parser.add_argument(
        "animation",
        type=Path,
        nargs="?",
        default=None,
        help="Path to character animation file (.anim.json)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="Character",
        help="Character name (default: Character)",
    )
    parser.add_argument(
        "--load",
        type=Path,
        default=None,
        help="Path to existing .hitbox.json data file to load",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Root path for project data",
    )
    parser.add_argument(
        "--window-size",
        type=str,
        default="1050x800",
        help="Window size as WxH (default: 1050x800)",
    )

    args = parser.parse_args(argv)

    pygame.init()
    win_w, win_h = parse_window_size(args.window_size)
    screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
    pygame.display.set_caption(f"Character Hitbox Editor - {args.name}")

    editor = CharacterHitboxEditor(
        rect=pygame.Rect(0, 0, win_w, win_h),
        character_name=args.name,
        data_root=args.data_root,
    )

    if args.animation is not None:
        if not args.animation.exists():
            print(f"Error: Animation file not found: {args.animation}", file=sys.stderr)
            sys.exit(1)
        editor.load_animation(args.animation)

    if args.load is not None:
        if not args.load.exists():
            print(f"Error: Hitbox file not found: {args.load}", file=sys.stderr)
            sys.exit(1)
        editor.load_hitbox_file(args.load)

    clock = pygame.time.Clock()
    running = True

    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                editor.resize(pygame.Rect(0, 0, event.w, event.h))
            else:
                editor.handle_event(event)

        editor.update(dt, screen)
        screen.fill((20, 22, 26))
        editor.draw(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
