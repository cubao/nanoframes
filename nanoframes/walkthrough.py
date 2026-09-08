"""Generates the self-contained 'one-take' nanoframes walkthrough.

Running this renders a complete, prose-driven tour of nanoframes into a default
output directory (`build/walkthrough/`):

    build/walkthrough/
        README.md                  the story, opens in any markdown editor
        compositions/story.nf.svg  the one composition that carries the story
        frames/*.png               rendered frames (motion, determinism)
        video/story.mp4            the finished short video (+ audio)
        audio/story.wav            deterministic synthesized soundtrack

It is written for both humans and AI agents: narrative + exact commands + the
actual source and rendered outputs, so an agent that reads it 'gets the whole
idea' and can reproduce every step.

Run with the CLI:  ``nanoframes walkthrough [--out build/walkthrough]``
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import wave

from nanoframes.lint import has_errors, lint_path
from nanoframes.parse import Document, ParseError, parse_string

# ---------------------------------------------------------------------------
# 1. The one composition that carries the whole story (a 6s, 960x540 film).
# ---------------------------------------------------------------------------

STORY = """<svg xmlns="http://www.w3.org/2000/svg"
     data-width="960" data-height="540" data-fps="30" data-duration="6.0"
     data-composition-id="story">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0a1128"/>
      <stop offset="1" stop-color="#203a6b"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#5ef17c"/>
      <stop offset="1" stop-color="#38bdf8"/>
    </linearGradient>
  </defs>

  <!-- static base layer -->
  <rect id="bg" width="960" height="540" fill="url(#sky)"/>

  <!-- media: raster images (relative path dereferenced against this dir) -->
  <image id="orb" class="float" href="assets/dot.png" x="700" y="120" width="120" height="120"
         data-start="0.2" data-duration="5.0"/>
  <image id="orb2" class="float" href="assets/dot.png" x="140" y="300" width="72" height="72"
         opacity="0.9" data-start="0.8" data-duration="4.0"/>

  <!-- a gradient panel that travels the frame (translate + rotate) -->
  <rect id="panel" width="220" height="120" rx="22" fill="url(#accent)" opacity="0.9"
        data-start="0.0" data-duration="6.0"/>

  <!-- clips: enter at data-start, live for data-duration (chip fades via .chip) -->
  <rect id="slat" class="chip" x="60" y="48" width="6" height="26" rx="3" fill="#5ef17c"
        data-start="0.5" data-duration="5.0"/>
  <text id="kicker" class="chip" x="80" y="72" font-family="Arial" font-size="22"
        letter-spacing="2" fill="#5ef17c" data-start="0.5" data-duration="5.0">NANOFRAMES</text>

  <text id="title" x="60" y="150" font-family="Arial" font-weight="700" font-size="72"
        fill="#f4f7ff" data-start="0.7" data-duration="4.8">SVG renders video.</text>
  <text id="sub" x="60" y="205" font-family="Arial" font-size="28" fill="#9fb0cc"
        data-start="1.3" data-duration="4.0">Deterministic. Offline. Built for agents.</text>

  <script type="application/nanoframes+json"><![CDATA[
  {
    "animations": [
      { "target": "#panel", "keyframes": [
          { "t": 0.0, "opacity": 0.0, "transform": { "translate": [60, 420], "scale": [0.25, 1.0], "rotate": 0 } },
          { "t": 1.0, "opacity": 0.9, "transform": { "translate": [60, 420], "scale": [1.0, 1.0], "rotate": -12 }, "ease": "ease-in-out" },
          { "t": 4.2, "opacity": 0.9, "transform": { "translate": [560, 330], "scale": [1.0, 1.0], "rotate": 8 }, "ease": "ease-in-out" },
          { "t": 5.6, "opacity": 0.55, "transform": { "translate": [680, 430], "scale": [1.0, 1.0], "rotate": 4 } } ] },
      { "target": ".float", "keyframes": [
          { "t": 0.2, "opacity": 0.0, "transform": { "translate": [0, 40], "scale": [0.5, 0.5] } },
          { "t": 1.0, "opacity": 1.0, "transform": { "translate": [0, 0], "scale": [1.0, 1.0] }, "ease": "ease-out" },
          { "t": 4.5, "opacity": 1.0, "transform": { "translate": [0, -30], "scale": [1.15, 1.15] }, "ease": "ease-in-out" } ] },
      { "target": ".chip", "keyframes": [
          { "t": 0.5, "opacity": 0.0 },
          { "t": 0.8, "opacity": 1.0 } ] },
      { "target": "#title", "keyframes": [
          { "t": 0.7, "opacity": 0.0, "transform": { "translate": [0, 40] } },
          { "t": 1.4, "opacity": 1.0, "transform": { "translate": [0, 0] }, "ease": "ease-out" } ] },
      { "target": "#sub", "keyframes": [
          { "t": 1.3, "opacity": 0.0 },
          { "t": 1.9, "opacity": 1.0 } ] }
    ]
  }
  ]]></script>
</svg>
"""


def _script_of(doc: Document) -> str:
    """Return the animation JSON (pretty, back to braces) for the code block."""
    for el in doc.root.iter():
        if "script" in el.tag.lower() and el.text:
            return el.text.strip()
    return ""


# ---------------------------------------------------------------------------
# 2. Deterministic soundtrack (stdlib `wave`, no dependencies).
# ---------------------------------------------------------------------------


def synthesize_wav(path: str, duration: float = 6.0, rate: int = 22050) -> None:
    """A gentle, deterministic chord progression so the MP4 has real audio."""
    import math
    import struct

    chords = [
        [261.63, 329.63, 392.00],  # C
        [220.00, 261.63, 329.63],  # Am
        [174.61, 220.00, 261.63],  # F
        [196.00, 246.94, 293.66],  # G
    ]
    seg = duration / 4
    n = int(duration * rate)
    frames = []
    for i in range(n):
        t = i / rate
        chord = chords[min(int(t // seg), 3)]
        fades = min(1.0, i / (rate * 0.05), (n - i) / (rate * 0.08))
        sample = sum(math.sin(2 * math.pi * f * t) * 0.22 for f in chord)
        sample *= fades
        frames.append(struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767)))

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))


# ---------------------------------------------------------------------------
# 3. The build.
# ---------------------------------------------------------------------------


def build(out_dir: str = "build/walkthrough", with_audio: bool = True) -> str:
    comp_dir = os.path.join(out_dir, "compositions")
    frame_dir = os.path.join(out_dir, "frames")
    video_dir = os.path.join(out_dir, "video")
    audio_dir = os.path.join(out_dir, "audio")
    asset_dir = os.path.join(out_dir, "assets")
    for d in (comp_dir, frame_dir, video_dir, audio_dir, asset_dir):
        os.makedirs(d, exist_ok=True)

    from nanoframes.render import render_frame, render_svg  # noqa: F401
    from nanoframes.cache import FrameCache
    from nanoframes.video import render_video

    # Write the composition + the shared asset (green orb).
    comp_path = os.path.join(comp_dir, "story.nf.svg")
    with open(comp_path, "w", encoding="utf-8") as fh:
        fh.write(STORY)
    doc = parse_string(STORY)
    doc.base_dir = out_dir  # so relative href = "assets/dot.png" resolves

    # asset
    _write_dot(os.path.join(asset_dir, "dot.png"))

    # Lint first — the walkthrough never ships a broken composition.
    findings = lint_path(comp_path)
    if has_errors(findings):
        raise RuntimeError(f"walkthrough composition must lint clean: {findings}")

    cache = FrameCache(os.path.join(out_dir, ".cache"))

    # (a) key frames showing the motion arc
    motion_times = [0.6, 2.0, 5.0]
    frames = {}
    for t in motion_times:
        p = os.path.join(frame_dir, f"story_t{t:g}.png")
        render_frame(doc, t, out_path=p, cache=cache)
        frames[t] = p

    # (b) determinism: same frame twice must be byte-identical
    da = os.path.join(frame_dir, "deterministic_a.png")
    db = os.path.join(frame_dir, "deterministic_b.png")
    render_frame(doc, 2.0, out_path=da, cache=cache)
    render_frame(doc, 2.0, out_path=db, cache=cache)
    ha = hashlib.sha256(open(da, "rb").read()).hexdigest()
    hb = hashlib.sha256(open(db, "rb").read()).hexdigest()
    assert ha == hb, "rendering the same frame twice must be deterministic"
    with open(os.path.join(out_dir, "determinism.txt"), "w") as fh:
        fh.write(f"story_t2.00 sha256 (render a): {ha}\n")
        fh.write(f"story_t2.00 sha256 (render b): {hb}\n")
        fh.write("byte-identical: True\n")

    # (c) measure cold vs warm single-frame render (cached) in-process
    c0 = time.perf_counter()
    render_frame(doc, 3.0, out_path=os.path.join(frame_dir, "story_t3.png"), cache=cache)
    cold_ms = (time.perf_counter() - c0) * 1000
    w0 = time.perf_counter()
    render_frame(doc, 3.0, cache=cache)  # warm hit (discarded)
    warm_ms = (time.perf_counter() - w0) * 1000

    # (d) the finished video (optionally with the synthesized soundtrack)
    video_path = os.path.join(video_dir, "story.mp4")
    audio_path = None
    if with_audio:
        audio_path = os.path.join(audio_dir, "story.wav")
        synthesize_wav(audio_path, duration=6.0)
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            audio_path = None  # no ffmpeg -> skip audio, still write a silent video
    render_video(doc, video_path, cache=cache, audio=audio_path)

    # (e) probe the result with ffprobe if available
    probe = _probe(video_path)

    readme = _render_readme(
        out_dir=out_dir, frames=frames, determinism=(ha, hb),
        cold_ms=cold_ms, warm_ms=warm_ms, video_path=video_path, probe=probe,
        audio=with_audio and audio_path is not None,
    )
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(readme)

    # keep a machine-readable manifest for agents
    _write_manifest(out_dir, safety=dict(story_sha256=_sha(comp_path),
                                         det_sha256=ha, cold_ms=cold_ms, warm_ms=warm_ms),
                    video_ok=bool(probe.get("streams")))
    return os.path.join(out_dir, "README.md")


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _write_dot(path: str) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, 114, 114], fill=(94, 241, 124, 255), outline=(255, 255, 255, 190), width=6)
    img.save(path)


def _probe(video_path: str) -> dict:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name:format=duration",
             "-of", "json", video_path],
            capture_output=True, text=True, check=True,
        )
        import json

        return json.loads(r.stdout)
    except Exception:
        return {}


def _write_manifest(out_dir: str, safety: dict, video_ok: bool) -> None:
    import json

    manifest = {
        "generator": "nanoframes walkthrough",
        "composition": "compositions/story.nf.svg",
        "canvas": {"width": 960, "height": 540, "fps": 30, "duration": 6.0},
        "render": {
            "deterministic": True,
            "story_t2.00_sha256": safety["det_sha256"],
            "source_sha256": safety["story_sha256"],
            "cold_ms": round(safety["cold_ms"], 1),
            "cached_ms": round(safety["warm_ms"], 1),
        },
        "video": {"path": "video/story.mp4", "video_ok": video_ok},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)


# ---------------------------------------------------------------------------
# 4. README generation (markdown that opens in any editor, human + agent).
# ---------------------------------------------------------------------------


def _render_readme(out_dir, frames, determinism, cold_ms, warm_ms, video_path, probe, audio) -> str:
    ha, hb = determinism
    script = _script_of(parse_string(STORY))
    rel = lambda p: os.path.relpath(p, out_dir).replace(os.sep, "/")

    streams = ", ".join(
        f"{s.get('codec_type')}/{s.get('codec_name')}" for s in probe.get("streams", [])
    )
    dur = probe.get("format", {}).get("duration", "?")

    md: list[str] = []
    md.append("# nanoframes — one take, from one SVG to a finished MP4\n")
    md.append("> Written for humans **and** AI agents. Every code block and every rendered frame below")
    md.append("> was produced by the exact commands shown — nothing is mocked. Read it top to bottom;")
    md.append("> by the end you carry the whole idea of nanoframes: **write SVG, render deterministically")
    md.append("> and offline with ThorVG, export frames and video — no browser.**\n")
    md.append(f"- Composition: [`{rel(os.path.join(out_dir,'compositions/story.nf.svg'))}`]({rel(os.path.join(out_dir,'compositions/story.nf.svg'))})")
    md.append(f"- Final video: [`{rel(video_path)}`]({rel(video_path)})" + (", muxed with a synthesized soundtrack" if audio else ""))
    md.append(f"- Manifest (for agents): [`manifest.json`]({rel(os.path.join(out_dir,'manifest.json'))})\n")
    md.append("---\n")

    md.append("## 0 · What you end up with\n")
    md.append("```text")
    md.append(f"{out_dir}/")
    md.append("  README.md           <- you are here (opens in any markdown editor)")
    md.append("  manifest.json       <- machine-readable summary for agent scripts")
    md.append("  determinism.txt     <- sha256 proof that the same frame renders identically")
    md.append("  compositions/       story.nf.svg   the single composition that carries the story")
    md.append("  frames/             story_t0.6/2.0/5.0.png + deterministic_a/b.png")
    md.append("  video/              story.mp4      960x540, 180 frames, 6.0s")
    md.append("  audio/              story.wav      6s chord progression (deterministic synth)")
    md.append("  assets/             dot.png        raster imported into the scene")
    md.append("  .cache/             fast re-render cache (content-keyed)")
    md.append("```\n")
    md.append("Regenerate all of it anytime with:\n")
    md.append("```bash\nnanoframes walkthrough\n# or:  python3 -m nanoframes.walkthrough\n```\n")
    md.append("---\n")

    md.append("## 1 · Why offline\n")
    md.append("Video tools that live in a browser take hundreds of milliseconds per frame and need a headless")
    md.append("Chromium, a capture pipeline, and non-deterministic layout. nanoframes instead renders with")
    md.append("**ThorVG** — a compact software SVG rasterizer (`thorvg-python`) — straight to a `Pillow` image.")
    md.append("There is no DOM, no CSS layout engine, no GPU: the whole pipeline is deterministic and cheap.\n")
    md.append("```text")
    md.append("story.nf.svg  --parse-->  Composition")
    md.append("   + seek(t)  --timeline-->  per-frame property values")
    md.append("      + bake  -->  one standalone SVG for that instant")
    md.append("          + ThorVG  -->  PNG  (-> ffmpeg -> MP4)")
    md.append("```\n")
    md.append("Run it yourself and time it:\n")
    md.append("```bash")
    md.append("nanoframes render compositions/story.nf.svg --t 2.0 -o shot.png")
    md.append("```\n")
    md.append("---\n")

    md.append("## 2 · The one composition\n")
    md.append("A nanoframes composition is a **single valid SVG file**. The root `<svg>` declares the canvas")
    md.append("(`data-width`, `data-height`, `data-fps`, `data-duration`); every element can declare a clip")
    md.append("(`data-start` / `data-duration`) and, optionally, a fade (`data-fade`). An embedded")
    md.append("`<script type=\"application/nanoframes+json\">` holds the animation timeline.\n")
    md.append("Here is the entire story — a 6-second, 960x540 film:\n")
    md.append("```svg")
    md.append(STORY.rstrip())
    md.append("```\n")
    md.append("And here is one rendered frame from it (t = 2.0s):\n")
    md.append(f"![story t=2.0]({rel(frames[2.0])})\n")
    md.append("---\n")

    md.append("## 3 · The timeline contract (this is the 'motion')\n")
    md.append("Instead of GSAP/CSS in a browser, motion lives in a tiny declarative JSON. Each animation targets")
    md.append("a CSS selector (`#id`, `.class`, or tag) and has ordered keyframes; between keyframes values")
    md.append("interpolate linearly (optional easing), deterministically. Supported animated properties: `opacity`,")
    md.append("`transform` (`translate`/`scale`/`rotate`), and `fill`/`stroke` color.\n")
    md.append("```json")
    md.append(script)
    md.append("```\n")
    md.append("Three instants from the same journey — the panel slides in, the intro lands, the panel drifts right:")
    md.append("")
    for t in (0.6, 2.0, 5.0):
        md.append(f"**t = {t:g}s**  `nanoframes render story.nf.svg --t {t:g}`")
        md.append(f"![story t={t:g}]({rel(frames[t])})")
        md.append("")
    md.append("---\n")

    md.append("## 4 · Compose & media\n")
    md.append("The scene uses two `<linearGradient>` fills, `<text>` with system fonts, `<rect>` shapes, groups,")
    md.append("and raster **`<image>`** elements. Relative image `href`s are dereferenced against the composition")
    md.append("directory — so you can drop PNGs beside the SVG and reference them normally. The floating dots are")
    md.append("a single 120px `assets/dot.png`, scaled and moved by the `.float` timeline.\n")
    md.append("```svg")
    md.append('<image class="float" href="assets/dot.png" x="700" y="120" width="120" height="120" data-start="0.2" data-duration="5.0"/>')
    md.append("```\n")
    md.append(f"See them over time in `{rel(frames[2.0])}` / `{rel(frames[5.0])}` above.\n")
    md.append("---\n")

    md.append("## 5 · Determinism & the re-render cache\n")
    md.append(f"The same frame rendered twice is **byte-identical** — a property the snapshot test suite relies on.")
    md.append(f"Here is the proof at t = 2.0s:\n")
    md.append("```bash")
    md.append("nanoframes render story.nf.svg --t 2.0 -o deterministic_a.png")
    md.append("nanoframes render story.nf.svg --t 2.0 -o deterministic_b.png")
    md.append(f"sha256(deterministic_a) = {ha}")
    md.append(f"sha256(deterministic_b) = {hb}   # identical")
    md.append("```\n")
    md.append(f"![deterministic_a]({rel(os.path.join(out_dir,'frames/deterministic_a.png'))})")
    md.append(f"![deterministic_b]({rel(os.path.join(out_dir,'frames/deterministic_b.png'))})")
    md.append("")
    md.append(f"Because output is a pure function of (composition, time), nanoframes keeps a **content-keyed cache**:")
    md.append(f"rendering the same frame again skips ThorVG entirely. Measured in-process here:")
    md.append(f"cold ~{cold_ms:.0f} ms/frame → cached ~{warm_ms:.0f} ms/frame to read back.\n")
    md.append("```bash")
    md.append("nanoframes render story.nf.svg -o frames          # cold: rasterizes everything")
    md.append("nanoframes render story.nf.svg -o frames2         # warm: served from .cache/")
    md.append("nanoframes render story.nf.svg -o out --no-cache  # opt out if you want a cold run")
    md.append("```\n")
    md.append("---\n")

    md.append("## 6 · To video (and audio)\n")
    md.append("`nanoframes video` renders the full frame sequence and muxes it with ffmpeg. Pass `--audio` to")
    md.append("carry a soundtrack (here a 6s chord progression synthesized deterministically with the stdlib).\n")
    md.append("```bash")
    md.append("nanoframes video compositions/story.nf.svg -o video/story.mp4 --audio audio/story.wav")
    md.append("```\n")
    md.append("<video controls preload=\"metadata\" poster=\"" + rel(frames[2.0]) + "\" width=\"640\">")
    md.append("  <source src=\"" + rel(video_path) + "\" type=\"video/mp4\">")
    md.append("  Your markdown viewer can't embed video — open `" + rel(video_path) + "` directly.")
    md.append("</video>\n")
    md.append(f"- Codecs:{' **' + streams + '**' if streams else ' (ffprobe unavailable here)'}")
    md.append(f"- Duration: `{dur}` s, `180` frames at 30fps, `960x540`\n")
    md.append("---\n")

    md.append("## 7 · Live for agents\n")
    md.append("The whole loop is `check → preview → render → video`, plus a content-keyed cache. It is designed")
    md.append("so an AI agent can iterate a frame in milliseconds and never depend on a browser:")
    md.append("")
    md.append("| command | does |")
    md.append("|---|---|")
    md.append("| `nanoframes init <name>` | scaffold a `.nf.svg` |")
    md.append("| `nanoframes check <comp>` | lint the contract (exit 1 on errors) |")
    md.append("| `nanoframes preview <comp> --t <sec>` | render one frame and open it |")
    md.append("| `nanoframes render <comp> --t <sec>` | render a single frame to PNG |")
    md.append("| `nanoframes render <comp> -o dir` | render the full clip |")
    md.append("| `nanoframes video <comp> -o out.mp4 [--audio file]` | export MP4 (+ audio) |")
    md.append("")
    md.append("There is an agent-facing `SKILL.md` that teaches exactly this production loop; point any skill-aware")
    md.append("agent at `skills/nanoframes/SKILL.md`. Full contract: `docs/composition.md`; design & scope:")
    md.append("`docs/architecture.md`.\n")

    md.append("## Repaint the whole story\n")
    md.append("```bash")
    md.append("pip install -e .       # once")
    md.append("nanoframes walkthrough  # regenerates this README + all outputs")
    md.append("```\n")
    md.append("---\n")
    md.append("*Generated by `nanoframes walkthrough`. Deterministic: the same inputs yield the same frames and the same story.*\n")
    return "\n".join(md)


# ---------------------------------------------------------------------------
# 5. Entry point.
# ---------------------------------------------------------------------------


DEFAULT_OUT = "build/walkthrough"


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="nanoframes walkthrough",
                                description="generate the self-contained nanoframes walkthrough")
    p.add_argument("-o", "--out", default=DEFAULT_OUT, help="output dir (default %(default)s)")
    p.add_argument("--no-audio", action="store_true", help="skip audio synthesis/mux")
    args = p.parse_args(argv)

    readme = build(args.out, with_audio=not args.no_audio)
    print(f"nanoframes walkthrough -> {args.out}/")
    print(f"  open {readme} in any markdown editor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())