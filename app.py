"""Meal recipe manager app: FastAPI + SQLite backend serving a single-page frontend."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MEALPLANNER_DB", os.path.join(APP_DIR, "mealplanner.db"))
STATIC_DIR = os.path.join(APP_DIR, "static")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    note TEXT DEFAULT '',
    UNIQUE(ingredient_id, name)
);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    diet TEXT NOT NULL DEFAULT 'omnivorous',   -- 'omnivorous' | 'vegetarian'
    is_subrecipe INTEGER NOT NULL DEFAULT 0,    -- 1 = component/sub-recipe
    is_meal_template INTEGER NOT NULL DEFAULT 0, -- 1 = meal builder template
    base_recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL, -- variant link
    variant_label TEXT DEFAULT '',              -- e.g. 'Vegetarian variant'
    servings REAL NOT NULL DEFAULT 2,
    instructions TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recipe_meals (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    meal TEXT NOT NULL,  -- breakfast | lunch | dinner | snack
    UNIQUE(recipe_id, meal)
);
CREATE TABLE IF NOT EXISTS recipe_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,               -- 'ingredient' | 'recipe'
    ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE CASCADE,
    subrecipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    slot TEXT DEFAULT '',             -- meal-builder slot, e.g. 'filling', 'side'
    quantity TEXT DEFAULT '',
    optional INTEGER NOT NULL DEFAULT 0,
    CHECK ((kind='ingredient' AND ingredient_id IS NOT NULL) OR
           (kind='recipe' AND subrecipe_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS pantry (
    ingredient_id INTEGER PRIMARY KEY REFERENCES ingredients(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS planner (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,               -- ISO date
    meal TEXT NOT NULL,             -- breakfast | lunch | dinner | snack
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    UNIQUE(day, meal, recipe_id)
);
CREATE INDEX IF NOT EXISTS idx_recipe_name ON recipes(name);
"""

MEALS = ["breakfast", "lunch", "dinner", "snack"]
DIETS = ["omnivorous", "vegetarian"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)


app = FastAPI(title="Meal Planner")


# ---------- helpers ----------

def recipe_row_to_dict(conn, r):
    meals = [m["meal"] for m in conn.execute(
        "SELECT meal FROM recipe_meals WHERE recipe_id=?", (r["id"],))]
    items = []
    for it in conn.execute("SELECT * FROM recipe_items WHERE recipe_id=? ORDER BY id", (r["id"],)):
        item = {
            "id": it["id"], "kind": it["kind"], "slot": it["slot"] or "",
            "quantity": it["quantity"] or "", "optional": bool(it["optional"]),
        }
        if it["kind"] == "ingredient":
            ing = conn.execute("SELECT name, category FROM ingredients WHERE id=?",
                               (it["ingredient_id"],)).fetchone()
            if not ing:
                continue
            item["ingredient_id"] = it["ingredient_id"]
            item["name"] = ing["name"]
            item["brands"] = [dict(b) for b in conn.execute(
                "SELECT id, name, note FROM brands WHERE ingredient_id=? ORDER BY name",
                (it["ingredient_id"],))]
        else:
            sub = conn.execute("SELECT id, name, diet, is_subrecipe, is_meal_template FROM recipes WHERE id=?",
                               (it["subrecipe_id"],)).fetchone()
            if not sub:
                continue
            item["subrecipe_id"] = it["subrecipe_id"]
            item["name"] = sub["name"]
            item["sub_diet"] = sub["diet"]
        items.append(item)
    return {
        "id": r["id"], "name": r["name"], "description": r["description"] or "",
        "diet": r["diet"], "is_subrecipe": bool(r["is_subrecipe"]),
        "is_meal_template": bool(r["is_meal_template"]),
        "base_recipe_id": r["base_recipe_id"], "variant_label": r["variant_label"] or "",
        "servings": r["servings"], "instructions": r["instructions"] or "",
        "meals": meals, "items": items,
    }


def get_recipe(conn, rid):
    r = conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "recipe not found")
    return recipe_row_to_dict(conn, r)


def expand_ingredients(conn, recipe_id, servings_mult=1.0, seen=None):
    """Recursively collect leaf ingredients of a recipe (through sub-recipes)."""
    if seen is None:
        seen = set()
    if recipe_id in seen:
        return []
    seen.add(recipe_id)
    out = []
    for it in conn.execute("SELECT * FROM recipe_items WHERE recipe_id=?", (recipe_id,)):
        if it["kind"] == "ingredient":
            ing = conn.execute("SELECT id, name FROM ingredients WHERE id=?",
                               (it["ingredient_id"],)).fetchone()
            if ing:
                out.append({"ingredient_id": ing["id"], "name": ing["name"],
                            "quantity": it["quantity"] or "",
                            "optional": bool(it["optional"])})
        else:
            out.extend(expand_ingredients(conn, it["subrecipe_id"], servings_mult, seen))
    return out


def apply_items(conn, recipe_id, items):
    conn.execute("DELETE FROM recipe_items WHERE recipe_id=?", (recipe_id,))
    for it in items or []:
        kind = it.get("kind")
        if kind == "ingredient":
            iid = it.get("ingredient_id")
            if not conn.execute("SELECT 1 FROM ingredients WHERE id=?", (iid,)).fetchone():
                raise HTTPException(400, f"unknown ingredient id {iid}")
        elif kind == "recipe":
            sid = it.get("subrecipe_id")
            if not conn.execute("SELECT 1 FROM recipes WHERE id=?", (sid,)).fetchone():
                raise HTTPException(400, f"unknown sub-recipe id {sid}")
            if sid == recipe_id:
                raise HTTPException(400, "recipe cannot reference itself")
        else:
            raise HTTPException(400, "item kind must be 'ingredient' or 'recipe'")
        conn.execute(
            "INSERT INTO recipe_items (recipe_id, kind, ingredient_id, subrecipe_id, slot, quantity, optional) "
            "VALUES (?,?,?,?,?,?,?)",
            (recipe_id, kind,
             it.get("ingredient_id") if kind == "ingredient" else None,
             it.get("subrecipe_id") if kind == "recipe" else None,
             it.get("slot", "") or "", it.get("quantity", "") or "",
             1 if it.get("optional") else 0))


# ---------- pydantic models ----------

class IngredientIn(BaseModel):
    name: str
    category: str = ""

class BrandIn(BaseModel):
    name: str
    note: str = ""

class RecipeItemIn(BaseModel):
    kind: str
    ingredient_id: Optional[int] = None
    subrecipe_id: Optional[int] = None
    slot: str = ""
    quantity: str = ""
    optional: bool = False

class RecipeIn(BaseModel):
    name: str
    description: str = ""
    diet: str = "omnivorous"
    is_subrecipe: bool = False
    is_meal_template: bool = False
    base_recipe_id: Optional[int] = None
    variant_label: str = ""
    servings: float = 2
    instructions: str = ""
    meals: list[str] = []
    items: list[RecipeItemIn] = []

class PlannerIn(BaseModel):
    day: str
    meal: str
    recipe_id: int

class ShoppingItem(BaseModel):
    ingredient_id: int
    name: str
    quantity: str
    have: bool

class ShoppingSelection(BaseModel):
    recipe_ids: list[int]
    pantry_ingredient_ids: list[int] = []


# ---------- ingredient & brand endpoints ----------

@app.get("/api/ingredients")
def list_ingredients(q: str = ""):
    with db() as conn:
        rows = conn.execute(
            "SELECT i.*, (SELECT COUNT(*) FROM brands b WHERE b.ingredient_id=i.id) AS brand_count, "
            "EXISTS(SELECT 1 FROM pantry p WHERE p.ingredient_id=i.id) AS in_pantry "
            "FROM ingredients i WHERE i.name LIKE ? ORDER BY i.name", (f"%{q}%",)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/ingredients")
def create_ingredient(body: IngredientIn):
    with db() as conn:
        try:
            cur = conn.execute("INSERT INTO ingredients (name, category) VALUES (?,?)",
                               (body.name.strip(), body.category))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "ingredient already exists")
        return {"id": cur.lastrowid, "name": body.name.strip(), "category": body.category}

@app.delete("/api/ingredients/{iid}")
def delete_ingredient(iid: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM ingredients WHERE id=?", (iid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "ingredient not found")
        return {"ok": True}

@app.get("/api/ingredients/{iid}/brands")
def list_brands(iid: int):
    with db() as conn:
        return [dict(b) for b in conn.execute(
            "SELECT id, name, note FROM brands WHERE ingredient_id=? ORDER BY name", (iid,))]

@app.post("/api/ingredients/{iid}/brands")
def add_brand(iid: int, body: BrandIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM ingredients WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "ingredient not found")
        try:
            cur = conn.execute("INSERT INTO brands (ingredient_id, name, note) VALUES (?,?,?)",
                               (iid, body.name.strip(), body.note))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "brand already exists for this ingredient")
        return {"id": cur.lastrowid, "name": body.name.strip(), "note": body.note}

@app.delete("/api/brands/{bid}")
def delete_brand(bid: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM brands WHERE id=?", (bid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "brand not found")
        return {"ok": True}

@app.post("/api/pantry/{iid}")
def set_pantry(iid: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM ingredients WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "ingredient not found")
        conn.execute("INSERT OR REPLACE INTO pantry (ingredient_id, updated_at) VALUES (?, datetime('now'))", (iid,))
        return {"ok": True}

@app.delete("/api/pantry/{iid}")
def unset_pantry(iid: int):
    with db() as conn:
        conn.execute("DELETE FROM pantry WHERE ingredient_id=?", (iid,))
        return {"ok": True}


# ---------- recipe endpoints ----------


def _recipes_matching_ingredient(conn, ingredient):
    """Recipe ids that contain `ingredient` as a leaf ingredient at any depth
    (through sub-recipes) or as a sub-recipe name."""
    pat = f"%{ingredient}%"
    ids = set()
    direct = conn.execute(
        "SELECT ri.recipe_id FROM recipe_items ri "
        "LEFT JOIN ingredients i ON i.id=ri.ingredient_id "
        "LEFT JOIN recipes sr ON sr.id=ri.subrecipe_id "
        "WHERE i.name LIKE ? OR sr.name LIKE ?", (pat, pat))
    ids |= {r[0] for r in direct.fetchall()}
    deep = conn.execute(
        "WITH RECURSIVE desc(root, sub) AS ("
        " SELECT id, id FROM recipes"
        " UNION ALL"
        " SELECT d.root, ri.subrecipe_id FROM desc d"
        " JOIN recipe_items ri ON ri.recipe_id=d.sub"
        " WHERE ri.kind='recipe') "
        "SELECT DISTINCT d.root FROM desc d "
        "JOIN recipe_items ri ON ri.recipe_id=d.sub "
        "LEFT JOIN ingredients i ON i.id=ri.ingredient_id "
        "LEFT JOIN recipes sr ON sr.id=ri.subrecipe_id "
        "WHERE i.name LIKE ? OR sr.name LIKE ?", (pat, pat))
    ids |= {r[0] for r in deep.fetchall()}
    return sorted(ids)

@app.get("/api/recipes")
def list_recipes(meal: str = "", diet: str = "", q: str = "", ingredient: str = "",
                 kind: str = ""):
    with db() as conn:
        sql = "SELECT DISTINCT r.* FROM recipes r"
        where, params = [], []
        if meal:
            if meal not in MEALS:
                raise HTTPException(400, "invalid meal")
            sql += " JOIN recipe_meals rm ON rm.recipe_id=r.id AND rm.meal=?"
            params.append(meal)
        if diet:
            if diet not in DIETS:
                raise HTTPException(400, "invalid diet")
            where.append("r.diet=?")
            params.append(diet)
        if q:
            where.append("r.name LIKE ?")
            params.append(f"%{q}%")
        if kind == "sub":
            where.append("r.is_subrecipe=1")
        elif kind == "template":
            where.append("r.is_meal_template=1")
        elif kind == "normal":
            where.append("r.is_subrecipe=0 AND r.is_meal_template=0")
        if ingredient:
            ids = _recipes_matching_ingredient(conn, ingredient)
            if not ids:
                return []
            where.append("r.id IN (%s)" % ",".join("?" * len(ids)))
            params.extend(ids)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.name"
        return [recipe_row_to_dict(conn, r) for r in conn.execute(sql, params)]

@app.post("/api/recipes")
def create_recipe(body: RecipeIn):
    if body.diet not in DIETS:
        raise HTTPException(400, "diet must be omnivorous or vegetarian")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (name, description, diet, is_subrecipe, is_meal_template, "
            "base_recipe_id, variant_label, servings, instructions) VALUES (?,?,?,?,?,?,?,?,?)",
            (body.name, body.description, body.diet, int(body.is_subrecipe),
             int(body.is_meal_template), body.base_recipe_id, body.variant_label,
             body.servings, body.instructions))
        rid = cur.lastrowid
        for m in body.meals:
            if m not in MEALS:
                raise HTTPException(400, f"invalid meal: {m}")
            conn.execute("INSERT INTO recipe_meals (recipe_id, meal) VALUES (?,?)", (rid, m))
        apply_items(conn, rid, [i.dict() for i in body.items])
        return get_recipe(conn, rid)

@app.get("/api/recipes/{rid}")
def get_recipe_api(rid: int):
    with db() as conn:
        return get_recipe(conn, rid)

@app.put("/api/recipes/{rid}")
def update_recipe(rid: int, body: RecipeIn):
    if body.diet not in DIETS:
        raise HTTPException(400, "diet must be omnivorous or vegetarian")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM recipes WHERE id=?", (rid,)).fetchone():
            raise HTTPException(404, "recipe not found")
        conn.execute(
            "UPDATE recipes SET name=?, description=?, diet=?, is_subrecipe=?, is_meal_template=?, "
            "base_recipe_id=?, variant_label=?, servings=?, instructions=? WHERE id=?",
            (body.name, body.description, body.diet, int(body.is_subrecipe),
             int(body.is_meal_template), body.base_recipe_id, body.variant_label,
             body.servings, body.instructions, rid))
        conn.execute("DELETE FROM recipe_meals WHERE recipe_id=?", (rid,))
        for m in body.meals:
            if m not in MEALS:
                raise HTTPException(400, f"invalid meal: {m}")
            conn.execute("INSERT INTO recipe_meals (recipe_id, meal) VALUES (?,?)", (rid, m))
        apply_items(conn, rid, [i.dict() for i in body.items])
        return get_recipe(conn, rid)

@app.delete("/api/recipes/{rid}")
def delete_recipe(rid: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM recipes WHERE id=?", (rid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "recipe not found")
        return {"ok": True}

@app.post("/api/recipes/{rid}/variants")
def create_variant(rid: int, body: RecipeIn):
    """Create a diet variant of an existing recipe."""
    if body.diet not in DIETS:
        raise HTTPException(400, "diet must be omnivorous or vegetarian")
    with db() as conn:
        base = conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
        if not base:
            raise HTTPException(404, "recipe not found")
        if body.base_recipe_id not in (None, rid):
            raise HTTPException(400, "base_recipe_id must be the base recipe")
        meals = [m["meal"] for m in conn.execute(
            "SELECT meal FROM recipe_meals WHERE recipe_id=?", (rid,))]
        body.meals = body.meals or meals
        body.base_recipe_id = rid
        if not body.variant_label:
            body.variant_label = f"{body.diet.capitalize()} variant"
        return create_recipe(body)

@app.get("/api/recipes/{rid}/ingredients")
def recipe_expanded_ingredients(rid: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM recipes WHERE id=?", (rid,)).fetchone():
            raise HTTPException(404, "recipe not found")
        return expand_ingredients(conn, rid)


# ---------- meal planner ----------

@app.get("/api/planner")
def get_planner(start: str = "", days: int = 7):
    with db() as conn:
        if not start:
            start = date.today().isoformat()
        try:
            d0 = date.fromisoformat(start)
        except ValueError:
            raise HTTPException(400, "invalid date")
        days = max(1, min(35, days))
        out = []
        for i in range(days):
            day = (d0 + timedelta(days=i)).isoformat()
            entry = {"day": day, "meals": {}}
            for m in MEALS:
                rows = conn.execute(
                    "SELECT p.id, p.recipe_id, r.name, r.diet FROM planner p "
                    "JOIN recipes r ON r.id=p.recipe_id WHERE p.day=? AND p.meal=?", (day, m)).fetchall()
                entry["meals"][m] = [dict(x) for x in rows]
            out.append(entry)
        return out

@app.post("/api/planner")
def add_to_planner(body: PlannerIn):
    if body.meal not in MEALS:
        raise HTTPException(400, "invalid meal")
    with db() as conn:
        try:
            date.fromisoformat(body.day)
        except ValueError:
            raise HTTPException(400, "invalid date")
        if not conn.execute("SELECT 1 FROM recipes WHERE id=?", (body.recipe_id,)).fetchone():
            raise HTTPException(404, "recipe not found")
        try:
            conn.execute("INSERT INTO planner (day, meal, recipe_id) VALUES (?,?,?)",
                          (body.day, body.meal, body.recipe_id))
        except sqlite3.IntegrityError:
            pass  # already planned
        return {"ok": True}

@app.delete("/api/planner/{pid}")
def remove_from_planner(pid: int):
    with db() as conn:
        conn.execute("DELETE FROM planner WHERE id=?", (pid,))
        return {"ok": True}


# ---------- shopping list ----------

@app.post("/api/shopping/preview")
def shopping_preview(body: ShoppingSelection):
    """Aggregate leaf ingredients for chosen recipes; mark what's in pantry or explicitly marked have."""
    with db() as conn:
        agg = {}
        for rid in body.recipe_ids:
            for ing in expand_ingredients(conn, rid):
                key = ing["ingredient_id"]
                if key not in agg:
                    agg[key] = {"ingredient_id": key, "name": ing["name"],
                                 "quantities": [], "optional": True}
                if ing["quantity"]:
                    agg[key]["quantities"].append(ing["quantity"])
                agg[key]["optional"] = agg[key]["optional"] and ing["optional"]
        have = set(body.pantry_ingredient_ids)
        have |= {r["ingredient_id"] for r in conn.execute("SELECT ingredient_id FROM pantry")}
        items = []
        for key, v in agg.items():
            items.append({
                "ingredient_id": key, "name": v["name"],
                "quantity": "; ".join(dict.fromkeys(v["quantities"])),
                "optional": v["optional"], "have": key in have,
            })
        items.sort(key=lambda x: x["name"])
        return {"items": items}


class ShoppingFinalize(BaseModel):
    items: list[ShoppingItem]

@app.post("/api/shopping/finalize")
def shopping_finalize(body: ShoppingFinalize):
    with db() as conn:
        conn.execute("DELETE FROM shopping_list")
        for it in body.items:
            if it.have:
                continue
            conn.execute("INSERT INTO shopping_list (ingredient_id, name, quantity) VALUES (?,?,?)",
                         (it.ingredient_id, it.name, it.quantity))
        return {"ok": True}

@app.get("/api/shopping/list")
def shopping_list():
    with db() as conn:
        return {"items": [dict(r) for r in conn.execute(
            "SELECT id, ingredient_id, name, quantity, bought FROM shopping_list ORDER BY name")]}

@app.post("/api/shopping/toggle/{item_id}")
def shopping_toggle(item_id: int):
    with db() as conn:
        conn.execute("UPDATE shopping_list SET bought = 1 - bought WHERE id=?", (item_id,))
        return {"ok": True}

@app.delete("/api/shopping/{item_id}")
def shopping_delete(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM shopping_list WHERE id=?", (item_id,))
        return {"ok": True}

@app.delete("/api/shopping")
def shopping_clear():
    with db() as conn:
        conn.execute("DELETE FROM shopping_list")
        return {"ok": True}


# ---------- static frontend ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


init_db()
# ensure shopping_list table exists even for pre-existing DBs
with db() as conn:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS shopping_list (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingredient_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        quantity TEXT DEFAULT '',
        bought INTEGER NOT NULL DEFAULT 0
    );
    """)
