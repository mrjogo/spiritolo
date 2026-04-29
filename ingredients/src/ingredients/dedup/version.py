"""Version constants for E's pipeline stages.

Bump NORMALIZER_VERSION when name-normalization rules change (alias
handling, stop-word list, lexical thresholds, prompt). Bumping requires
re-running normalize-names --reset --except-version <prior>.

Bump DEDUP_VERSION when role classifier rules change OR cluster/variant
key shape changes OR INCLUDED_ROLES changes OR is_defining_garnish allowlist
changes. Bumping requires re-running cluster --reset --except-version <prior>.
"""

from __future__ import annotations

NORMALIZER_VERSION = "v1"
DEDUP_VERSION = "v1"
