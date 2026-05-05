"""Shared LLM provider Protocol + implementations."""

from .batch_provider import (
    BatchProvider, BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .provider import LLMProvider, ProviderResult
from .retry import resolve_with_retry
from .sidecar import Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar

__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "ProviderResult", "resolve_with_retry",
    "Sidecar", "SidecarMismatch", "load_sidecar", "mark_ingested", "write_sidecar",
]
