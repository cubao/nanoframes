"""nanoframes command-line interface.

Commands
--------
  init        <name>            scaffold a new `.nf.svg` composition
  check       <comp>            lint the composition contract (exit 1 on errors)
  debug       <comp>            where each element's geometry lands, frame by frame
  render      <comp>            render: single frame `--t SEC`, or full batch
  preview     <comp>            render one frame and open it (needs `--t`)
  video       <comp>            render the whole clip to an MP4 via ffmpeg
  measure     <comp>            report renderer-exact glyph widths for text elements
  fonts       list/add/verify/install   CJK font toolbox
  lottie      <file.json>       render a Lottie JSON scene offline to MP4
  diagram     <spec.json>       build a .nf.svg composition from a diagram spec
  walkthrough [-o DIR]          generate the one-take walkthrough
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from nanoframes import __version__, walkthrough
from nanoframes.cache import FrameCache
from nanoframes.lint import has_errors, lint_path, lint_string
from nanoframes.parse import ParseError, parse_file
from nanoframes.render import frame_is_blank, measurer, render_frame
from nanoframes.video import render_video

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
          {{"t": 0.4, "opacity": 0.0, "transform": {{"scale": [1.0, 0.02], "center": "auto"}}}},
          {{"t": 1.0, "opacity": 1.0, "transform": {{"scale": [1.0, 1.0], "center": "auto"}}, "ease": "ease-in-out"}}
        ]
      }}
    ]
  }}
  ]]></script>
</svg>
"""


DEFAULT_CACHE = ".nanoframes-cache"


def _add_scale(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--scale", type=float, default=1.0, metavar="F",
        help="draft render at F x the size (e.g. 0.5); faster, for previewing",
    )


def _add_dpi(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--dpi", type=float, default=1.0, metavar="F",
        help="delivery resolution: rasterize at F x the pixel density (e.g. 2)",
    )


def _dpi_of(args: argparse.Namespace) -> float:
    dpi = getattr(args, "dpi", 1.0)
    if dpi <= 0:
        print(f"nanoframes: --dpi must be positive, got {dpi}", file=sys.stderr)
        raise SystemExit(2)
    return dpi


def _scale_of(args: argparse.Namespace) -> float:
    scale = getattr(args, "scale", 1.0)
    if scale <= 0:
        print(f"nanoframes: --scale must be positive, got {scale}", file=sys.stderr)
        raise SystemExit(2)
    return scale


def _make_cache(args) -> FrameCache | None:
    return None if getattr(args, "no_cache", False) else FrameCache(DEFAULT_CACHE)


def _media_resolver(doc, scale: float):
    """A prepared video resolver for this composition, or ``None`` if it has none.

    Preparation (frame extraction) is expensive and content-keyed, so it happens
    once here rather than per frame; the extraction cache is separate from the
    frame cache and is not disabled by ``--no-cache``.
    """
    from nanoframes.media import MediaCache, MediaResolver, has_video_source

    if not has_video_source(doc):
        return None
    resolver = MediaResolver(MediaCache(DEFAULT_CACHE), doc.composition.fps, scale)
    for warning in resolver.prepare(doc):
        print(f"nanoframes: {warning}", file=sys.stderr)
    return resolver


def build_parser() -> argparse.ArgumentParser:
    # The docs/skill pointer must ride on --help as well: agents reach for
    # `nanoframes --help` first, and a bare command list drops them into a
    # subcommand without ever showing where the contract lives.
    epilog = "\n".join([
        "Docs and the agent skill ship with the package; read them before composing:",
        *_resource_lines(),
    ])
    p = argparse.ArgumentParser(
        prog="nanoframes",
        description="SVG-first, browserless, deterministic frame rendering on ThorVG.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"nanoframes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold a new .nf.svg composition")
    sp.add_argument("name", help="composition name (and output file name)")
    sp.add_argument("-o", "--output", help="output path (default <name>.nf.svg)")
    sp.set_defaults(handler=cmd_init)

    sp = sub.add_parser("check", help="lint the composition contract")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--json", action="store_true",
                    help="emit findings as JSON (stable 'code' per finding) instead of lines")
    sp.set_defaults(handler=cmd_check)

    sp = sub.add_parser("debug", help="show where each element's geometry lands")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--t", type=float, default=0.0, help="frame to report (seconds)")
    sp.add_argument("--samples", type=int, default=24, help="frames sampled by the clip scan")
    sp.add_argument("--no-scan", action="store_true", help="skip the whole-clip scan")
    sp.add_argument("--loop", action="store_true",
                    help="also compare the first and last frame (loop seam)")
    sp.add_argument("--json", action="store_true",
                    help="emit the report as JSON instead of the text layout")
    sp.set_defaults(handler=cmd_debug)

    sp = sub.add_parser("render", help="render a frame or the full clip to PNG")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--t", type=float, default=None, help="render only this time (seconds)")
    sp.add_argument("-o", "--out", default="out", help="output directory or file path")
    sp.add_argument("--threads", type=int, default=4, help="ThorVG thread count")
    _add_scale(sp)
    _add_dpi(sp)
    sp.set_defaults(handler=cmd_render)
    sp.add_argument("--no-cache", action="store_true",
                    help="disable the fast re-render cache (.nanoframes-cache)")

    sp = sub.add_parser("preview", help="render one frame and open it")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("--t", type=float, required=True, help="time in seconds to preview")
    sp.add_argument("--threads", type=int, default=4)
    _add_scale(sp)
    _add_dpi(sp)
    sp.set_defaults(handler=cmd_preview)

    sp = sub.add_parser("video", help="render the whole clip to an MP4 via ffmpeg")
    sp.add_argument("composition", help="path to a .nf.svg composition")
    sp.add_argument("-o", "--out", default="out.mp4", help="output MP4 path")
    sp.add_argument("--fps", type=int, default=None, help="override composition fps")
    _add_scale(sp)
    _add_dpi(sp)
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
    _add_scale(sp)
    sp.add_argument("--keep-frames", default=None, help="keep the PNG sequence at this dir")
    sp.add_argument("--audio", default=None, help="mux this audio file into the MP4 (aac, shortest)")
    sp.add_argument("--bg", default="white",
                    help="backdrop for the scene's transparent areas (a color, or 'none'"
                         " to keep alpha in --keep-frames PNGs); default: white")
    sp.add_argument("--threads", type=int, default=4)
    sp.set_defaults(handler=cmd_lottie)

    sp = sub.add_parser("diagram", help="build a .nf.svg from a diagram spec (JSON)")
    sp.add_argument("spec", help="path to a diagram spec JSON (nodes/edges or loop stations)")
    sp.add_argument("-o", "--out", default=None,
                    help="output composition path (default <spec>.nf.svg)")
    sp.add_argument("--check", action="store_true",
                    help="build, then lint the composition; exit 1 on lint errors")
    sp.set_defaults(handler=cmd_diagram)

    sp = sub.add_parser("cache", help="show or clear the fast re-render cache")
    sp.add_argument("--clear", action="store_true",
                    help="delete the cache directory (safe: it only holds rendered frames)")
    sp.add_argument("--trim", action="store_true",
                    help="evict oldest frames until the cache is back under its size cap")
    sp.set_defaults(handler=cmd_cache)

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
        raise SystemExit(2) from None


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
    """Lint the contract (geometry checks measure text, so ThorVG may load)."""
    findings = lint_path(args.composition)
    errors = sum(1 for f in findings if f.severity == "error")
    if args.json:
        print(json.dumps({
            "ok": errors == 0,
            "errors": errors,
            "warnings": len(findings) - errors,
            "findings": [f.to_dict() for f in findings],
        }, ensure_ascii=False))
        return 1 if errors else 0
    for f in findings:
        print(str(f))
    if errors:
        print(f"nanoframes: {errors} error(s)")
        return 1
    print(f"nanoframes: ok ({len(findings)} finding(s), 0 errors)")
    return 0


def cmd_debug(args: argparse.Namespace) -> int:
    """Report where each element's geometry lands, frame by frame."""
    from nanoframes import diagnose

    doc = _load(args.composition)
    m = measurer()
    report = diagnose.frame_report(doc, args.t, measurer=m)
    scan = None if args.no_scan else diagnose.scan_clip(
        doc, measurer=m, samples=max(2, args.samples))
    seam = diagnose.loop_seam(doc) if args.loop else None

    if args.json:
        payload: dict = {"frame": report.to_dict()}
        if scan is not None:
            payload["scan"] = scan.to_dict()
        if seam is not None:
            payload["loop_seam"] = seam.to_dict()
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"frame {report.frame_index}  t={report.t:g}s  canvas {report.width}x{report.height}")
    if report.coverage is not None:
        print(f"  alpha coverage: {report.coverage * 100:.1f}% of the canvas")
    if not report.elements:
        print("  (no renderable elements)")
    for el in report.elements:
        print(f"  {'  ' * el.depth}{el.label:<16}{el.status_line()}")
    for blank in report.blanks:
        print(f"  ^ {blank.label} paints nothing at this time: its geometry misses the canvas"
              f" — an animated translate that leaves the frame, or a rotate with no pivot"
              f" (`nanoframes check` names those)")

    if scan is not None:
        print(f"clip scan: {scan.sampled} of {scan.frame_count} frames sampled")
        for entry in scan.reported():
            counts = (f"painted in {entry.painted_frames}/{scan.sampled} sampled frames,"
                      f" on-canvas in {entry.on_canvas_frames}/{scan.sampled}")
            flag = ""
            if entry.never_visible:
                flag = "  <-- draws nothing in any sampled frame"
            elif entry.first_off_at is not None:
                flag = f"  (first off-canvas at t={entry.first_off_at:g})"
            print(f"  {entry.label:<16}{counts}{flag}")
        if not scan.never_visible and not any(e.first_off_at is not None for e in scan.elements):
            print("  every element lands on the canvas throughout")

    if seam is not None:
        verdict = "closed (identical)" if seam.closed else "OPEN"
        print(f"loop seam: frame 0 (t={seam.first_t:g}) vs last frame (t={seam.last_t:g}):"
              f" {seam.differing_fraction * 100:.2f}% of pixels differ,"
              f" max channel delta {seam.max_channel_delta} — {verdict}")
        if not seam.closed:
            print("  a seamless loop closes at t = duration - 1/fps; the motion has to"
                  " finish by then and hold (see docs/composition.md)")
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
    scale = _scale_of(args)
    resolver = _media_resolver(doc, scale)
    if args.t is not None:
        # single frame -> write PNG to args.out (treat as file or dir/<name>_t.png)
        dst = _frame_dest(doc, args.out, args.t)
        render_frame(doc, args.t, out_path=dst, threads=args.threads, cache=cache,
                     scale=scale, dpi=_dpi_of(args), media_resolver=resolver)
        print(f"rendered {dst}")
        return 0

    # full batch: frame i at t = i/fps, i in 0..frame_count-1
    os.makedirs(out_dir, exist_ok=True)
    prefix = comp.composition_id or os.path.splitext(os.path.basename(args.composition))[0]
    step = 1.0 / comp.fps
    blank = []
    for i in range(comp.frame_count):
        t = i * step
        dst = os.path.join(out_dir, f"{prefix}.{i:05d}.png")
        img = render_frame(doc, t, out_path=dst, threads=args.threads, cache=cache,
                           scale=scale, dpi=_dpi_of(args), warn_blank=False,
                           media_resolver=resolver)
        if frame_is_blank(img):
            blank.append(t)
    print(f"rendered {comp.frame_count} frames to {out_dir}/ ({prefix}.*.png)")
    _report_blank_frames(blank, comp.frame_count, args.composition)
    return 0


def _report_blank_frames(blank: list[float], total: int, composition: str) -> None:
    """One summary line for frames that came out fully transparent."""
    if not blank:
        return
    shown = ", ".join(f"{t:g}" for t in blank[:6]) + ("…" if len(blank) > 6 else "")
    print(f"nanoframes: {len(blank)} of {total} frames rendered fully transparent"
          f" (t={shown}s) — every element is hidden or off-canvas there;"
          f" run `nanoframes debug {composition} --t {blank[0]:g}`.", file=sys.stderr)


def cmd_preview(args: argparse.Namespace) -> int:
    doc = _load(args.composition)
    dst = "/tmp/nanoframes_preview.png"
    scale = _scale_of(args)
    render_frame(doc, args.t, out_path=dst, threads=args.threads, cache=_make_cache(args),
                 scale=scale, dpi=_dpi_of(args), media_resolver=_media_resolver(doc, scale))
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
    scale = _scale_of(args)
    render_video(doc, args.out, fps=args.fps, scale=scale, threads=args.threads,
                 keep_frames=args.keep_frames, cache=_make_cache(args), audio=args.audio,
                 dpi=_dpi_of(args), media_resolver=_media_resolver(doc, scale))
    print(f"wrote {args.out}")
    return 0


def cmd_lottie(args: argparse.Namespace) -> int:
    """Render a Lottie JSON scene offline (ThorVG's native loader) to MP4."""
    from nanoframes.lottie import LottieError, parse_background, render_lottie_video

    try:
        background = parse_background(args.bg)
        if background is None and not args.keep_frames:
            print("nanoframes: --bg none only affects --keep-frames PNGs;"
                  " the MP4 flattens alpha onto black", file=sys.stderr)
        render_lottie_video(args.file, args.out, scale=_scale_of(args), threads=args.threads,
                            keep_frames=args.keep_frames, audio=args.audio,
                            background=background)
    except (LottieError, subprocess.CalledProcessError) as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0


def cmd_diagram(args: argparse.Namespace) -> int:
    """Build a diagram spec into a composition (and optionally lint it)."""
    from nanoframes.diagram import build_scene, load_spec, render
    from nanoframes.diagram.spec import SpecError

    if not os.path.exists(args.spec):
        print(f"nanoframes: no such file: {args.spec}", file=sys.stderr)
        return 2
    try:
        spec = load_spec(args.spec)
    except SpecError as exc:
        for problem in exc.problems:
            print(f"[error] {problem}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        return 2

    m = measurer()
    try:
        scene = build_scene(spec, measurer=m)
    except ValueError as exc:
        print(f"nanoframes: {exc}", file=sys.stderr)
        return 1
    out = args.out or os.path.splitext(args.spec)[0] + ".nf.svg"
    name = os.path.splitext(os.path.basename(out))[0]
    svg = render(scene, composition_id=name, measurer=m)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)

    for warning in scene.warnings:
        print(f"[warning] {warning}")
    findings = lint_string(svg, measurer=m)
    if args.check and has_errors(findings):
        for f in findings:
            print(str(f))
        print("nanoframes: refusing to write a composition with lint errors", file=sys.stderr)
        return 1
    print(f"wrote {out} ({scene.width:g}x{scene.height:g},"
          f" {len(scene.groups)} groups, duration {scene.duration:g}s)")
    if not scene.warnings:
        print("  no spec warnings (budget, grid, clipping)")
    dpi = getattr(spec, "dpi", None) or 2
    print(f"  nanoframes render {out} --t 0 -o shot.png"
          f"            # {scene.width:g}x{scene.height:g}")
    print(f"  nanoframes render {out} --t 0 --dpi {dpi:g} -o shot@{dpi:g}x.png"
          f"   # {geo_size(scene.width, dpi):g}x{geo_size(scene.height, dpi):g}")
    if scene.duration > 1.0:
        print(f"  nanoframes video {out} -o out.mp4   # reveal animation")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """Report the cache, clear it, or trim it to its cap.

    The cache is keyed by source content, so every edit to a composition
    orphans its previous frames; they are also always reproducible, which is
    what makes clearing safe rather than destructive. Extracted video frames
    live under the same directory and are reported (and cleared) with it.
    """
    from nanoframes.media import MediaCache

    cache = FrameCache(DEFAULT_CACHE)
    media = MediaCache(DEFAULT_CACHE)
    if args.clear:
        frames, size = cache.stats()
        sequences, media_bytes = media.stats()
        cache.clear()
        print(f"cleared {DEFAULT_CACHE}/ ({frames} frames, {size / 1e6:.0f} MB;"
              f" {sequences} video sequence(s), {media_bytes / 1e6:.0f} MB)")
        return 0
    frames, size = cache.stats()
    cap = cache.max_bytes / 1e6
    ttl = "never" if cache.ttl is None else f"{cache.ttl / 86400:.0f} days"
    print(f"{DEFAULT_CACHE}/: {frames} frames, {size / 1e6:.0f} MB"
          f" of {cap:.0f} MB (entries expire after {ttl})")
    sequences, media_bytes = media.stats()
    if sequences:
        print(f"  media: {sequences} extracted video sequence(s), {media_bytes / 1e6:.0f} MB"
              " (content-keyed; cleared with the cache)")
    if args.trim:
        removed = cache.trim()
        print(f"trimmed {removed} frame(s); now {cache.stats()[1] / 1e6:.0f} MB")
    else:
        print("  nanoframes cache --clear    # delete it; frames re-render on demand")
        print("  nanoframes cache --trim     # evict oldest frames down to the cap")
    cache.close()
    return 0


def geo_size(value: float, dpi: float) -> int:
    """The raster size a dimension renders at for a given ``--dpi``."""
    return max(2, int(round(value * dpi)) // 2 * 2)


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


def _resource_lines() -> list[str]:
    """The docs/skill pointer block, shared by the bare guide and the --help epilog."""
    found = _resource_dirs()
    if not found:
        return ["  (docs/skills not found next to this install)"]
    docs, skills = found
    return [
        f"  composition contract ... {os.path.join(docs, 'composition.md')}",
        f"  architecture ............ {os.path.join(docs, 'architecture.md')}",
        f"  text capabilities ....... {os.path.join(docs, 'text-capabilities.md')}",
        f"  lottie import ........... {os.path.join(docs, 'lottie.md')}",
        f"  diagram spec ............ {os.path.join(docs, 'diagram.md')}",
        f"  agent skill ............. {os.path.join(skills, 'SKILL.md')}",
    ]


def guide_text() -> str:
    """Point users (agents) at the docs and agent skill shipped with the package."""
    lines = [
        "nanoframes — SVG-first, browserless, deterministic frame rendering on ThorVG.",
        "Docs and the agent skill ship with the package; read them before composing:",
        "",
    ]
    lines += _resource_lines()
    lines += ["", "Usage: nanoframes <command> ...    (nanoframes --help for the command list)"]
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
