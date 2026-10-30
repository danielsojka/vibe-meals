"""Seed the mealplanner DB with example data (burrito, pico de gallo, variants, brands)."""
import os
import sys

from app import db, init_db

init_db()

with db() as conn:
    if conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]:
        print("DB already seeded, skipping.")
        sys.exit(0)

    def ing(name, cat=""):
        r = conn.execute("SELECT id FROM ingredients WHERE name=?", (name,)).fetchone()
        if r:
            return r["id"]
        return conn.execute("INSERT INTO ingredients (name, category) VALUES (?,?)", (name, cat)).lastrowid

    def recipe(name, diet, meals, items, instructions, description="",
               is_sub=0, is_template=0, base=None, label="", servings=2):
        rid = conn.execute(
            "INSERT INTO recipes (name, description, diet, is_subrecipe, is_meal_template, base_recipe_id, variant_label, servings, instructions) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, description, diet, is_sub, is_template, base, label, servings, instructions)).lastrowid
        for m in meals:
            conn.execute("INSERT INTO recipe_meals (recipe_id, meal) VALUES (?,?)", (rid, m))
        for kind, ref, qty, opt in items:
            conn.execute(
                "INSERT INTO recipe_items (recipe_id, kind, ingredient_id, subrecipe_id, slot, quantity, optional) "
                "VALUES (?,?,?,?,?,?,?)",
                (rid, kind, ref if kind == "ingredient" else None,
                 ref if kind == "recipe" else None, "", qty, int(opt)))
        return rid

    # ingredients
    ing_tomato = ing("tomato sauce", "pantry")
    ing_tomato_raw = ing("tomato")
    ing_onion = ing("onion")
    ing_pepper = ing("bell pepper")
    ing_garlic = ing("garlic")
    ing_cilantro = ing("cilantro")
    ing_lime = ing("lime")
    ing_jalapeno = ing("jalapeño")
    ing_avocado = ing("avocado")
    ing_beans = ing("black beans", "canned")
    ing_rice = ing("rice")
    ing_tortilla = ing("tortilla")
    ing_beef = ing("ground beef")
    ing_cheddar = ing("cheddar cheese")
    ing_salsa = ing("salsa", "pantry")
    ing_oats = ing("oats")
    ing_milk = ing("milk")
    ing_banana = ing("banana")
    ing_pb = ing("peanut butter", "pantry")
    ing_yogurt = ing("greek yogurt")
    ing_honey = ing("honey", "pantry")
    ing_egg = ing("eggs")

    # brands
    for name, note in [("Mutti", "thick, best for burritos"), ("Cento", "cheaper, fine for soups")]:
        conn.execute("INSERT INTO brands (ingredient_id, name, note) VALUES (?,?,?)", (ing_tomato, name, note))
    conn.execute("INSERT INTO brands (ingredient_id, name, note) VALUES (?,?,?)",
                 (ing_beans, "Goya", "low sodium"))
    conn.execute("INSERT INTO brands (ingredient_id, name, note) VALUES (?,?,?)",
                 (ing_salsa, "Herdez", "salsa casera — closest to pico de gallo in a jar"))

    # sub-recipe: pico de gallo (vegetarian)
    pico = recipe("Pico de Gallo", "vegetarian", ["snack"], [
        ("ingredient", ing_tomato_raw, "3, diced", 0),
        ("ingredient", ing_onion, "1/2, finely chopped", 0),
        ("ingredient", ing_cilantro, "handful", 0),
        ("ingredient", ing_lime, "1, juiced", 0),
        ("ingredient", ing_jalapeno, "1, seeded and minced", 1),
    ], "Dice tomatoes, chop onion and cilantro, mix with lime juice and jalapeño. Salt to taste. Rest 15 min before serving.",
        is_sub=1)

    # meal template: burrito (omnivorous base)
    burrito = recipe("Burrito", "omnivorous", ["lunch", "dinner"], [
        ("recipe", pico, "one batch", 0),
        ("ingredient", ing_beef, "250 g", 0),
        ("ingredient", ing_avocado, "1", 1),
        ("ingredient", ing_beans, "1 can", 0),
        ("ingredient", ing_rice, "1 cup cooked", 0),
        ("ingredient", ing_tortilla, "4", 0),
        ("ingredient", ing_cheddar, "50 g", 1),
    ], "Brown the beef with spices, layer rice, beans, beef, pico de gallo, avocado and cheese on tortillas. Fold and toast on a dry pan.",
        description="Classic build-your-own burrito.", is_template=1)

    # vegetarian variant of burrito
    burrito_veg = recipe("Burrito", "vegetarian", ["lunch", "dinner"], [
        ("recipe", pico, "one batch", 0),
        ("ingredient", ing_avocado, "1", 0),
        ("ingredient", ing_beans, "1 can", 0),
        ("ingredient", ing_rice, "1 cup cooked", 0),
        ("ingredient", ing_tortilla, "4", 0),
        ("ingredient", ing_cheddar, "50 g", 1),
        ("ingredient", ing_salsa, "2 tbsp", 1),
    ], "Layer rice, beans, pico de gallo, avocado and cheese on tortillas. Fold and toast on a dry pan.",
        description="Classic build-your-own burrito.", is_template=1, base=burrito, label="Vegetarian variant")

    # normal recipes
    recipe("Overnight Oats", "vegetarian", ["breakfast"], [
        ("ingredient", ing_oats, "1/2 cup", 0),
        ("ingredient", ing_milk, "1/2 cup", 0),
        ("ingredient", ing_banana, "1, sliced", 0),
        ("ingredient", ing_pb, "1 tbsp", 0),
        ("ingredient", ing_yogurt, "2 tbsp", 1),
    ], "Mix oats with milk, top with banana, peanut butter and yogurt. Refrigerate overnight.")

    recipe("Pepper & Onion Frittata", "vegetarian", ["breakfast", "lunch"], [
        ("ingredient", ing_egg, "6", 0),
        ("ingredient", ing_pepper, "1, sliced", 0),
        ("ingredient", ing_onion, "1/2, sliced", 0),
        ("ingredient", ing_cheddar, "40 g", 1),
    ], "Sauté pepper and onion, pour over beaten eggs, top with cheese, bake 15 min at 180°C.")

    recipe("Stuffed Peppers", "omnivorous", ["dinner"], [
        ("ingredient", ing_pepper, "3, halved", 0),
        ("ingredient", ing_beef, "300 g", 0),
        ("ingredient", ing_rice, "1 cup cooked", 0),
        ("ingredient", ing_tomato, "1 jar", 0),
        ("ingredient", ing_onion, "1", 0),
    ], "Fill halved peppers with beef, rice and onion mixture, cover with tomato sauce, bake 35 min at 190°C.")

    print("Seeded example data.")
