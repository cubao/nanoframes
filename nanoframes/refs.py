"""Where a composition's external references live, in one place.

Two passes need the same lists: ``bake`` dereferences local ``<image>`` hrefs so
ThorVG can resolve them, and ``lint`` warns about assets that are not there.
They used to carry private copies of the attribute names and the "not local"
scheme list, which drifted apart the moment either changed.
"""

from __future__ import annotations

# Every attribute an ``<image>`` may carry its source in.
IMAGE_REF_ATTRS = ("href", "{http://www.w3.org/1999/xlink}href", "src")

# Schemes a local pass must leave alone (absolute, remote or inlined).
REMOTE_SCHEMES = ("http:", "https:", "data:")
