"""The Protocol itself has no behavior — these tests pin the dataclass shapes
so downstream code can rely on them. Behavior tests live in
test_batch_openai.py and test_batch_runner.py."""

from common.llm.batch_provider import (
    BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)


def test_batch_request_is_frozen():
    r = BatchRequest(custom_id="r0", system_prompt="s", user_prompt="u")
    try:
        r.custom_id = "r1"
    except Exception:
        return
    assert False, "BatchRequest should be frozen"


def test_batch_submission_carries_provider_and_count():
    s = BatchSubmission(
        batch_id="batch_abc", provider="openai",
        model_id="gpt-5-mini", request_count=42,
    )
    assert s.batch_id == "batch_abc"
    assert s.provider == "openai"
    assert s.model_id == "gpt-5-mini"
    assert s.request_count == 42


def test_batch_status_carries_progress_counts():
    st = BatchStatus(batch_id="b", state="in_progress", completed=10, total=42)
    assert st.state == "in_progress"
    assert st.completed == 10
    assert st.total == 42


def test_batch_result_can_carry_either_text_or_error():
    ok = BatchResult(custom_id="r0", raw_text="hi", error=None)
    err = BatchResult(custom_id="r1", raw_text=None, error="timeout")
    assert ok.raw_text == "hi" and ok.error is None
    assert err.raw_text is None and err.error == "timeout"
