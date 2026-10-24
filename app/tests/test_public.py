from conftest import seed_recipe


def test_recipe_list_search_and_paging(client, db):
    seed_recipe(db, "Negroni", ingredients=("gin", "campari", "sweet vermouth"))
    seed_recipe(db, "Boulevardier", ingredients=("bourbon", "campari", "sweet vermouth"))
    seed_recipe(db, "Daiquiri", site="liquor", ingredients=("rum", "lime", "sugar"))
    r = client.get("/api/recipes").json()
    assert r["total"] == 3 and [x["name"] for x in r["rows"]] == ["Boulevardier", "Daiquiri", "Negroni"]
    assert client.get("/api/recipes", params={"q": "campari"}).json()["total"] == 2
    assert client.get("/api/recipes", params={"q": "campari gin"}).json()["total"] == 1
    assert client.get("/api/recipes", params={"q": "neg"}).json()["total"] == 1
    assert client.get("/api/recipes", params={"q": "ne"}).json()["total"] == 3  # too short, ignored
    assert client.get("/api/recipes", params={"q": "100%"}).json()["total"] == 0
    page = client.get("/api/recipes", params={"page": 2, "page_size": 2}).json()
    assert page["total"] == 3 and len(page["rows"]) == 1


def test_recipe_detail(client, db):
    rid = seed_recipe(db)
    r = client.get(f"/api/recipes/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Negroni" and body["jsonld"]["@type"] == "Recipe"
    assert client.get("/api/recipes/999").status_code == 404


def test_recipe_ingredients_require_sign_in(client, db):
    rid = seed_recipe(db)
    assert client.get(f"/api/recipes/{rid}/ingredients").status_code == 401


def test_recipe_ingredients_join_taxonomy(client, db, operator):
    rid = seed_recipe(db)
    db.execute("insert into taxonomy_nodes (slug, display_name) values ('gin', 'Gin')")
    db.execute("insert into ingredient_resolutions (normalized_name, taxonomy_slug, method) values ('gin', 'gin', 'alias')")
    rows = client.get(f"/api/recipes/{rid}/ingredients").json()
    assert rows[0]["taxonomy_node"]["slug"] == "gin"
    assert rows[1]["taxonomy_node"] is None
    assert rows[0]["modifiers"] == []


def test_taxonomy_and_node_recipes(client, db):
    rid = seed_recipe(db)
    db.execute("insert into taxonomy_nodes (id, slug, display_name, is_cluster_node) values (1, 'spirit', 'Spirit', 0), (2, 'gin', 'Gin', 1)")
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('London dry', 2)")
    db.execute("insert into ingredient_resolutions (normalized_name, taxonomy_slug, method) values ('gin', 'gin', 'alias')")
    db.execute("insert into taxonomy_nodes (slug, display_name, status) values ('mystery', 'Mystery', 'provisional')")
    rows = client.get("/api/taxonomy").json()
    assert [r["slug"] for r in rows] == ["spirit", "gin"]  # provisional hidden
    gin = rows[1]
    assert gin["parent_ids"] == [1] and gin["aliases"] == ["London dry"] and gin["recipe_count"] == 1
    assert gin["is_cluster_node"] is True
    assert rows[0]["child_ids"] == [2]
    assert client.get("/api/taxonomy/2/recipes").json() == [{"id": rid, "name": "Negroni", "site": "punch"}]
