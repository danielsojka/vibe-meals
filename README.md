# Meal Planner

Flexible recipe, meal planning, and shopping list web app.

## Features
- **Recipes** with diet (omnivorous/vegetarian), meals (breakfast/lunch/dinner/snack, multi-select), servings, instructions
- **Diet variants** — link a vegetarian variant to any recipe (e.g. Vegetarian Burrito ↔ Burrito)
- **Sub-recipes** — a recipe item can be another recipe (Burrito → Pico de Gallo); ingredient search and shopping lists recurse through them
- **Meal templates / builder** — flag a recipe as a template and give each component a slot (e.g. filling, side)
- **Ingredients & brands** — attach recommended brands per ingredient ("Mutti tomato sauce — best for burritos")
- **Search** — by name, meal, diet, and ingredient (matches through sub-recipes and sub-recipe names)
- **Meal planner** — 7-day grid with breakfast/lunch/dinner/snack slots
- **Shopping list** — preview all ingredients for chosen recipes (or the whole week's plan), check off what you already have (pantry auto-checked), then generate the list

## Run
```bash
pip install fastapi uvicorn
python seed.py            # optional: example data (burrito, pico de gallo, variants, brands)
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```
Then open http://127.0.0.1:8000 (or your host/port).

## Deploy
Single process, SQLite file storage — runs on any small host (Railway, Render, Fly.io, a VPS) behind uvicorn/gunicorn. Set `MEALPLANNER_DB` to a persistent path.

## Structure
- `app.py` — FastAPI backend (API + serves the frontend), SQLite schema
- `static/index.html` — single-page frontend (vanilla JS, no build step)
- `seed.py` — example data

## Notes
- The database file (`mealplanner.db`) is gitignored; run `python seed.py` to create example data.
