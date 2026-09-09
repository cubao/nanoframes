"""nanoframes command-line interface.

Commands
--------
  init        <name>            scaffold a new `.nf.svg` composition
  check       <comp>            lint the composition contract (exit 1 on errors)
  render      <comp>            render: single frame `--t SEC`, or full batch
  preview     <comp>            render one frame and open it (needs `--t`)
  video       <comp>            render the whole clip to an MP4 via ffmpeg
  measure     <comp>            report renderer-exact glyph widths for text elements
  fonts       list/add/verify/install   CJK font toolbox
  lottie      <file.json>       render a Lottie JSON scene offline to MP4
  walkthrough [-o DIR]          generate the one-take walkthrough
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from nanoframes import __version__
from nanoframes.cache import FrameCache
from nanoframes.lint import has_errors, lint_path
from nanoframes.parse import ParseError, parse_file
from nanoframes.render import render_frame
from nanoframes.video import render_video
from nanoframes import walkthrough

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg"
     data-width="960" data-height="540" data-fps="30" data-duration="6.0"
     data-composition-id="{name}">
  <rect id="bg" width="960" height="540" fill="#0a0c0b"/>
  <text id="title" x="60" y="120" font-family="Sarasa Mono SC" font-weight="700"
        font-size="64" fill="#f4f7ff" data-start="0.0" data-duration="6.0"
        data-fade="0.4">Your title</text>
  <rect id="accent" x="60" y="150" width="6" height="120" fill="#5ef17c"
        data-start="0.4" data-duration="5.0" />
  <text id="sub" x="60" y="330" font-family="Sarasa Mono SC" font-size="26"
        fill="#9aa4b2" data-start="0.8" data-duration="5.0">SVG renders MP4. No browser.</text>
  <script type="application/nanoframes+json"><![CDATA[
  {{
    "animations": [
      {{
        "target": "#title",
        "keyframes": [
          {{"t": 0.0, "opacity": 0.0, "transform": {{"translate": [0, 24]}}}},
          {{"t": 0.6, "opacity": 1.0, "transform": {{"translate": [0, 0]}}, "ease": "ease-out"}}
        ]
      }},
      {{
        "target": "#accent",
        "keyframes": [
          {{"t": 0.4, "opacity": 0.0, "transform": {{"scale": [1.0, 0.02]}}}},
          {{"t": 1.0, "opacity": 1.0, "transform": {{"scale": [1.0, 1.0]}}, "ease": "ease-in-out"}}
        ]
      }}
    ]
  }}
  ]]></script>
</svg>
"""


DEFAULT_CACHE = ".nanoframes-cache"


def _make_cache(args) -> FrameCache | None:
    return None if getattr(args, "no_cache", False) else FrameCache(DEFAULT_CACHE)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nanoframes",
        description="SVG-first, browserless, deterministic frame rendering on ThorVG.",
    )
    p.add_argument("--version", action="version", version=f"nanoframes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold a new .nf.svg composition")
    sp.add_argument("name", help="composition name (and output file name)")
    sp.add_argument("-o", "--output", help="output path (default <name>.nf.svg)")
    sp.set_defaults(handler=cmd_init)

    sp = sub.add_parser("check", help="lint the composition contract")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.set_defaults(handler=cmd_check)

    sp = sub.add_parser("render", help="render a frame or the full clip to PNG")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--t", type=float, default=None, help="render only this time (seconds)")
    sp.add_argument("-o", "--out", default="out", help="output directory or file path")
    sp.add_argument("--threads", type=int, default=4, help="ThorVG thread count")
    sp.set_defaults(handler=cmd_render)
    sp.add_argument("--no-cache", action="store_true",
                    help="disable the fast re-render cache (.nanoframes-cache)")

    sp = sub.add_parser("preview", help="render one frame and open it")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--t", type=float, required=True, help="time in seconds to preview")
    sp.add_argument("--threads", type=int, default=4)
    sp.set_defaults(handler=cmd_preview)

    sp = sub.add_parser("video", help="render the whole clip to an MP4 via ffmpeg")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("-o", "--out", default="out.mp4", help="output MP4 path")
    sp.add_argument("--fps", type=int, default=None, help="override composition fps")
    sp.add_argument("--scale", default=None, help="ffmpeg scale filter, e.g. 720:720")
    sp.add_argument("--threads", type=int, default=4)
    sp.add_argument("--keep-frames", default=None, help="keep the PNG sequence at this dir")
    sp.add_argument("--audio", default=None, help="mux this audio file into the MP4 (aac, shortest)")
    sp.set_defaults(handler=cmd_video)
    sp.add_argument("--no-cache", action="store_true",
                    help="disable the fast re-render cache (.nanoframes-cache)")

    sp = sub.add_parser("measure", help="report renderer-exact glyph widths for text elements")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.set_defaults(handler=cmd_measure)

    sp = sub.add_parser("fonts", help="manage CJK/added fonts (list / add / verify / install)")
    fsub = sp.add_subparsers(dest="fonts_command", required=True)
    fp = fsub.add_parser("list", help="discover available CJK-capable fonts and family names")
    fp.set_defaults(fhandler=cmd_fonts_list)
    fp = fsub.add_parser("add", help="copy a font into the nanoframes user font dir")
    fp.add_argument("path", help="path to a .ttf/.otf font file")
    fp.set_defaults(fhandler=cmd_fonts_add)
    fp = fsub.add_parser("verify", help="check a font loads+rasterizes without crashing ThorVG (subprocess)")
    fp.add_argument("path", help="path to a .ttf/.otf font file")
    fp.set_defaults(fhandler=cmd_fonts_verify)
    fp = fsub.add_parser("install", help="fetch a CJK monospace font (default: Sarasa Mono SC)")
    fp.set_defaults(fhandler=cmd_fonts_install)

    sp = sub.add_parser("lottie", help="render a Lottie JSON scene to MP4 (ThorVG loader, offline)")
    sp.add_argument("file", help="path to a Lottie/Bodymovin .json scene")
    sp.add_argument("-o", "--out", default="out.mp4", help="output MP4 path")
    sp.add_argument("--scale", default=None, help="ffmpeg scale filter, e.g. 720:720")
    sp.add_argument("--keep-frames", default=None, help="keep the PNG sequence at this dir")
    sp.add_argument("--audio", default=None, help="mux this audio file into the MP4 (aac, shortest)")
    sp.add_argument("--threads", type=int, default=4)
    sp.set_defaults(handler=cmd_lottie)

    sp = sub.add_parser("walkthrough", help="generate the self-contained one-take walkthrough")
    sp.add_argument("-o", "--out", default="build/walkthrough", help="output dir")
    sp.add_argument("--no-audio", action="store_true", help="skip audio synthesis/mux")
    sp.set_defaults(handler=cmd_walkthrough)

    return p


def _load(path: str):
    if not os.path.exists(path):
        print(f"nanoframes: no such file: {path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        return parse_file(path)
    except ParseError as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        raise SystemExit(2)


def cmd_init(args: argparse.Namespace) -> int:
    path = args.output or f"{args.name}.nf.svg"
    if os.path.exists(path):
        print(f"nanoframes: {path} already exists", file=sys.stderr)
        return 2
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE.format(name=args.name))
    print(f"created {path}")
    print("  nanoframes check {path}".format(path=path))
    print(f"  nanoframes render {path} --t 1.0")
    return 0


def cmd_measure(args: argparse.Namespace) -> int:
    from nanoframes.measure import Measurer
    from nanoframes.xmlutil import local_name

    doc = parse_file(args.composition)
    measurer = Measurer()
    rows = []
    for node in doc.root.iter():
        if local_name(node.tag) != "text":
            continue
        t = (node.text or "").strip()
        if not t:
            continue
        family = node.get("font-family") or "Arial"
        weight = node.get("font-weight") or "normal"
        size = float(node.get("font-size") or 16)
        m = measurer.ink(t, family, weight, size)
        rows.append((node.get("id") or "?", t, size, round(m.w, 1)))
    if not rows:
        print("no <text> elements")
        return 0
    print(f"{'id':<12}{'text':<28}{'size':>5}  width(px)")
    for i, t, size, w in rows:
        print(f"{i:<12}{t[:26]:<28}{size:>5}  {w}")
    return 0


def _user_font_dir() -> str:
    d = os.path.expanduser("~/.local/share/nanoframes/fonts")
    os.makedirs(d, exist_ok=True)
    return d


def cmd_fonts_list(args: argparse.Namespace) -> int:
    from nanoframes.fonts import discover_fonts

    fonts = [f for f in discover_fonts() if f.cjk]
    print(f"CJK-capable fonts discovered: {len(fonts)}")
    for f in sorted(fonts, key=lambda x: (not x.mono, x.family)):
        mark = "mono " if f.mono else "     "
        print(f"  {mark}{f.family:<22}{f.style:<10}{os.path.basename(f.path)}")
    print("\nfont-family uses the font's exact family name above.")
    print("Not all loads are ThorVG-safe; run `nanoframes fonts verify <path>` on any you rely on.")
    return 0


def cmd_fonts_add(args: argparse.Namespace) -> int:
    import shutil
    from nanoframes.fonts import family_name

    src = args.path
    if not os.path.exists(src):
        print(f"no such file: {src}", file=sys.stderr)
        return 2
    family, style = family_name(src)
    dst = os.path.join(_user_font_dir(), os.path.basename(src))
    shutil.copyfile(src, dst)
    print(f"added {src} -> {dst}")
    print(f"family={family!r} style={style!r}")
    print("verify it is ThorVG-safe with: nanoframes fonts verify " + dst)
    return 0


def cmd_fonts_verify(args: argparse.Namespace) -> int:
    """Check a font loads+rasterizes without crashing ThorVG (isolated subprocess).

    Some fonts segfault this ThorVG build at engine teardown; the check runs in
    a separate process (``nanoframes.scripts.verify_font``) so a crash surfaces
    as exit code 139 here instead of taking the CLI down.
    """
    from nanoframes.fonts import family_name

    family = family_name(args.path)[0]
    proc = subprocess.run(
        [sys.executable, "-m", "nanoframes.scripts.verify_font", args.path, family],
        capture_output=True, text=True,
    )
    print(proc.stdout.strip())
    if proc.returncode == 139:
        print(f"UNSAFE: {args.path} crashes ThorVG at exit (code 139). Do not use.")
        return 1
    if proc.returncode != 0 or not proc.stdout.strip():
        print(f"verify failed (code {proc.returncode}): {proc.stderr.strip()}")
        return 1
    print(f"safe: {args.path} loaded and rasterized in an isolated subprocess.")
    return 0


def cmd_fonts_install(args: argparse.Namespace) -> int:
    """Best-effort fetch of a CJK monospace font (Sarasa Mono SC) into the user dir."""
    import urllib.request

    urls = [
        # Sarasa Mono SC regular ttf mirrors; the exact URL/size varies by release.
        "https://cdn.jsdelivr.net/gh/be5invis/Sarasa-Gothic@v1.0.2/release/sarasa-monera-sc-regular.ttf",
        "https://registry.npmmirror.com/sarasa-mono-sc/-/sarasa-mono-sc-1.0.0.tgz",
    ]
    dst_dir = _user_font_dir()
    out = os.path.join(dst_dir, "sarasa-mono-sc.ttf")
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nanoframes"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = resp.read()
            if len(data) < 1000:
                continue
            with open(out, "wb") as fh:
                fh.write(data)
            print(f"downloaded {len(data)} bytes -> {out}")
            print("verify: nanoframes fonts verify " + out)
            return 0
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
    print(f"could not download a font from {len(urls)} source(s); last error: {last}", file=sys.stderr)
    print("drop any .ttf/.otf into " + dst_dir + " and use `nanoframes fonts list` to see its family.")
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    findings = lint_path(args.composition)
    for f in findings:
        print(str(f))
    if has_errors(findings):
        print(f"nanoframes: {sum(1 for f in findings if f.severity == 'error')} error(s)")
        return 1
    print(f"nanoframes: ok ({len(findings)} finding(s), 0 errors)")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    doc = _load(args.composition)
    comp = doc.composition
    errors = has_errors(lint_path(args.composition))
    if errors:
        print("nanoframes: refusing to render a composition with lint errors "
              "(run `nanoframes check`)", file=sys.stderr)
        return 1

    out_dir = args.out
    cache = _make_cache(args)
    if args.t is not None:
        # single frame -> write PNG to args.out (treat as file or dir/<name>_t.png)
        dst = _frame_dest(doc, args.out, args.t)
        render_frame(doc, args.t, out_path=dst, threads=args.threads, cache=cache)
        print(f"rendered {dst}")
        return 0

    # full batch: frame i at t = i/fps, i in 0..frame_count-1
    os.makedirs(out_dir, exist_ok=True)
    prefix = comp.composition_id or os.path.splitext(os.path.basename(args.composition))[0]
    step = 1.0 / comp.fps
    for i in range(comp.frame_count):
        t = i * step
        dst = os.path.join(out_dir, f"{prefix}.{i:05d}.png")
        render_frame(doc, t, out_path=dst, threads=args.threads, cache=cache)
    print(f"rendered {comp.frame_count} frames to {out_dir}/ ({prefix}.*.png)")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    doc = _load(args.composition)
    dst = "/tmp/nanoframes_preview.png"
    render_frame(doc, args.t, out_path=dst, threads=args.threads, cache=_make_cache(args))
    if sys.platform == "darwin":
        subprocess.run(["open", dst], check=True)
    elif sys.platform == "linux":
        subprocess.run(["xdg-open", dst], check=True)
    else:
        print(dst)
        return 0
    print(f"preview opened for t={args.t}s -> {dst}")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    doc = _load(args.composition)
    if has_errors(lint_path(args.composition)):
        print("nanoframes: refusing to render a composition with lint errors "
              "(run `nanoframes check`)", file=sys.stderr)
        return 1
    render_video(doc, args.out, fps=args.fps, scale=args.scale, threads=args.threads,
                 keep_frames=args.keep_frames, cache=_make_cache(args), audio=args.audio)
    print(f"wrote {args.out}")
    return 0


def cmd_lottie(args: argparse.Namespace) -> int:
    """Render a Lottie JSON scene offline (ThorVG's native loader) to MP4."""
    from nanoframes.lottie import LottieError, render_lottie_video

    try:
        render_lottie_video(args.file, args.out, scale=args.scale, threads=args.threads,
                            keep_frames=args.keep_frames, audio=args.audio)
    except (LottieError, subprocess.CalledProcessError) as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0


def cmd_walkthrough(args: argparse.Namespace) -> int:
    return walkthrough.main(["-o", args.out] + (["--no-audio"] if args.no_audio else []))


def _frame_dest(doc, out, t: float) -> str:
    """Resolve the destination path for a single-frame render."""
    if out.endswith(".png") or os.path.isdir(out) or out.endswith(os.sep):
        # file path chosen by user, or a directory
        if os.path.isdir(out) or out.endswith("/"):
            return os.path.join(out, f"frame_{t:g}.png")
        return out
    name = doc.composition.composition_id or os.path.splitext(out)[0]
    return f"{name}_t{t:g}.png"


def _resource_dirs() -> tuple[str, str] | None:
    """Absolute (docs_dir, skills_dir) — repo checkout first, then package copy.

    In a repo checkout the docs/skills sit next to the package
    (``<repo>/docs``, ``<repo>/skills``); in a wheel install they are embedded
    inside the package (``nanoframes/docs``, ``nanoframes/skills``).
    """
    pkg = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.dirname(pkg), pkg):
        docs = os.path.join(base, "docs")
        skills = os.path.join(base, "skills", "nanoframes")
        if os.path.isdir(docs) and os.path.isdir(skills):
            return docs, skills
    return None


def guide_text() -> str:
    """Point users (agents) at the docs and agent skill shipped with the package."""
    lines = [
        "nanoframes — SVG-first, browserless, deterministic frame rendering on ThorVG.",
        "Docs and the agent skill ship with the package; read them before composing:",
        "",
    ]
    found = _resource_dirs()
    if found:
        docs, skills = found
        lines += [
            f"  composition contract ... {os.path.join(docs, 'composition.md')}",
            f"  architecture ............ {os.path.join(docs, 'architecture.md')}",
            f"  text capabilities ....... {os.path.join(docs, 'text-capabilities.md')}",
            f"  lottie import ........... {os.path.join(docs, 'lottie.md')}",
            f"  agent skill ............. {os.path.join(skills, 'SKILL.md')}",
            "",
        ]
    else:
        lines += ["  (docs/skills not found next to this install)", ""]
    lines += ["Usage: nanoframes <command> ...    (nanoframes --help for the command list)"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        print(guide_text())
        return 2
    args = build_parser().parse_args(args_list)
    if hasattr(args, "fhandler") and args.fhandler is not None:
        return args.fhandler(args)
    try:
        return args.handler(args)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())