import io
import json
from unittest.mock import MagicMock

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus
from common.llm.openai_batch import OpenAIBatchProvider


def _stub_openai_client():
    """Return a MagicMock OpenAI client whose files/batches surfaces are
    tracked individually."""
    client = MagicMock()
    return client


def test_submit_uploads_jsonl_then_creates_batch():
    client = _stub_openai_client()
    file_obj = MagicMock(id="file_xyz")
    client.files.create.return_value = file_obj
    batch_obj = MagicMock(id="batch_abc")
    client.batches.create.return_value = batch_obj

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    sub = p.submit([
        BatchRequest(custom_id="r0", system_prompt="s", user_prompt="u0"),
        BatchRequest(custom_id="r1", system_prompt="s", user_prompt="u1"),
    ])
    assert sub.batch_id == "batch_abc"
    assert sub.provider == "openai"
    assert sub.model_id == "gpt-5-mini"
    assert sub.request_count == 2

    # files.create called with a JSONL body containing both requests.
    assert client.files.create.call_count == 1
    call = client.files.create.call_args
    assert call.kwargs["purpose"] == "batch"
    raw = call.kwargs["file"]
    if hasattr(raw, "read"):
        body = raw.read().decode() if isinstance(raw.read(), bytes) else raw.read()
    else:
        body = raw
    lines = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["custom_id"] == "r0"
    assert lines[0]["method"] == "POST"
    assert lines[0]["url"] == "/v1/chat/completions"
    assert lines[0]["body"]["model"] == "gpt-5-mini"
    assert lines[0]["body"]["messages"][0] == {"role": "system", "content": "s"}
    assert lines[0]["body"]["messages"][1] == {"role": "user", "content": "u0"}
    # gpt-5-family token + reasoning settings (see openai_batch.py docstring).
    assert lines[0]["body"]["max_completion_tokens"] == 2048
    assert lines[0]["body"]["reasoning_effort"] == "none"
    assert lines[0]["body"]["response_format"] == {"type": "json_object"}

    # batches.create called with the uploaded file id + 24h window.
    assert client.batches.create.call_count == 1
    bcall = client.batches.create.call_args.kwargs
    assert bcall["input_file_id"] == "file_xyz"
    assert bcall["endpoint"] == "/v1/chat/completions"
    assert bcall["completion_window"] == "24h"


def test_status_maps_openai_response():
    client = _stub_openai_client()
    fake_batch = MagicMock(
        id="batch_abc", status="in_progress",
        request_counts=MagicMock(completed=5, total=10),
    )
    client.batches.retrieve.return_value = fake_batch

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    st = p.status("batch_abc")
    assert st == BatchStatus(batch_id="batch_abc", state="in_progress",
                             completed=5, total=10)


def test_fetch_results_streams_parsed_results():
    client = _stub_openai_client()
    # batches.retrieve returns the completed batch with output_file_id.
    fake_batch = MagicMock(
        id="batch_abc", status="completed",
        output_file_id="file_out", error_file_id=None,
    )
    client.batches.retrieve.return_value = fake_batch

    # files.content returns a binary stream of newline-delimited JSON.
    payload = (
        json.dumps({
            "custom_id": "r0",
            "response": {"status_code": 200, "body": {
                "choices": [{"message": {"content": '{"action":"chose"}'}}]
            }},
            "error": None,
        }) + "\n" +
        json.dumps({
            "custom_id": "r1",
            "response": None,
            "error": {"message": "rate limited"},
        }) + "\n"
    ).encode()
    fake_resp = MagicMock()
    fake_resp.text = payload.decode()
    fake_resp.read.return_value = payload
    client.files.content.return_value = fake_resp

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    results = list(p.fetch_results("batch_abc"))
    assert results == [
        BatchResult(custom_id="r0", raw_text='{"action":"chose"}', error=None),
        BatchResult(custom_id="r1", raw_text=None, error="rate limited"),
    ]


def test_submit_omits_reasoning_effort_for_non_gpt5_models():
    """gpt-4o-mini and older reject reasoning_effort with a 400."""
    client = _stub_openai_client()
    client.files.create.return_value = MagicMock(id="file_x")
    client.batches.create.return_value = MagicMock(id="batch_y")
    p = OpenAIBatchProvider(client=client, model_id="gpt-4o-mini")
    p.submit([BatchRequest(custom_id="r0", system_prompt="s", user_prompt="u")])
    raw = client.files.create.call_args.kwargs["file"]
    body = raw if isinstance(raw, (bytes, str)) else raw.read()
    if isinstance(body, bytes):
        body = body.decode()
    line = json.loads(body.splitlines()[0])
    assert "reasoning_effort" not in line["body"]


def test_fetch_results_strips_nul_bytes_from_content():
    """gpt-5-mini emits NUL bytes in two forms — a literal 0x00 in the JSON
    source, OR more commonly a \\u0000 escape inside a string value that
    decodes to NUL after json.loads. Both must be stripped before downstream
    json.loads + Postgres write, otherwise psycopg.DataError mid-loop."""
    nul = chr(0)
    # Two cases in one batch: literal 0x00 in JSON syntax, AND \u0000 escape
    # inside a string value (the form gpt-5-mini actually emits in practice).
    literal_form = '{"slug":"foo' + nul + 'bar"}'
    escaped_form = r'{"slug":"baz\u0000qux"}'

    client = _stub_openai_client()
    fake_batch = MagicMock(
        id="batch_xyz", status="completed",
        output_file_id="file_out", error_file_id=None,
    )
    client.batches.retrieve.return_value = fake_batch
    payload = (
        json.dumps({
            "custom_id": "r0",
            "response": {"status_code": 200, "body": {
                "choices": [{"message": {"content": literal_form}}]
            }},
            "error": None,
        }) + "\n" +
        json.dumps({
            "custom_id": "r1",
            "response": {"status_code": 200, "body": {
                "choices": [{"message": {"content": escaped_form}}]
            }},
            "error": None,
        }) + "\n"
    ).encode()
    fake_resp = MagicMock()
    fake_resp.text = payload.decode()
    fake_resp.read.return_value = payload
    client.files.content.return_value = fake_resp

    p = OpenAIBatchProvider(client=client, model_id="gpt-5-mini")
    results = list(p.fetch_results("batch_xyz"))
    assert len(results) == 2

    # Both raw_text values are valid JSON with NUL stripped — and crucially,
    # parsing them does NOT yield NUL in any string value either.
    for r in results:
        assert nul not in (r.raw_text or "")
        parsed = json.loads(r.raw_text)
        assert nul not in parsed["slug"]

    # The escaped form was the actual bug; assert it specifically.
    parsed_escaped = json.loads(results[1].raw_text)
    assert parsed_escaped["slug"] == "bazqux"
