"""Shared per-site / per-category summary printer.

Shape (common to every pipeline CLI):

    --- <Title> ---
      <site>:
         1234  <category>
          567  <other-category>
      <other-site>:
           12  <category>
    Total: N (applied|dry-run)

Sites are alphabetical; categories within a site are ordered by descending
count so the biggest bucket is the first thing the eye lands on.
"""

from __future__ import annotations

import sys
from collections import Counter
from typing import TextIO


def print_summary(
    title: str,
    changes: dict[str, Counter],
    *,
    mode: str = "applied",
    out: TextIO | None = None,
) -> None:
    stream = out if out is not None else sys.stdout
    stream.write(f"\n--- {title} ---\n")
    if not changes:
        stream.write("No changes.\n")
        return

    total = 0
    for site in sorted(changes):
        stream.write(f"  {site}:\n")
        for category, count in changes[site].most_common():
            stream.write(f"    {count:6d}  {category}\n")
            total += count
    stream.write(f"Total: {total} ({mode})\n")
