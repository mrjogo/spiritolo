"""Version constant for the dedup clustering stage.

Bump DEDUP_VERSION when role classifier rules change OR cluster/variant
key shape changes OR INCLUDED_ROLES changes OR is_defining_garnish allowlist
changes. Bumping requires re-running the `cluster` stage — delete its
`job_items` rows, or the version bump itself re-queues affected recipes.
"""

from __future__ import annotations

DEDUP_VERSION = "v1"
