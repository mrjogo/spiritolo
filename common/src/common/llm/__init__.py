"""Shared LLM provider Protocol + implementations."""

from .batch_provider import (
    BatchProvider, BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from .batch_runner import BatchSubmitOutcome, ingest_batch, submit_batch
from .claude import ClaudeProvider
from .deepseek import build_deepseek_provider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openai_batch import OpenAIBatchProvider
from .provider import LLMProvider, ProviderResult
from .sidecar import Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar

__all__ = [
    "BatchProvider", "BatchRequest", "BatchResult", "BatchStatus",
    "BatchSubmission", "BatchSubmitOutcome",
    "ClaudeProvider", "LLMProvider", "OllamaProvider", "OpenAIProvider",
    "OpenAIBatchProvider", "build_deepseek_provider",
    "ProviderResult",
    "Sidecar", "SidecarMismatch", "load_sidecar", "mark_ingested", "write_sidecar",
    "ingest_batch", "submit_batch",
]
