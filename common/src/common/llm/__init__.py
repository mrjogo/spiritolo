"""Shared LLM provider Protocol + implementations.

Sync providers (one prompt, one response): see provider.py.
Batch providers (submit / poll / ingest lifecycle): see batch_provider.py.
"""

from .provider import LLMProvider, ProviderResult

__all__ = ["LLMProvider", "ProviderResult"]
