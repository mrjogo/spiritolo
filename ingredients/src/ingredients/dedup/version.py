"""Version constants for the dedup name-normalization and clustering stages.

Bump NORMALIZER_VERSION when name-normalization rules change (alias
handling, stop-word list, lexical thresholds, prompt). Canonical names feed
the `cluster` and `convert` stages; force them to recompute by deleting
those stages' `stage_runs` rows (or bumping DEDUP_VERSION / CONVERTER_VERSION).

Bump DEDUP_VERSION when role classifier rules change OR cluster/variant
key shape changes OR INCLUDED_ROLES changes OR is_defining_garnish allowlist
changes. Bumping requires re-running the `cluster` stage — delete its
`stage_runs` rows, or the version bump itself re-queues affected recipes.
"""

from __future__ import annotations

NORMALIZER_VERSION = "v1"
DEDUP_VERSION = "v1"
