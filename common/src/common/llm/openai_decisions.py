"""OpenAI Decisions API provider (``POST /v1/decisions``, gpt-6-luna only).

The Decisions API answers a fixed question about an input instead of
generating text: a *choice* question returns the chosen value plus a
probability for every option, which is exactly what a URL classifier wants
(a label and a confidence to sort uncertain pages by). Output is free; input
is billed at the uncached luna rate.

This provider keeps the ``LLMProvider`` contract so ``scraper.classify`` can
drive it unchanged: ``response_schema`` must carry one enum property (the
classifier's ``label``), whose values become the question's ``choices``;
``system_prompt`` becomes the question's ``instructions`` and ``user_prompt``
the ``input``. The reply is re-serialized as JSON text of the form
``{"label": <choice>, "confidence": <float>, "probabilities": {<value>: p}}``
so the flow's existing ``json.loads`` + enum check still applies, and the
caller may read ``confidence`` when it wants to store it.

The installed openai SDK (2.x) predates the ``client.decisions`` resource, so
the request goes through the SDK's generic ``client.post`` — same auth, base
URL, retries and proxy as every other OpenAI call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .provider import ProviderResult

DEFAULT_MODEL = "gpt-6-luna"
DECISIONS_PATH = "/decisions"


class DecisionsRefused(ValueError):
    """The model answered the question with a refusal; there is no label."""


def choices_from_schema(response_schema: dict | None) -> tuple[str, list[str]]:
    """``(property_name, enum_values)`` of the single enum property the
    schema declares. A choice question needs 2..255 values."""
    if not response_schema:
        raise ValueError("Decisions provider needs a response_schema with one enum property")
    props = response_schema.get("properties") or {}
    enums = {k: v.get("enum") for k, v in props.items() if isinstance(v, dict) and v.get("enum")}
    if len(enums) != 1:
        raise ValueError(
            f"Decisions provider needs exactly one enum property, got {sorted(enums)}"
        )
    (name, values), = enums.items()
    values = [str(v) for v in values]
    if not 2 <= len(values) <= 255:
        raise ValueError(f"choice question needs 2..255 choices, got {len(values)}")
    return name, values


def build_decisions_request(
    *, model: str, instructions: str, user_input: str,
    choices: list[str], question_name: str,
) -> dict:
    """The ``/decisions`` request body for one choice question."""
    return {
        "model": model,
        "input": user_input,
        "questions": [
            {
                "type": "choice",
                "name": question_name,
                "instructions": instructions,
                "choices": [{"value": v} for v in choices],
            }
        ],
    }


def parse_decisions_response(payload: dict, *, question_name: str) -> dict:
    """``{"<question_name>": choice, "confidence": float, "probabilities": {...}}``
    from a ``/decisions`` reply. Raises ``DecisionsRefused`` on a refusal
    answer and ``ValueError`` on anything else that is not a choice answer."""
    answers = payload.get("answers") or []
    if len(answers) != 1:
        raise ValueError(f"expected one answer, got {len(answers)}: {payload!r}")
    answer = answers[0]
    kind = answer.get("type")
    if kind == "refusal":
        raise DecisionsRefused(f"model refused the question: {payload!r}")
    if kind != "choice":
        raise ValueError(f"expected a choice answer, got {kind!r}: {payload!r}")
    probabilities = {
        str(p["value"]): float(p["probability"])
        for p in answer.get("probabilities") or []
    }
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    if confidence is None and choice is not None:
        confidence = probabilities.get(str(choice))
    return {
        question_name: choice,
        "confidence": float(confidence) if confidence is not None else None,
        "probabilities": probabilities,
    }


@dataclass
class DecisionsProvider:
    client: object               # openai.OpenAI; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    # Set by the last ``resolve`` from the reply's ``usage`` block, for cost reporting.
    last_usage: dict | None = None

    @classmethod
    def from_env(
        cls, *, model_id: str = DEFAULT_MODEL, api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> "DecisionsProvider":
        import openai
        key = api_key or os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(
                f"{api_key_env} not set. Add it to .env or export before using "
                "this provider."
            )
        return cls(client=openai.OpenAI(api_key=key), model_id=model_id)

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
        response_schema: dict | None = None,
    ) -> ProviderResult:
        question_name, choices = choices_from_schema(response_schema)
        body = build_decisions_request(
            model=self.model_id, instructions=system_prompt, user_input=user_prompt,
            choices=choices, question_name=question_name,
        )
        # cast_to=str hands back the raw response text; the SDK has no
        # Decisions model at this version to parse into.
        text = self.client.post(DECISIONS_PATH, cast_to=str, body=body)
        payload = json.loads(text)
        self.last_usage = payload.get("usage")
        result = parse_decisions_response(payload, question_name=question_name)
        return ProviderResult(raw_text=json.dumps(result), model_id=self.model_id)
