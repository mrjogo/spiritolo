# LLM prompting audit — URL classifier and the provider request shapes

Checked 2026-10-31 against each vendor's own guidance: Anthropic's *Prompting best
practices*, *Prompting Claude Haiku 5.5* and *Structured outputs*; OpenAI's *Using GPT-6*,
*Decisions* and *Structured model outputs*; DeepSeek's *JSON Output*, *Thinking Mode* and
*Parameter Settings*; the Qwen3.5-9B model card. What we send is in
`common/src/common/llm/{claude,openai,deepseek,openai_decisions,local}.py`; the prompt is
`scraper/src/scraper/classify_prompt.py` (v8).

## Already compliant (unchanged)

| Vendor | Guidance | Us |
|---|---|---|
| Anthropic | No `temperature`/`top_p`/`top_k`; no assistant prefill; select content blocks by `type` | Yes (text block read skips thinking blocks) |
| Anthropic | Thinking off only at effort ≤ high; effort is the control | `thinking: disabled` + `effort: low` on `claude-haiku-5*` |
| Anthropic | Cache the stable system prompt (Haiku 5.5 minimum 512 tokens) | System prompt (~2.7k tokens) carries `cache_control` |
| Anthropic | Structured outputs: `required` + `additionalProperties: false`, enum of strings | Yes |
| OpenAI | gpt-6-luna supports `reasoning_effort: none`; drop sampling params when reasoning is on | `none` sent; no sampling params |
| OpenAI | Structured Outputs `strict: true`, stable prefix first for caching | Yes |
| DeepSeek | Thinking off via `extra_body={"thinking": {"type": "disabled"}}`; JSON mode needs the word "json" and a sane `max_tokens` | Yes; `max_completion_tokens` 2048 |
| DeepSeek | `top_p` is fixed at 1.0 in non-thinking mode; temperature default 1.0 (their table: 1.0 for data analysis) | Nothing sent, defaults apply |
| Qwen3.5 | Non-thinking general-task sampling: temperature 0.7, top_p 0.8, top_k 20, min_p 0, presence 1.5, repetition 1.0 | Exactly the `qwen3.5-9b` profile (LM Studio ignores presence_penalty) |
| Qwen3.5 | Standardize multiple-choice output with a JSON field in the prompt | JSON schema + prompt instruction |

## Changed in v8

- **Role sentence** (Anthropic: "Give Claude a role"). The prompt now opens with who the
  model is and why the label matters.
- **XML-tagged sections** (Anthropic: wrap each content type in its own tag; wrap each
  example in `<example>`). `<categories>`, `<rules>`, `<examples>` / `<example>`.
- **Positive phrasing** where it was cheap (Anthropic: "tell Claude what to do instead of
  what not to do"): "editorial other than a single recipe", "give them the article label".
- **Concrete JSON example** in the answer instruction (DeepSeek: "provide an example of the
  desired JSON format").
- **Fallback for inputs with no signal** (OpenAI structured outputs: say what to return
  when the input can't produce a valid answer): a homepage or opaque id with no
  categorizing path is `likely_junk`.
- **Schema `description` on `label`** (OpenAI: "create clear titles and descriptions for
  important keys").
- **Case-insensitive label match** in `classify_client` (Anthropic: enum capitalization is
  not guaranteed).
- **Decisions request reshaped** (OpenAI Decisions guide): the system prompt moves from
  the question's `instructions` into `input` as a developer message, so it sits in the
  cacheable prefix (question text never caches, and the prefix must be ≥1024 tokens);
  the question is one sentence; every choice carries a `description` from
  `LABEL_DESCRIPTIONS`, the same text the prompt's `<categories>` block renders.
- **Blank-content retry for JSON-mode endpoints** (DeepSeek: unreadable output is returned
  as spaces with `finish_reason: stop`; "handle blank content, e.g. retry").
- **`--thinking adaptive` on the Claude provider** (Anthropic Haiku 5.5 guide: "compare two
  or three effort levels on your own evals"; adaptive thinking "reliably drives better
  performance" in their tests). Default stays `disabled`; adaptive runs at low effort with
  `max_tokens` raised to 8192 because thinking counts toward it.

## Deliberately not changed

- **Example count.** Anthropic suggests 3–5 diverse examples; we keep 25 because each is a
  failure mode a model has shown. Watch for the model over-fitting to them; prune if a
  later eval shows it.
- **No "other" choice in Decisions.** Community advice, not OpenAI's; our label set already
  has `likely_junk` as the catch-all, and the choices must equal the schema enum.
- **DeepSeek temperature.** Their table has no classification row (1.0 for data analysis,
  0.0 for coding/math). Left at the default; an eval at 0.0 is a one-line experiment.
- **Qwen thinking switch.** The card's `chat_template_kwargs.enable_thinking: false` is a
  vLLM/SGLang knob LM Studio ignores; `reasoning_effort: none` is what works there
  (verified on barbot 2026-10-30).
- **GPT-6 prompting section.** Written for gpt-6-astra's agentic behaviours (initiative,
  delegation, verification); none applies to a one-shot classifier.
