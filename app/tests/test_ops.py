import pytest

from conftest import seed_recipe
from spiritolo.executor import run_inline


def test_ops_requires_admin(client, db):
    assert client.post("/api/ops/query", json={"table": "recipes"}).status_code == 401


def test_ops_rejects_non_admin(client, operator):
    assert client.post("/api/ops/query", json={"table": "recipes"}).status_code == 403


def test_generic_query_filters_order_and_paging(client, db, admin):
    seed_recipe(db, "Negroni")
    seed_recipe(db, "Boulevardier")
    seed_recipe(db, "Daiquiri", site="liquor")
    r = client.post("/api/ops/query", json={
        "table": "recipes", "select": "id, title, site",
        "filters": [{"col": "site", "op": "eq", "value": "punch"}],
        "order": {"col": "title", "asc": False}, "limit": 1, "offset": 0,
    }).json()
    assert r["total"] == 2 and r["rows"][0]["title"] == "Negroni" and set(r["rows"][0]) == {"id", "title", "site"}
    r = client.post("/api/ops/query", json={
        "table": "recipes_public", "filters": [{"col": "site", "op": "in", "value": ["liquor"]}],
    }).json()
    assert r["total"] == 1 and r["rows"][0]["jsonld"]["name"] == "Daiquiri"
    r = client.post("/api/ops/query", json={
        "table": "recipes", "filters": [{"col": "title", "op": "ilike", "value": "*oule*"}],
    }).json()
    assert r["total"] == 1
    r = client.post("/api/ops/query", json={
        "table": "recipes", "search": {"terms": ["dai"], "cols": ["title"]},
    }).json()
    assert r["total"] == 1


def test_generic_query_rejects_unknown_table_column_and_operator(client, admin):
    assert client.post("/api/ops/query", json={"table": "passkeys"}).status_code == 404
    assert client.post("/api/ops/query", json={"table": "sqlite_master"}).status_code == 404
    assert client.post("/api/ops/query", json={"table": "recipes", "select": "id, nope"}).status_code == 400
    assert client.post("/api/ops/query", json={
        "table": "recipes", "filters": [{"col": "id", "op": "drop", "value": 1}]}).status_code == 400
    assert client.post("/api/ops/query", json={
        "table": "recipes", "filters": [{"col": "id; --", "op": "eq", "value": 1}]}).status_code == 400


def test_run_lifecycle_through_the_api_and_executor(client, db, admin, app, monkeypatch):
    ids = [seed_recipe(db, f"Recipe {i}", url=f"https://x/{i}") for i in range(3)]
    r = client.post("/api/ops/runs", json={"stage": "parse-ingredients"})
    assert r.status_code == 200
    job_id = r.json()["id"]
    run = client.get(f"/api/ops/runs/{job_id}").json()
    assert run["state"] == "draft" and run["created_by"] == "ruddick" and run["task_count"] == 0

    assert client.post(f"/api/ops/runs/{job_id}/llm", json={"provider": "ollama", "model": "qwen3:14b"}).status_code == 200
    r = client.post(f"/api/ops/runs/{job_id}/items", json={"entity_type": "recipe", "entity_ids": [str(i) for i in ids]})
    assert r.json() == {"added": 3}
    assert client.get(f"/api/ops/runs/{job_id}").json()["never_run_count"] == 3

    pool = client.post("/api/ops/eligible-pool", json={"stage": "parse-ingredients", "filter": {}, "sort": "title:asc"}).json()
    assert pool["total"] == 3 and pool["rows"][0]["status"] == "never_run"
    facets = client.post("/api/ops/eligible-pool/facets", json={"stage": "parse-ingredients", "filter": {}}).json()
    assert facets["status"] == {"never_run": 3} and facets["source"] == {"punch": 3}

    items = client.post(f"/api/ops/runs/{job_id}/items/query", json={"filter": {}, "sort": "title:asc", "limit": 2}).json()
    assert items["total"] == 3 and len(items["rows"]) == 2 and items["rows"][0]["task_state"] == "pending"
    removed = client.post(f"/api/ops/runs/{job_id}/items/remove", json={"item_ids": [items["rows"][0]["item_id"]]}).json()
    assert removed == {"removed": 1}

    assert client.get("/api/ops/estimate", params={"provider": "openai", "model": "x", "items": 100}).json()["cents"] > 0
    assert client.get("/api/ops/estimate", params={"provider": "ollama", "model": "x", "items": 100}).json()["cents"] == 0

    assert client.post(f"/api/ops/runs/{job_id}/start", json={"max_cost_cents": 0}).status_code == 200
    assert client.get(f"/api/ops/runs/{job_id}").json()["state"] == "queued"
    assert client.post(f"/api/ops/runs/{job_id}/start", json={}).status_code == 409
    assert client.delete(f"/api/ops/runs/{job_id}").status_code == 409

    # A fake stage: applies every pending member.
    def fake_stage(job, conn, providers):
        conn.execute(
            "update job_items set state = 'applied', outcome = 'resolved', code_version = 'v9' "
            "where job_id = ? and state = 'pending'", (job["id"],))
        return {"applied": 2}

    assert run_inline(app.state.spiritolo.db, stage_fns={"parse-ingredients": fake_stage}) == 1
    run = client.get(f"/api/ops/runs/{job_id}").json()
    assert run["state"] == "done" and run["items_applied"] == 2 and run["task_count"] == 2
    assert client.post(f"/api/ops/runs/{job_id}/retry", json={}).status_code == 200
    assert client.get(f"/api/ops/runs/{job_id}").json()["state"] == "queued"
    assert client.post(f"/api/ops/runs/{job_id}/cancel").json() == {"state": "cancelled"}
    assert client.get("/api/ops/runs/9999").status_code == 404
    pool = client.post("/api/ops/eligible-pool", json={"stage": "parse-ingredients", "filter": {"status": ["applied"]}}).json()
    assert pool["total"] == 2


def test_reviews_flag_resolve_dismiss(client, db, admin):
    rid = seed_recipe(db)
    r = client.post("/api/ops/reviews/flag", json={"entity_kind": "recipe", "entity_id": str(rid), "stage": "parse-ingredients", "note": "odd"})
    assert r.status_code == 200
    review_id = r.json()["id"]
    q = client.post("/api/ops/query", json={"table": "needs_review"}).json()
    assert q["rows"] == [{"entity_kind": "recipe", "entity_id": str(rid), "stage": "parse-ingredients", "reason": "human_flag"}]
    assert client.post(f"/api/ops/reviews/{review_id}/dismiss").status_code == 200
    assert db.execute("select state, reviewed_by from human_reviews where id = ?", (review_id,)).fetchone().asdict() == {"state": "dismissed", "reviewed_by": "ruddick"}
    assert client.post("/api/ops/reviews/999/dismiss").status_code == 404
    assert client.post("/api/ops/reviews/flag", json={"entity_kind": "recipe"}).status_code == 400


def test_taxonomy_curation(client, db, admin):
    root = client.post("/api/ops/taxonomy/nodes", json={"slug": "spirit", "display_name": "Spirit"}).json()["id"]
    gin = client.post("/api/ops/taxonomy/nodes", json={
        "slug": "gin", "display_name": "Gin", "parent_id": root, "is_cluster_node": True, "aliases": ["London dry"]}).json()["id"]
    assert client.post("/api/ops/taxonomy/nodes", json={"slug": "bad_slug", "display_name": "x"}).status_code == 409
    assert client.patch(f"/api/ops/taxonomy/nodes/{gin}", json={"patch": {"display_name": "Gin!", "aliases": ["dry gin"]}}).status_code == 200
    node = [n for n in client.get("/api/taxonomy").json() if n["id"] == gin][0]
    assert node["display_name"] == "Gin!" and node["aliases"] == ["dry gin"] and node["parent_ids"] == [root]
    assert client.put(f"/api/ops/taxonomy/nodes/{root}/parents", json={"parent_ids": [gin]}).status_code == 409  # cycle
    blockers = client.get(f"/api/ops/taxonomy/nodes/{root}/blockers").json()
    assert blockers["children"] == 1 and blockers["child_names"][0]["id"] == gin
    assert client.delete(f"/api/ops/taxonomy/nodes/{root}").status_code == 409
    assert client.delete(f"/api/ops/taxonomy/nodes/{gin}").status_code == 200
    assert client.delete(f"/api/ops/taxonomy/nodes/{root}").status_code == 200
    assert client.get("/api/ops/taxonomy/nodes/999/blockers").status_code == 404


def test_audit_log_records_the_operator(client, db, admin):
    client.post("/api/ops/taxonomy/nodes", json={"slug": "rum", "display_name": "Rum"})
    row = db.execute("select actor_kind, actor_id, source from audit_log where table_name = 'taxonomy_nodes' order by id desc limit 1").fetchone()
    assert row.asdict() == {"actor_kind": "human", "actor_id": str(admin), "source": "api:/api/ops/taxonomy/nodes"}


def test_executor_health_when_disabled(client, admin):
    assert client.get("/api/ops/executor").json() == {"alive": False, "disabled": True}
    assert client.get("/api/health").json()["ok"] is True
