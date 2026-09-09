"""python -m nanoframes — same entry point as the ``nanoframes`` console script.

Running with no arguments prints where the docs and the agent skill live
(see ``nanoframes.cli.guide_text``).
"""

from nanoframes.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
