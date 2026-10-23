import threading
import time

from conftest import seed_recipe
from spiritolo.db import Database
from spiritolo.executor import Executor, available_providers

from ingredients import runs as R


def test_available_providers_follow_env_keys():
    assert available_providers({}) == ["ollama"]
    assert available_providers({"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}) == ["ollama", "openai", "claude", "anthropic"]


def _queued_run(db, conn, n=2):
    ids = [seed_recipe(conn, f"R{i}", url=f"https://x/{i}") for i in range(n)]
    job_id = R.create_run(conn, "parse-ingredients")
    R.add_run_items(conn, job_id, "recipe", ids)
    R.start_run(conn, job_id)
    return job_id


def test_executor_thread_runs_queued_jobs_on_wake(tmp_path):
    db = Database(str(tmp_path / "e.db"))
    conn = db.new_connection(actor=("system", None, "test"))
    done = threading.Event()

    def fake(job, c, providers):
        c.execute("update job_items set state = 'applied', outcome = 'resolved' where job_id = ?", (job["id"],))
        done.set()
        return {"ok": 1}

    ex = Executor(db, poll_seconds=60, run_kwargs={"stage_fns": {"parse-ingredients": fake}})
    ex.start()
    try:
        job_id = _queued_run(db, conn)
        ex.wake()
        assert done.wait(10)
        for _ in range(100):
            if conn.execute("select state from jobs where id = ?", (job_id,)).fetchone()[0] == "done":
                break
            time.sleep(0.05)
        row = conn.execute("select state, progress, worker_id from jobs where id = ?", (job_id,)).fetchone()
        assert row["state"] == "done" and row["progress"] == {"ok": 1} and row["worker_id"].startswith("executor:")
        health = ex.health()
        assert health["alive"] and health["jobs_run"] == 1 and health["current_job_id"] is None
    finally:
        ex.stop()
        conn.close()
    assert not ex.alive


def test_executor_cancel_trips_running_job(tmp_path):
    db = Database(str(tmp_path / "e.db"))
    conn = db.new_connection(actor=("system", None, "test"))
    started = threading.Event()

    def slow(job, c, providers):
        started.set()
        for _ in range(200):
            if job["should_stop"]():
                return {}
            time.sleep(0.02)
        raise AssertionError("never cancelled")

    ex = Executor(db, poll_seconds=60, run_kwargs={"stage_fns": {"parse-ingredients": slow}})
    ex.start()
    try:
        job_id = _queued_run(db, conn)
        ex.wake()
        assert started.wait(10)
        assert R.cancel_run(conn, job_id) == "cancelling"
        assert ex.cancel(job_id) is True
        for _ in range(100):
            if conn.execute("select state from jobs where id = ?", (job_id,)).fetchone()[0] == "cancelled":
                break
            time.sleep(0.05)
        assert conn.execute("select state from jobs where id = ?", (job_id,)).fetchone()[0] == "cancelled"
        assert ex.cancel(job_id) is False
    finally:
        ex.stop()
        conn.close()


def test_stage_exception_fails_the_job_not_the_executor(tmp_path):
    db = Database(str(tmp_path / "e.db"))
    conn = db.new_connection(actor=("system", None, "test"))

    def boom(job, c, providers):
        raise RuntimeError("kaboom")

    ex = Executor(db, poll_seconds=60, run_kwargs={"stage_fns": {"parse-ingredients": boom}})
    ex.start()
    try:
        job_id = _queued_run(db, conn)
        ex.wake()
        for _ in range(100):
            if conn.execute("select state from jobs where id = ?", (job_id,)).fetchone()[0] == "failed":
                break
            time.sleep(0.05)
        row = conn.execute("select state, error_code, error_detail from jobs where id = ?", (job_id,)).fetchone()
        assert row["state"] == "failed" and row["error_code"] == "stage_error" and "kaboom" in row["error_detail"]
        assert ex.alive
    finally:
        ex.stop()
        conn.close()
