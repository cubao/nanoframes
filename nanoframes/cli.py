"""nanoframes command-line interface."""

from __future__ import annotations

import argparse
import sys

from nanoframes import __version__

COMMANDS = ("init", "render", "preview", "check")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nanoframes",
        description="SVG-first, browserless, deterministic frame rendering on ThorVG.",
    )
    p.add_argument("--version", action="version", version=f"nanoframes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        sp = sub.add_parser(name, help=f"`nanoframes {name}` — see docs/composition.md")
        sp.add_argument("composition", nargs="?", help="path to a .nf.svg composition")
        sp.add_argument("--t", type=float, default=None, help="single-frame time in seconds")
        sp.add_argument("--frames", type=int, default=None, help="batch frame count")
        sp.set_defaults(handler=_not_impl)
    return p


def _not_impl(args: argparse.Namespace) -> int:
    print(f"nanoframes {args.command}: not implemented yet (see docs/architecture.md milestones)",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())