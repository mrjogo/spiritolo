"""Text similarity helpers (the pg_trgm replacement)."""

from .trigram import TrigramIndex, similarity, trigrams

__all__ = ["TrigramIndex", "similarity", "trigrams"]
