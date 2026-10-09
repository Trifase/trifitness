import csv
import datetime
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DEFAULTS_DIR = BASE_DIR / "data_defaults"
STATIC_DIR = BASE_DIR / "static"

DATA_DIR.mkdir(exist_ok=True)
DATA_DEFAULTS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

RECIPES_FILE = DATA_DIR / "recipes.json"
PLAN_FILE = DATA_DIR / "plan.json"
WEIGHT_FILE = DATA_DIR / "weight.json"
ACTIVITIES_FILE = DATA_DIR / "activities.json"
PRESETS_FILE = DATA_DIR / "activity_presets.json"
STRAVA_CONFIG_FILE = DATA_DIR / "strava_config.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
YAZIO_CACHE_FILE = DATA_DIR / "yazio_cache.json"
YAZIO_META_CACHE_FILE = DATA_DIR / "yazio_meta_cache.json"

app = FastAPI(title="Trifitness - Metabolic Health & Lifestyle", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_json(filepath: Path, default_data: Any) -> Any:
    # If file missing or empty, seed from data_defaults/
    if not filepath.exists() or filepath.stat().st_size == 0:
        default_file = DATA_DEFAULTS_DIR / filepath.name
        if default_file.exists():
            try:
                with open(default_file, "r", encoding="utf-8") as df:
                    seed_data = json.load(df)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(seed_data, f, indent=2, ensure_ascii=False)
                return seed_data
            except Exception:
                pass
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(default_data, f, indent=2, ensure_ascii=False)
        return default_data

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback if file is corrupted (e.g. merge conflict markers)
        default_file = DATA_DEFAULTS_DIR / filepath.name
        if default_file.exists():
            try:
                with open(default_file, "r", encoding="utf-8") as df:
                    return json.load(df)
            except Exception:
                pass
        return default_data


def save_json(filepath: Path, data: Any):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# Pydantic models
class Ingredient(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str


class MealPrepInfo(BaseModel):
    is_prep: bool = True
    prep_day: str = "Domenica"
    batch_title: str
    instructions: str
    can_freeze: bool = True


class Recipe(BaseModel):
    id: Optional[str] = None
    title: str
    category: str  # colazione, spuntino, pranzo, cena
    allowed_slots: List[str] = ["pranzo", "cena"]
    servings: int = 1
    prep_time_minutes: int = 5
    ingredients: List[Ingredient] = []
    meal_prep: Optional[Union[MealPrepInfo, List[MealPrepInfo]]] = None
    notes: Optional[str] = ""


class SlotUpdate(BaseModel):
    week_number: int
    day_index: int
    slot_name: str  # colazione, merenda_mattina, pranzo, merenda_pomeriggio, cena
    recipe_id: Optional[str] = None
    servings: Optional[int] = None


class RenameIngredientRequest(BaseModel):
    old_name: str
    new_name: str


class CopyWeekRequest(BaseModel):
    source_week: int = 1
    target_week: int = 2


class WeightEntry(BaseModel):
    id: Optional[str] = None
    date: str  # YYYY-MM-DD
    weight: float
    body_fat: Optional[float] = None
    muscle: Optional[float] = None
    visceral_fat: Optional[float] = None
    water: Optional[float] = None
    waist: Optional[float] = None
    hips: Optional[float] = None
    notes: Optional[str] = ""


class ActivityEntry(BaseModel):
    id: Optional[str] = None
    date: str  # YYYY-MM-DD or YYYY-MM-DDTHH:MM
    activity_type: str = "walking_pad"  # walking_pad, outdoor_walking, cyclette, other
    description: str = ""
    duration_minutes: float
    distance_km: Optional[float] = None
    speed_kmh: Optional[float] = 4.0
    calories: Optional[float] = 0.0
    auto_calories: bool = True
    notes: Optional[str] = ""
    strava_id: Optional[int] = None
    intervals_id: Optional[str] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    z2_z3_min: Optional[float] = None


class ActivityPreset(BaseModel):
    id: Optional[str] = None
    label: str
    type: str = "walking_pad"
    duration: float
    speed: Optional[float] = 4.0
    distance: Optional[float] = None
    description: str = ""


class StravaConfig(BaseModel):
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    refresh_token: Optional[str] = ""
    access_token: Optional[str] = ""
    expires_at: Optional[int] = 0


class StravaImportRequest(BaseModel):
    activities: List[ActivityEntry]


class IntervalsSettings(BaseModel):
    athlete_id: Optional[str] = "i745424"
    api_key: Optional[str] = ""


class YazioSettings(BaseModel):
    username: Optional[str] = ""
    password: Optional[str] = ""
    auto_sync: Optional[bool] = False


class HeartRateSettings(BaseModel):
    resting_hr: Optional[int] = 60
    max_hr: Optional[int] = 150
    lthr: Optional[int] = 130


class GoalsSettings(BaseModel):
    daily_steps: Optional[int] = 10000
    daily_active_calories: Optional[int] = 500


class AppSettings(BaseModel):
    intervals: Optional[IntervalsSettings] = None
    yazio: Optional[YazioSettings] = None
    strava: Optional[StravaConfig] = None
    heart_rate: Optional[HeartRateSettings] = None
    goals: Optional[GoalsSettings] = None


class NutritionSyncRequest(BaseModel):
    date: Optional[str] = None
    calories: Optional[float] = None
    carbohydrates: Optional[float] = None
    protein: Optional[float] = None
    fat: Optional[float] = None


class IntervalsImportRequest(BaseModel):
    activities: List[Dict[str, Any]]


class TestIntervalsRequest(BaseModel):
    athlete_id: Optional[str] = None
    api_key: Optional[str] = None


class TestYazioRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None



class FileParseRequest(BaseModel):
    filename: str
    content: str


# API Endpoints
@app.get("/api/recipes")
def get_recipes():
    return load_json(RECIPES_FILE, [])


@app.post("/api/recipes")
def create_recipe(recipe: Recipe):
    recipes = load_json(RECIPES_FILE, [])
    if not recipe.id:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", recipe.title.lower()).strip("-")
        recipe.id = f"{slug}-{len(recipes) + 1}"
    
    # check if id exists
    for r in recipes:
        if r.get("id") == recipe.id:
            raise HTTPException(status_code=400, detail="Ricetta con questo ID già esistente.")

    recipe_dict = recipe.model_dump()
    recipes.append(recipe_dict)
    save_json(RECIPES_FILE, recipes)
    return recipe_dict


@app.put("/api/recipes/{recipe_id}")
def update_recipe(recipe_id: str, updated: Recipe):
    recipes = load_json(RECIPES_FILE, [])
    found = False
    for i, r in enumerate(recipes):
        if r.get("id") == recipe_id:
            updated.id = recipe_id
            recipes[i] = updated.model_dump()
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Ricetta non trovata.")
    save_json(RECIPES_FILE, recipes)
    return updated.model_dump()


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str):
    recipes = load_json(RECIPES_FILE, [])
    new_recipes = [r for r in recipes if r.get("id") != recipe_id]
    if len(new_recipes) == len(recipes):
        raise HTTPException(status_code=404, detail="Ricetta non trovata.")
    save_json(RECIPES_FILE, new_recipes)
    return {"status": "success", "deleted_id": recipe_id}


@app.get("/api/ingredients")
def get_ingredients():
    recipes = load_json(RECIPES_FILE, [])
    if not recipes:
        recipes = load_json(DATA_DEFAULTS_DIR / "recipes.json", [])

    ingredients_map: Dict[str, Dict[str, Any]] = {}
    for r in recipes:
        for ing in r.get("ingredients", []):
            raw_name = ing.get("name", "").strip()
            if not raw_name:
                continue
            name = normalize_ingredient_name(raw_name)
            raw_unit = ing.get("unit", "g").strip()
            norm_unit = UNIT_NORMALIZATION.get(raw_unit.lower(), raw_unit)
            category = ing.get("category", "Altro").strip()
            if "senza lattosio" in category.lower():
                category = "Banco Frigo & Latticini"

            key = name.lower()
            if key not in ingredients_map:
                ingredients_map[key] = {
                    "name": name,
                    "unit": norm_unit,
                    "category": category,
                    "count": 0,
                }
            ingredients_map[key]["count"] += 1

    return sorted(ingredients_map.values(), key=lambda x: (-x["count"], x["name"].lower()))


@app.post("/api/ingredients/rename")
def rename_ingredient(req: RenameIngredientRequest):
    old_clean = req.old_name.strip()
    new_clean = req.new_name.strip()

    if not new_clean:
        raise HTTPException(status_code=400, detail="Il nuovo nome dell'ingrediente non può essere vuoto.")

    if old_clean.lower() == new_clean.lower():
        return {
            "status": "unchanged",
            "updated_recipes_count": 0,
            "updated_recipes": [],
            "old_name": old_clean,
            "new_name": new_clean
        }

    recipes = load_json(RECIPES_FILE, [])
    updated_recipes_count = 0
    updated_recipe_titles = []

    old_lower = old_clean.lower()

    for recipe in recipes:
        recipe_modified = False
        for ing in recipe.get("ingredients", []):
            raw_name = ing.get("name", "").strip()
            if raw_name.lower() == old_lower:
                ing["name"] = new_clean
                recipe_modified = True

        if recipe_modified:
            updated_recipes_count += 1
            updated_recipe_titles.append(recipe.get("title", ""))

    if updated_recipes_count > 0:
        save_json(RECIPES_FILE, recipes)

    return {
        "status": "success",
        "updated_recipes_count": updated_recipes_count,
        "updated_recipes": updated_recipe_titles,
        "old_name": old_clean,
        "new_name": new_clean
    }


@app.get("/api/plan")
def get_plan():
    return load_json(PLAN_FILE, {"weeks": []})


@app.post("/api/plan")
def save_plan(plan_data: Dict[str, Any]):
    save_json(PLAN_FILE, plan_data)
    return {"status": "success"}


@app.put("/api/plan/slot")
def update_slot(update: SlotUpdate):
    plan = load_json(PLAN_FILE, {"weeks": []})
    for week in plan.get("weeks", []):
        if week.get("week_number") == update.week_number:
            for day in week.get("days", []):
                if day.get("day_index") == update.day_index:
                    if "slots" not in day:
                        day["slots"] = {}
                    if "slot_servings" not in day:
                        day["slot_servings"] = {}

                    if update.recipe_id is not None:
                        day["slots"][update.slot_name] = update.recipe_id
                    elif update.servings is None:
                        day["slots"][update.slot_name] = None
                        day["slot_servings"].pop(update.slot_name, None)

                    if update.servings is not None:
                        day["slot_servings"][update.slot_name] = max(1, update.servings)

                    save_json(PLAN_FILE, plan)
                    return {"status": "success", "day": day}
    raise HTTPException(status_code=404, detail="Giorno o settimana non trovati.")


@app.post("/api/plan/copy-week")
def copy_week(req: CopyWeekRequest):
    plan = load_json(PLAN_FILE, {"weeks": []})
    source = None
    target_idx = None
    for i, w in enumerate(plan.get("weeks", [])):
        if w.get("week_number") == req.source_week:
            source = w
        if w.get("week_number") == req.target_week:
            target_idx = i
            
    if not source or target_idx is None:
        raise HTTPException(status_code=404, detail="Settimana sorgente o destinazione non trovata.")

    # clone days with updated day_index
    offset = 7 if req.target_week == 2 else 0
    copied_days = []
    for d in source.get("days", []):
        new_d = json.loads(json.dumps(d))
        new_d["day_index"] = (new_d.get("day_index", 0) % 7) + offset
        copied_days.append(new_d)

    plan["weeks"][target_idx]["days"] = copied_days
    save_json(PLAN_FILE, plan)
    return {"status": "success", "target_week": plan["weeks"][target_idx]}


UNIT_NORMALIZATION = {
    "cucchiaio": "cucchiai",
    "cucchiai": "cucchiai",
    "spicchio": "spicchi",
    "spicchi": "spicchi",
    "frutto": "frutti",
    "frutti": "frutti",
    "fetta": "fette",
    "fette": "fette",
    "piadina": "piadine",
    "piadine": "piadine",
    "pizza": "pizze",
    "pizze": "pizze",
    "panino": "panini",
    "panini": "panini",
    "uovo": "uova",
    "uova": "uova",
    "finocchio": "finocchi",
    "finocchi": "finocchi",
    "tazzina": "tazzine",
    "tazzine": "tazzine",
    "porzione": "porzioni",
    "porzioni": "porzioni",
}

SINGULAR_UNITS = {
    "cucchiai": "cucchiaio",
    "spicchi": "spicchio",
    "frutti": "frutto",
    "fette": "fetta",
    "piadine": "piadina",
    "pizze": "pizza",
    "panini": "panino",
    "uova": "uovo",
    "finocchi": "finocchio",
    "tazzine": "tazzina",
    "porzioni": "porzione",
}


def normalize_ingredient_name(name: str) -> str:
    return name.strip()


@app.get("/api/shopping-list")
def get_shopping_list(week: Optional[str] = "1"):
    recipes = {r["id"]: r for r in load_json(RECIPES_FILE, [])}
    plan = load_json(PLAN_FILE, {"weeks": []})

    aggregated: Dict[str, Dict[str, Any]] = {}
    slot_names = ["colazione", "merenda_mattina", "pranzo", "pranzo_2", "merenda_pomeriggio", "cena", "cena_2"]

    target_weeks = []
    for w in plan.get("weeks", []):
        w_num = str(w.get("week_number", 1))
        if week in ["both", "all", "14"]:
            target_weeks.append(w)
        elif week == w_num:
            target_weeks.append(w)

    if not target_weeks and plan.get("weeks"):
        target_weeks = [plan["weeks"][0]]

    for week_obj in target_weeks:
        for day in week_obj.get("days", []):
            slots = day.get("slots", {})
            slot_servings_map = day.get("slot_servings", {})
            for slot_key in slot_names:
                recipe_id = slots.get(slot_key)
                if recipe_id and recipe_id in recipes:
                    recipe = recipes[recipe_id]
                    slot_servings = slot_servings_map.get(slot_key, 1) or 1
                    base_servings = recipe.get("servings", 1) or 1
                    multiplier = float(slot_servings) / float(base_servings)

                    for ing in recipe.get("ingredients", []):
                        raw_name = ing.get("name", "").strip()
                        name = normalize_ingredient_name(raw_name)
                        qty = float(ing.get("quantity", 1)) * multiplier
                        raw_unit = ing.get("unit", "").strip()
                        norm_unit = UNIT_NORMALIZATION.get(raw_unit.lower(), raw_unit)
                        category = ing.get("category", "Altro").strip()
                        if "senza lattosio" in category.lower():
                            category = "Banco Frigo & Latticini"

                        agg_key = f"{category}___{name.lower()}___{norm_unit.lower()}"
                        if agg_key not in aggregated:
                            aggregated[agg_key] = {
                                "name": name,
                                "quantity": 0.0,
                                "unit": norm_unit,
                                "category": category,
                                "occurrences": 0,
                                "recipes": set()
                            }
                        aggregated[agg_key]["quantity"] += qty
                        aggregated[agg_key]["occurrences"] += 1
                        aggregated[agg_key]["recipes"].add(recipe["title"])

    # Organize by category
    categories_order = [
        "Ortofrutta",
        "Macellaio sotto casa",
        "Banco Frigo & Latticini",
        "Surgelati",
        "Dispensa, Scatolame & Secco",
        "Pizzeria / Forno",
        "Altro"
    ]

    grouped: Dict[str, List[Dict[str, Any]]] = {c: [] for c in categories_order}

    for item in aggregated.values():
        display_qty = round(item["quantity"], 1) if item["quantity"] % 1 != 0 else int(item["quantity"])
        display_unit = item["unit"]
        if display_qty == 1 and item["unit"].lower() in SINGULAR_UNITS:
            display_unit = SINGULAR_UNITS[item["unit"].lower()]

        item_copy = {
            "name": item["name"],
            "quantity": display_qty,
            "unit": display_unit,
            "category": item["category"],
            "occurrences": item["occurrences"],
            "recipes": list(item["recipes"])
        }
        cat = item["category"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(item_copy)

    # Sort items within each category
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x["name"])

    # Filter out empty categories
    result = {k: v for k, v in grouped.items() if v}
    return result


@app.get("/api/meal-prep")
def get_meal_prep():
    recipes = {r["id"]: r for r in load_json(RECIPES_FILE, [])}
    plan = load_json(PLAN_FILE, {"weeks": []})

    prep_tasks_w1: Dict[str, Dict[str, Any]] = {}
    prep_tasks_w2: Dict[str, Dict[str, Any]] = {}

    slot_names = ["colazione", "merenda_mattina", "pranzo", "pranzo_2", "merenda_pomeriggio", "cena", "cena_2"]

    for week in plan.get("weeks", []):
        w_num = week.get("week_number", 1)
        target_dict = prep_tasks_w1 if w_num == 1 else prep_tasks_w2

        for day in week.get("days", []):
            day_name = day.get("day_name", "")
            slots = day.get("slots", {})
            for slot_key in slot_names:
                r_id = slots.get(slot_key)
                if r_id and r_id in recipes:
                    recipe = recipes[r_id]
                    mp_data = recipe.get("meal_prep")
                    mp_list = []
                    if isinstance(mp_data, list):
                        mp_list = [m for m in mp_data if isinstance(m, dict) and m.get("is_prep")]
                    elif isinstance(mp_data, dict) and mp_data.get("is_prep"):
                        mp_list = [mp_data]

                    for mp in mp_list:
                        batch_title = mp.get("batch_title", recipe["title"])
                        if batch_title not in target_dict:
                            target_dict[batch_title] = {
                                "batch_title": batch_title,
                                "prep_day": mp.get("prep_day", "Domenica"),
                                "instructions": mp.get("instructions", ""),
                                "can_freeze": mp.get("can_freeze", True),
                                "needed_for": []
                            }
                        needed_label = f"{day_name} ({slot_key.replace('_', ' ').capitalize()})"
                        if needed_label not in target_dict[batch_title]["needed_for"]:
                            target_dict[batch_title]["needed_for"].append(needed_label)

    return {
        "week1_prep": list(prep_tasks_w1.values()),
        "week2_prep": list(prep_tasks_w2.values())
    }


# WEIGHT TRACKING ENDPOINTS
@app.get("/api/weight")
def get_weights():
    weights = load_json(WEIGHT_FILE, [])
    weights.sort(key=lambda x: x.get("date", ""))
    return weights


@app.post("/api/weight")
def add_weight(entry: WeightEntry):
    weights = load_json(WEIGHT_FILE, [])
    if not entry.id:
        entry.id = f"w_{int(time.time() * 1000)}"
        entry_dict = entry.model_dump()
        weights.append(entry_dict)
    else:
        entry_dict = entry.model_dump()
        found = False
        for i, w in enumerate(weights):
            if w.get("id") == entry.id:
                weights[i] = entry_dict
                found = True
                break
        if not found:
            weights.append(entry_dict)
    weights.sort(key=lambda x: x.get("date", ""))
    save_json(WEIGHT_FILE, weights)
    return entry_dict


@app.delete("/api/weight/{entry_id}")
def delete_weight(entry_id: str):
    weights = load_json(WEIGHT_FILE, [])
    new_weights = [w for w in weights if w.get("id") != entry_id]
    if len(new_weights) == len(weights):
        raise HTTPException(status_code=404, detail="Misurazione non trovata.")
    save_json(WEIGHT_FILE, new_weights)
    return {"status": "success", "deleted_id": entry_id}


# ACTIVITY PRESETS
DEFAULT_PRESETS = [
    {
        "id": "preset_postpranzo",
        "label": "🚶 15 min @ 3.5 km/h (Post-Pranzo)",
        "type": "walking_pad",
        "duration": 15,
        "speed": 3.5,
        "distance": 0.88,
        "description": "Pad Post-Pranzo (sensibilità insulinica)"
    },
    {
        "id": "preset_stacco",
        "label": "🚶 20 min @ 4.0 km/h (Stacco Serale)",
        "type": "walking_pad",
        "duration": 20,
        "speed": 4.0,
        "distance": 1.33,
        "description": "Pad Decompressione (fine giornata)"
    },
    {
        "id": "preset_lunga",
        "label": "🚶 30 min @ 4.0 km/h (Sessione Lunga)",
        "type": "walking_pad",
        "duration": 30,
        "speed": 4.0,
        "distance": 2.0,
        "description": "Sessione Lunga Walking Pad"
    },
    {
        "id": "preset_outdoor",
        "label": "🌲 45 min @ 4.5 km/h (Camminata Aperto)",
        "type": "outdoor_walking",
        "duration": 45,
        "speed": 4.5,
        "distance": 3.38,
        "description": "Camminata aerobica all'aperto"
    }
]


@app.get("/api/activity-presets")
def get_activity_presets():
    presets = load_json(PRESETS_FILE, None)
    if presets is None:
        presets = DEFAULT_PRESETS
        save_json(PRESETS_FILE, presets)
    return presets


@app.post("/api/activity-presets")
def save_activity_presets(presets: List[ActivityPreset]):
    preset_dicts = [p.model_dump() for p in presets]
    for i, p in enumerate(preset_dicts):
        if not p.get("id"):
            p["id"] = f"preset_{int(time.time() * 1000)}_{i}"
    save_json(PRESETS_FILE, preset_dicts)
    return preset_dicts


def estimate_calories(duration_minutes: float, speed_kmh: Optional[float] = None, activity_type: str = "walking_pad") -> float:
    """Calculates estimated calories burned based on current user weight, duration, and speed."""
    user_weight = 105.0
    try:
        weights_data = load_json(WEIGHT_FILE, [])
        if weights_data:
            valid_weights = [w.get("weight") for w in weights_data if w.get("weight")]
            if valid_weights:
                user_weight = float(valid_weights[-1])
    except Exception:
        pass

    dur_hours = (float(duration_minutes) if duration_minutes else 0.0) / 60.0
    speed = float(speed_kmh) if (speed_kmh and speed_kmh > 0) else 4.0
    cals = dur_hours * speed * user_weight * 0.75
    return round(cals, 1)


# ACTIVITIES TRACKING ENDPOINTS
@app.get("/api/activities")
def get_activities():
    activities = load_json(ACTIVITIES_FILE, [])
    activities.sort(key=lambda x: x.get("date", ""), reverse=True)
    return activities


@app.post("/api/activities")
def add_activity(entry: ActivityEntry):
    activities = load_json(ACTIVITIES_FILE, [])
    entry_dict = entry.model_dump()
    if (entry_dict.get("calories") is None or entry_dict.get("calories") == 0) and entry_dict.get("auto_calories", True):
        entry_dict["calories"] = estimate_calories(entry_dict.get("duration_minutes", 0), entry_dict.get("speed_kmh", 4.0), entry_dict.get("activity_type", "walking_pad"))

    if not entry.id:
        entry_dict["id"] = f"act_{int(time.time() * 1000)}"
        activities.append(entry_dict)
    else:
        found = False
        for i, a in enumerate(activities):
            if a.get("id") == entry.id:
                activities[i] = entry_dict
                found = True
                break
        if not found:
            activities.append(entry_dict)
    activities.sort(key=lambda x: x.get("date", ""), reverse=True)
    save_json(ACTIVITIES_FILE, activities)
    return entry_dict


@app.delete("/api/activities/{entry_id}")
def delete_activity(entry_id: str):
    activities = load_json(ACTIVITIES_FILE, [])
    new_acts = [a for a in activities if a.get("id") != entry_id]
    if len(new_acts) == len(activities):
        raise HTTPException(status_code=404, detail="Attività non trovata.")
    save_json(ACTIVITIES_FILE, new_acts)
    return {"status": "success", "deleted_id": entry_id}


# DEFAULT SETTINGS CONSTANT
DEFAULT_SETTINGS = {
    "intervals": {
        "athlete_id": "i745424",
        "api_key": "6pdys6s3sc6br1wbtuqex26g1"
    },
    "yazio": {
        "username": "",
        "password": "",
        "auto_sync": False
    },
    "strava": {
        "client_id": "",
        "client_secret": "",
        "refresh_token": ""
    },
    "heart_rate": {
        "resting_hr": 60,
        "max_hr": 150,
        "lthr": 130
    },
    "goals": {
        "daily_steps": 10000,
        "daily_active_calories": 500
    }
}


def get_app_settings() -> dict:
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    for key, val in DEFAULT_SETTINGS.items():
        if key not in settings or not isinstance(settings[key], dict):
            settings[key] = val.copy()
        else:
            for sub_k, sub_v in val.items():
                if sub_k not in settings[key]:
                    settings[key][sub_k] = sub_v
    return settings


def save_app_settings(settings: dict):
    save_json(SETTINGS_FILE, settings)
    if "strava" in settings and isinstance(settings["strava"], dict):
        str_cfg = load_json(STRAVA_CONFIG_FILE, {})
        for k in ["client_id", "client_secret", "refresh_token"]:
            if k in settings["strava"]:
                str_cfg[k] = settings["strava"][k]
        save_json(STRAVA_CONFIG_FILE, str_cfg)


# SETTINGS ENDPOINTS
@app.get("/api/settings")
def get_settings():
    settings = get_app_settings()
    display_settings = json.loads(json.dumps(settings))
    yazio_pwd = display_settings.get("yazio", {}).get("password", "")
    display_settings["yazio"]["has_password"] = bool(yazio_pwd)
    str_cfg = load_json(STRAVA_CONFIG_FILE, {})
    if not display_settings.get("strava", {}).get("client_id") and str_cfg.get("client_id"):
        display_settings["strava"] = {
            "client_id": str_cfg.get("client_id", ""),
            "client_secret": str_cfg.get("client_secret", ""),
            "refresh_token": str_cfg.get("refresh_token", "")
        }
    return display_settings


@app.post("/api/settings")
def update_settings(new_settings: AppSettings):
    current = get_app_settings()
    data = new_settings.model_dump(exclude_unset=True)

    if data.get("intervals"):
        current["intervals"].update({k: v for k, v in data["intervals"].items() if v is not None})
    if data.get("yazio"):
        y_data = {k: v for k, v in data["yazio"].items() if v is not None}
        if not y_data.get("password") and current.get("yazio", {}).get("password"):
            y_data["password"] = current["yazio"]["password"]
        current["yazio"].update(y_data)
    if data.get("strava"):
        current["strava"].update({k: v for k, v in data["strava"].items() if v is not None})
    if data.get("heart_rate"):
        current["heart_rate"].update({k: v for k, v in data["heart_rate"].items() if v is not None})
    if data.get("goals"):
        current["goals"].update({k: v for k, v in data["goals"].items() if v is not None})

    save_app_settings(current)
    return {"status": "success", "message": "Impostazioni salvate con successo!", "settings": get_settings()}


@app.post("/api/settings/test-intervals")
def test_intervals(req: Optional[TestIntervalsRequest] = None):
    settings = get_app_settings()
    int_cfg = settings.get("intervals", {})
    athlete_id = (req.athlete_id if req and req.athlete_id else int_cfg.get("athlete_id", "")).strip()
    api_key = (req.api_key if req and req.api_key else int_cfg.get("api_key", "")).strip()
    if not athlete_id or not api_key:
        raise HTTPException(status_code=400, detail="Athlete ID e API Key Intervals.icu richiesti.")

    try:
        r = requests.get(f"https://intervals.icu/api/v1/athlete/{athlete_id}", auth=("API_KEY", api_key), timeout=10)
        if r.status_code == 200:
            d = r.json()
            if req and req.athlete_id and req.api_key:
                int_cfg["athlete_id"] = athlete_id
                int_cfg["api_key"] = api_key
                settings["intervals"] = int_cfg
                save_app_settings(settings)
            return {
                "status": "success",
                "message": f"Connessione riuscita! Atleta: {d.get('name', athlete_id)} ({d.get('city', 'Italia')})"
            }
        else:
            raise HTTPException(status_code=r.status_code, detail=f"Errore Intervals ({r.status_code}): {r.text}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore di rete Intervals: {str(e)}")


@app.post("/api/settings/test-yazio")
def test_yazio(req: Optional[TestYazioRequest] = None):
    settings = get_app_settings()
    y_cfg = settings.get("yazio", {})
    username = (req.username if req and req.username else y_cfg.get("username", "")).strip()
    password = (req.password if req and req.password else y_cfg.get("password", "")).strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Email e Password Yazio richieste.")

    token_url = "https://yzapi.yazio.com/v22/oauth/token"
    yazio_ua = "YAZIO/26.30.1 (com.yazio.ios.YAZIO; build:2607271240; iOS 27.0.0) Ktor"
    headers = {
        "user-agent": yazio_ua,
        "content-type": "application/json"
    }
    auth_body = {
        "username": username,
        "password": password,
        "client_id": "3_5rbw4kehpugw8ogsc8ck8oo4ogswgckcskc04gcg8kk8k48ssw",
        "client_secret": "25gdtt1hvdi8gwowoww4oo88sgsw0oo04o0og0kkgwwks8k0k",
        "grant_type": "password"
    }
    try:
        r = requests.post(token_url, headers=headers, json=auth_body, timeout=12)
        if r.status_code == 200:
            token_data = r.json()
            y_cfg["username"] = username
            y_cfg["password"] = password
            y_cfg["_token"] = {
                "access_token": token_data.get("access_token"),
                "expires_at": int(time.time()) + token_data.get("expires_in", 3600)
            }
            settings["yazio"] = y_cfg
            save_app_settings(settings)
            return {"status": "success", "message": "Login Yazio completato con successo!"}
        else:
            raise HTTPException(status_code=r.status_code, detail=f"Autenticazione Yazio fallita ({r.status_code}). Verifica le credenziali.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore connessione Yazio: {str(e)}")


# YAZIO DIARY & NUTRITION LOGIC
def fetch_yazio_day_data(target_date_str: str) -> dict:
    settings = get_app_settings()
    y_cfg = settings.get("yazio", {})
    username = y_cfg.get("username", "").strip()
    password = y_cfg.get("password", "").strip()
    if not username or not password:
        return {
            "is_configured": False,
            "date": target_date_str,
            "message": "Credenziali Yazio non configurate. Vai in Impostazioni per inserire email e password."
        }

    token_cache = y_cfg.get("_token", {})
    access_token = token_cache.get("access_token")
    expires_at = token_cache.get("expires_at", 0)
    now = int(time.time())

    yazio_ua = "YAZIO/26.30.1 (com.yazio.ios.YAZIO; build:2607271240; iOS 27.0.0) Ktor"

    if not access_token or expires_at <= (now + 60):
        token_url = "https://yzapi.yazio.com/v22/oauth/token"
        headers = {
            "user-agent": yazio_ua,
            "content-type": "application/json"
        }
        auth_body = {
            "username": username,
            "password": password,
            "client_id": "3_5rbw4kehpugw8ogsc8ck8oo4ogswgckcskc04gcg8kk8k48ssw",
            "client_secret": "25gdtt1hvdi8gwowoww4oo88sgsw0oo04o0og0kkgwwks8k0k",
            "grant_type": "password"
        }
        r = requests.post(token_url, headers=headers, json=auth_body, timeout=12)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Login Yazio fallito ({r.status_code}). Controlla email e password in Impostazioni.")
        token_data = r.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        y_cfg["_token"] = {
            "access_token": access_token,
            "expires_at": now + expires_in
        }
        settings["yazio"] = y_cfg
        save_app_settings(settings)

    api_headers = {
        "user-agent": yazio_ua,
        "authorization": f"Bearer {access_token}"
    }

    # 1. Daily Nutrients
    nutr_url = "https://yzapi.yazio.com/v22/user/consumed-items/nutrients-daily"
    r_nutr = requests.get(nutr_url, headers=api_headers, params={"start": target_date_str, "end": target_date_str}, timeout=12)
    nutr_list = r_nutr.json() if r_nutr.status_code == 200 and isinstance(r_nutr.json(), list) else []
    day_nutr = next((x for x in nutr_list if x.get("date") == target_date_str), nutr_list[0] if nutr_list else {})

    # 2. Consumed Items
    items_url = "https://yzapi.yazio.com/v22/user/consumed-items"
    r_items = requests.get(items_url, headers=api_headers, params={"date": target_date_str}, timeout=12)
    items_raw = r_items.json() if r_items.status_code == 200 and isinstance(r_items.json(), dict) else {}

    # 3. Water Intake
    water_url = "https://yzapi.yazio.com/v22/user/water-intake"
    r_water = requests.get(water_url, headers=api_headers, params={"date": target_date_str}, timeout=12)
    water_data = r_water.json() if r_water.status_code == 200 and isinstance(r_water.json(), dict) else {}
    water_val = float(water_data.get("water_intake") or water_data.get("amount") or 0.0)

    # Metadata cache for products and recipes
    meta_cache = load_json(YAZIO_META_CACHE_FILE, {})
    meta_modified = False

    meals = {
        "breakfast": {"label": "Colazione", "icon": "☕", "calories": 0.0, "items": []},
        "lunch": {"label": "Pranzo", "icon": "🍝", "calories": 0.0, "items": []},
        "dinner": {"label": "Cena", "icon": "🍽️", "calories": 0.0, "items": []},
        "snack": {"label": "Spuntini & Snack", "icon": "🍎", "calories": 0.0, "items": []}
    }

    def get_meal_slot(item_dict: dict) -> str:
        raw_dt = str(item_dict.get("daytime") or item_dict.get("meal") or "snack").lower()
        if "breakfast" in raw_dt or "colazione" in raw_dt:
            return "breakfast"
        if "lunch" in raw_dt or "pranzo" in raw_dt:
            return "lunch"
        if "dinner" in raw_dt or "cena" in raw_dt:
            return "dinner"
        return "snack"

    calc_cals = 0.0
    calc_carbs = 0.0
    calc_prot = 0.0
    calc_fat = 0.0

    # Process simple_products
    for p in items_raw.get("simple_products") or []:
        slot = get_meal_slot(p)
        name = p.get("name") or "Alimento"
        nutrs = p.get("nutrients") or {}
        cals = float(nutrs.get("energy.energy", 0.0))
        carbs = float(nutrs.get("nutrient.carb", 0.0))
        prot = float(nutrs.get("nutrient.protein", 0.0))
        fat = float(nutrs.get("nutrient.fat", 0.0))

        meals[slot]["items"].append({
            "name": name,
            "calories": round(cals),
            "amount": 1,
            "unit": "porz.",
            "carbs": round(carbs, 1),
            "protein": round(prot, 1),
            "fat": round(fat, 1),
            "is_recipe": False
        })
        meals[slot]["calories"] += cals
        calc_cals += cals
        calc_carbs += carbs
        calc_prot += prot
        calc_fat += fat

    # Process products
    for p in items_raw.get("products") or []:
        slot = get_meal_slot(p)
        pid = p.get("product_id")
        cached_info = meta_cache.get(f"prod_{pid}")
        if not cached_info and pid:
            try:
                rp = requests.get(f"https://yzapi.yazio.com/v22/products/{pid}", headers=api_headers, timeout=8)
                if rp.status_code == 200:
                    p_data = rp.json()
                    cached_info = {
                        "name": p_data.get("name", "Prodotto"),
                        "base_unit": p_data.get("base_unit", "g"),
                        "nutrients": p_data.get("nutrients", {})
                    }
                    meta_cache[f"prod_{pid}"] = cached_info
                    meta_modified = True
            except Exception:
                pass

        name = cached_info.get("name", "Prodotto Yazio") if cached_info else "Prodotto"
        base_unit = cached_info.get("base_unit", "g") if cached_info else "g"
        nutrs = cached_info.get("nutrients", {}) if cached_info else {}
        amount = float(p.get("amount") or p.get("quantity") or 1.0)
        cals = float(nutrs.get("energy.energy", 0.0)) * amount
        carbs = float(nutrs.get("nutrient.carb", 0.0)) * amount
        prot = float(nutrs.get("nutrient.protein", 0.0)) * amount
        fat = float(nutrs.get("nutrient.fat", 0.0)) * amount

        meals[slot]["items"].append({
            "name": name,
            "calories": round(cals),
            "amount": round(amount, 1),
            "unit": base_unit,
            "carbs": round(carbs, 1),
            "protein": round(prot, 1),
            "fat": round(fat, 1),
            "is_recipe": False
        })
        meals[slot]["calories"] += cals
        calc_cals += cals
        calc_carbs += carbs
        calc_prot += prot
        calc_fat += fat

    # Process recipe_portions
    for r_entry in items_raw.get("recipe_portions") or []:
        slot = get_meal_slot(r_entry)
        rid = r_entry.get("recipe_id")
        cached_info = meta_cache.get(f"rec_{rid}")
        if not cached_info and rid:
            try:
                rr = requests.get(f"https://yzapi.yazio.com/v22/recipes/{rid}", headers=api_headers, timeout=8)
                if rr.status_code == 200:
                    r_data = rr.json()
                    cached_info = {
                        "name": r_data.get("name") or r_data.get("title") or "Ricetta",
                        "nutrients": r_data.get("nutrients", {})
                    }
                    meta_cache[f"rec_{rid}"] = cached_info
                    meta_modified = True
            except Exception:
                pass

        name = cached_info.get("name", "Ricetta Yazio") if cached_info else "Ricetta"
        nutrs = cached_info.get("nutrients", {}) if cached_info else {}
        portion = float(r_entry.get("portion_count") or 1.0)
        cals = float(nutrs.get("energy.energy", 0.0)) * portion
        carbs = float(nutrs.get("nutrient.carb", 0.0)) * portion
        prot = float(nutrs.get("nutrient.protein", 0.0)) * portion
        fat = float(nutrs.get("nutrient.fat", 0.0)) * portion

        meals[slot]["items"].append({
            "name": name,
            "calories": round(cals),
            "amount": round(portion, 2),
            "unit": "porz.",
            "carbs": round(carbs, 1),
            "protein": round(prot, 1),
            "fat": round(fat, 1),
            "is_recipe": True
        })
        meals[slot]["calories"] += cals
        calc_cals += cals
        calc_carbs += carbs
        calc_prot += prot
        calc_fat += fat

    if meta_modified:
        save_json(YAZIO_META_CACHE_FILE, meta_cache)

    for m in meals.values():
        m["calories"] = round(m["calories"])

    tot_energy = day_nutr.get("energy") if day_nutr.get("energy") is not None else calc_cals
    tot_carbs = day_nutr.get("carb") if day_nutr.get("carb") is not None else calc_carbs
    tot_prot = day_nutr.get("protein") if day_nutr.get("protein") is not None else calc_prot
    tot_fat = day_nutr.get("fat") if day_nutr.get("fat") is not None else calc_fat
    goal_energy = day_nutr.get("energy_goal") or 0.0

    result = {
        "is_configured": True,
        "date": target_date_str,
        "calories": round(tot_energy),
        "calories_goal": round(goal_energy),
        "carbs": round(tot_carbs, 1),
        "protein": round(tot_prot, 1),
        "fat": round(tot_fat, 1),
        "water_liters": round(water_val / 1000.0 if water_val > 20 else water_val, 2),
        "meals": meals,
        "synced_at": datetime.datetime.now().strftime("%H:%M:%S")
    }

    cache = load_json(YAZIO_CACHE_FILE, {})
    cache[target_date_str] = result
    save_json(YAZIO_CACHE_FILE, cache)

    return result


@app.get("/api/yazio/daily")
def get_yazio_daily(date: Optional[str] = None):
    target_date = date or datetime.date.today().isoformat()
    cache = load_json(YAZIO_CACHE_FILE, {})
    if target_date in cache:
        return cache[target_date]
    try:
        return fetch_yazio_day_data(target_date)
    except HTTPException:
        raise
    except Exception as e:
        return {
            "is_configured": False,
            "date": target_date,
            "message": f"Errore recupero dati Yazio: {str(e)}"
        }


@app.post("/api/yazio/sync")
def sync_yazio_now(date: Optional[str] = None):
    target_date = date or datetime.date.today().isoformat()
    return fetch_yazio_day_data(target_date)


# INTERVALS.ICU ENDPOINTS
@app.get("/api/intervals/activities")
def get_intervals_activities(oldest: Optional[str] = None, newest: Optional[str] = None):
    settings = get_app_settings()
    int_cfg = settings.get("intervals", {})
    athlete_id = int_cfg.get("athlete_id")
    api_key = int_cfg.get("api_key")
    if not athlete_id or not api_key:
        raise HTTPException(status_code=400, detail="Credenziali Intervals.icu non configurate nelle Impostazioni.")

    if not oldest:
        oldest = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    if not newest:
        newest = datetime.date.today().isoformat()

    existing_activities = load_json(ACTIVITIES_FILE, [])
    imported_ids = {str(a.get("intervals_id")) for a in existing_activities if a.get("intervals_id")}

    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities"
    try:
        r = requests.get(url, auth=("API_KEY", api_key), params={"oldest": oldest, "newest": newest}, timeout=12)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Errore Intervals.icu API: {r.text}")
        raw_acts = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore connessione Intervals.icu: {str(e)}")

    parsed = []
    for a in raw_acts:
        act_id = str(a.get("id"))
        source = a.get("source", "ZEPP")
        name = a.get("name") or "Attività Amazfit"
        act_type = a.get("type") or "Run"
        dist = a.get("distance") or 0.0
        moving_s = a.get("moving_time") or a.get("elapsed_time") or 0
        calories = a.get("calories") or 0
        avg_hr = a.get("average_heartrate")
        max_hr = a.get("max_heartrate")

        zone_times = a.get("icu_hr_zone_times") or []
        z2_z3_s = 0
        if len(zone_times) >= 3:
            z2_z3_s = (zone_times[1] or 0) + (zone_times[2] or 0)

        dur_min = round(moving_s / 60.0, 1)
        dist_km = round(dist / 1000.0, 2)
        speed = round(dist_km / (dur_min / 60.0), 1) if dur_min > 0 and dist_km > 0 else 4.0

        parsed.append({
            "id": act_id,
            "name": name,
            "type": act_type,
            "source": source,
            "start_date": a.get("start_date_local", ""),
            "distance_km": dist_km,
            "duration_min": dur_min,
            "speed_kmh": speed,
            "calories": round(calories),
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "z2_z3_min": round(z2_z3_s / 60.0, 1),
            "already_imported": act_id in imported_ids
        })
    return parsed


@app.post("/api/intervals/import")
def import_intervals_activities(req: IntervalsImportRequest):
    existing = load_json(ACTIVITIES_FILE, [])
    imported_ids = {str(a.get("intervals_id")) for a in existing if a.get("intervals_id")}

    new_entries = []
    for item in req.activities:
        act_id = str(item.get("id"))
        if act_id in imported_ids:
            continue

        name = (item.get("name") or "").lower()
        raw_type = (item.get("type") or "walk").lower()

        if "tapis" in name or "pad" in name or "treadmill" in name or (raw_type == "run" and item.get("distance_km", 0) <= 5.0):
            act_type = "walking_pad"
        elif "ride" in raw_type or "cycle" in raw_type or "bike" in raw_type:
            act_type = "cyclette"
        elif "walk" in raw_type or "run" in raw_type or "hike" in raw_type:
            act_type = "outdoor_walking"
        else:
            act_type = item.get("activity_type") or "other"

        dur_min = float(item.get("duration_min") or 0.0)
        dist_km = float(item.get("distance_km") or 0.0)
        speed = float(item.get("speed_kmh") or (round(dist_km / (dur_min / 60.0), 1) if dur_min > 0 and dist_km > 0 else 4.0))
        cals = float(item.get("calories") or 0.0)

        entry = {
            "id": f"act_int_{act_id}",
            "date": (item.get("start_date") or datetime.datetime.now().isoformat())[:16],
            "activity_type": act_type,
            "description": item.get("name") or "Attività Amazfit",
            "duration_minutes": dur_min,
            "distance_km": dist_km,
            "speed_kmh": speed,
            "calories": cals,
            "auto_calories": False,
            "avg_hr": item.get("avg_hr"),
            "max_hr": item.get("max_hr"),
            "z2_z3_min": item.get("z2_z3_min"),
            "intervals_id": act_id,
            "notes": f"Sincronizzato da Amazfit / Intervals.icu ({item.get('source', 'ZEPP')})"
        }
        existing.append(entry)
        imported_ids.add(act_id)
        new_entries.append(entry)

    existing.sort(key=lambda x: x.get("date", ""), reverse=True)
    save_json(ACTIVITIES_FILE, existing)
    return {"status": "success", "imported_count": len(new_entries), "imported": new_entries}


@app.post("/api/intervals/sync-nutrition")
def sync_nutrition_to_intervals(req: NutritionSyncRequest):
    target_date = req.date or datetime.date.today().isoformat()

    cals = req.calories
    carbs = req.carbohydrates
    protein = req.protein
    fat = req.fat

    if cals is None:
        cache = load_json(YAZIO_CACHE_FILE, {})
        day_data = cache.get(target_date)
        if not day_data:
            day_data = fetch_yazio_day_data(target_date)
        if day_data and day_data.get("is_configured"):
            cals = day_data.get("calories")
            carbs = day_data.get("carbs")
            protein = day_data.get("protein")
            fat = day_data.get("fat")

    if cals is None:
        raise HTTPException(status_code=400, detail=f"Dati nutrizionali non disponibili per {target_date}. Verifica Yazio.")

    settings = get_app_settings()
    int_cfg = settings.get("intervals", {})
    athlete_id = int_cfg.get("athlete_id")
    api_key = int_cfg.get("api_key")
    if not athlete_id or not api_key:
        raise HTTPException(status_code=400, detail="Credenziali Intervals.icu non configurate nelle Impostazioni.")

    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness/{target_date}"
    payload = {
        "kcalConsumed": round(cals),
        "carbohydrates": round(carbs, 1) if carbs is not None else None,
        "protein": round(protein, 1) if protein is not None else None,
        "fatTotal": round(fat, 1) if fat is not None else None
    }

    try:
        r = requests.put(url, auth=("API_KEY", api_key), json=payload, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Errore Intervals.icu: {r.text}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore connessione Intervals.icu: {str(e)}")

    return {
        "status": "success",
        "message": f"Dati inviati con successo a Intervals.icu per {target_date}!",
        "payload": payload
    }


# STRAVA ENDPOINTS
@app.get("/api/strava/config")
def get_strava_config():
    config = load_json(STRAVA_CONFIG_FILE, {})
    return {
        "client_id": config.get("client_id", ""),
        "client_secret": config.get("client_secret", ""),
        "refresh_token": config.get("refresh_token", ""),
        "is_configured": bool(config.get("client_id") and config.get("client_secret") and config.get("refresh_token"))
    }


@app.post("/api/strava/config")
def save_strava_config(cfg: StravaConfig):
    config = load_json(STRAVA_CONFIG_FILE, {})
    if cfg.client_id is not None:
        config["client_id"] = cfg.client_id.strip()
    if cfg.client_secret is not None:
        config["client_secret"] = cfg.client_secret.strip()
    if cfg.refresh_token is not None:
        config["refresh_token"] = cfg.refresh_token.strip()
    config["access_token"] = ""
    config["expires_at"] = 0
    save_json(STRAVA_CONFIG_FILE, config)
    return {
        "status": "success",
        "is_configured": bool(config.get("client_id") and config.get("client_secret") and config.get("refresh_token"))
    }


def get_strava_access_token():
    config = load_json(STRAVA_CONFIG_FILE, {})
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    refresh_token = config.get("refresh_token")

    if not client_id or not client_secret or not refresh_token:
        raise HTTPException(status_code=400, detail="Credenziali Strava non configurate. Clicca su Configura Strava.")

    now = int(time.time())
    access_token = config.get("access_token")
    expires_at = config.get("expires_at", 0)

    if access_token and expires_at > (now + 60):
        return access_token

    token_url = "https://www.strava.com/oauth/token"
    post_data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=post_data, headers={"User-Agent": "Trifitness/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            config["access_token"] = data["access_token"]
            config["refresh_token"] = data.get("refresh_token", refresh_token)
            config["expires_at"] = data.get("expires_at", 0)
            save_json(STRAVA_CONFIG_FILE, config)
            return config["access_token"]
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=400, detail=f"Errore autenticazione Strava ({e.code}): {error_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore connessione a Strava: {str(e)}")


@app.get("/api/strava/activities")
def get_strava_activities():
    access_token = get_strava_access_token()
    existing_activities = load_json(ACTIVITIES_FILE, [])
    imported_strava_ids = {a.get("strava_id") for a in existing_activities if a.get("strava_id")}

    api_url = "https://www.strava.com/api/v3/athlete/activities?per_page=30"
    req = urllib.request.Request(api_url, headers={
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Trifitness/1.1"
    })

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_activities = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=400, detail=f"Errore Strava API ({e.code}): {error_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore connessione a Strava: {str(e)}")

    parsed = []
    for item in raw_activities:
        strava_id = item.get("id")
        sport_type = (item.get("sport_type") or item.get("type") or "Walk").lower()
        name = item.get("name", "Attività Strava")
        name_lower = name.lower()

        if "ride" in sport_type or "cycle" in sport_type:
            act_type = "cyclette"
        elif "tapis" in name_lower or "pad" in name_lower or "virtualwalk" in sport_type or "treadmill" in name_lower:
            act_type = "walking_pad"
        elif "walk" in sport_type or "hike" in sport_type or "run" in sport_type:
            act_type = "outdoor_walking"
        else:
            act_type = "other"

        duration_sec = item.get("moving_time") or item.get("elapsed_time") or 0
        duration_min = round(duration_sec / 60, 1)

        dist_meters = item.get("distance", 0)
        dist_km = round(dist_meters / 1000, 2)

        speed_kmh = 0.0
        if duration_min > 0 and dist_km > 0:
            speed_kmh = round((dist_km / (duration_min / 60)), 1)
        elif item.get("average_speed"):
            speed_kmh = round(float(item["average_speed"]) * 3.6, 1)

        calories = item.get("calories")
        if calories is None and item.get("kilojoules"):
            calories = round(float(item["kilojoules"]) * 0.239006, 1)

        raw_date = item.get("start_date_local") or item.get("start_date") or ""
        date_formatted = raw_date[:16] if len(raw_date) >= 16 else raw_date

        avg_hr = item.get("average_heartrate")
        if avg_hr:
            avg_hr = round(float(avg_hr), 1)

        if calories is None or calories == 0:
            cals_val = estimate_calories(duration_min, speed_kmh, act_type)
            auto_cal_val = True
        else:
            cals_val = round(calories, 1)
            auto_cal_val = False

        parsed.append({
            "strava_id": strava_id,
            "date": date_formatted,
            "activity_type": act_type,
            "description": name,
            "duration_minutes": duration_min,
            "distance_km": dist_km,
            "speed_kmh": speed_kmh,
            "calories": cals_val,
            "auto_calories": auto_cal_val,
            "avg_hr": avg_hr,
            "is_imported": strava_id in imported_strava_ids
        })

    return parsed


@app.post("/api/strava/import")
def import_strava_activities(req: StravaImportRequest):
    activities = load_json(ACTIVITIES_FILE, [])
    existing_strava_ids = {a.get("strava_id") for a in activities if a.get("strava_id")}

    imported_count = 0
    now_ms = int(time.time() * 1000)
    for i, act in enumerate(req.activities):
        if act.strava_id and act.strava_id in existing_strava_ids:
            continue
        act_dict = act.model_dump()
        if (act_dict.get("calories") is None or act_dict.get("calories") == 0) and act_dict.get("auto_calories", True):
            act_dict["calories"] = estimate_calories(act_dict.get("duration_minutes", 0), act_dict.get("speed_kmh", 4.0), act_dict.get("activity_type", "walking_pad"))

        if not act_dict.get("id"):
            act_dict["id"] = f"act_strava_{now_ms}_{i}"
        activities.append(act_dict)
        if act.strava_id:
            existing_strava_ids.add(act.strava_id)
        imported_count += 1

    activities.sort(key=lambda x: x.get("date", ""), reverse=True)
    save_json(ACTIVITIES_FILE, activities)
    return {"status": "success", "imported_count": imported_count}


# FITNESS FILE PARSER (TCX / GPX)
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def parse_strava_date(d_str: str) -> str:
    d_str = d_str.strip().strip('"')
    formats = [
        "%d %b %Y, %H:%M:%S",
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y, %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(d_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    return d_str[:16]


def clean_activity_title(name: str) -> str:
    """Removes file extensions, underscores, and duplicate numbers like (2) from title."""
    if not name:
        return "Attività"
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s*\(\d+\)\s*", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def parse_strava_csv(content: str) -> List[Dict[str, Any]]:
    existing_activities = load_json(ACTIVITIES_FILE, [])
    existing_strava_ids = {a.get("strava_id") for a in existing_activities if a.get("strava_id")}

    reader = csv.DictReader(io.StringIO(content))
    activities = []
    for row in reader:
        act_id_raw = row.get("Activity ID")
        act_id = int(act_id_raw) if act_id_raw and act_id_raw.isdigit() else None
        name = clean_activity_title(row.get("Activity Name") or row.get("Name") or "Attività Strava")
        sport = (row.get("Activity Type") or row.get("Type") or "Walk").lower()

        if "pad" in name.lower() or "tapis" in name.lower() or "virtualwalk" in sport:
            act_type = "walking_pad"
        elif "ride" in sport or "cycle" in sport:
            act_type = "cyclette"
        elif "walk" in sport or "run" in sport or "hike" in sport:
            act_type = "outdoor_walking"
        else:
            act_type = "other"

        date_str = parse_strava_date(row.get("Activity Date") or row.get("Date") or "")

        try:
            m_time = float(row.get("Moving Time") or row.get("Elapsed Time") or 0)
        except ValueError:
            m_time = 0

        try:
            dist_val = float(row.get("Distance") or 0)
            dist_km = round(dist_val / 1000, 2) if dist_val > 100 else round(dist_val, 2)
        except ValueError:
            dist_km = 0.0

        dur_min = round(m_time / 60, 1)
        speed = round((dist_km / (dur_min / 60)), 1) if dur_min > 0 and dist_km > 0 else 4.0

        try:
            avg_hr = float(row.get("Average Heart Rate")) if row.get("Average Heart Rate") else None
        except ValueError:
            avg_hr = None

        try:
            cals = float(row.get("Calories")) if row.get("Calories") else 0.0
        except ValueError:
            cals = 0.0

        if cals == 0:
            cals = estimate_calories(dur_min, speed, act_type)
            is_auto_cal = True
        else:
            cals = round(cals, 1)
            is_auto_cal = False

        activities.append({
            "strava_id": act_id,
            "date": date_str,
            "activity_type": act_type,
            "description": name,
            "duration_minutes": dur_min,
            "distance_km": dist_km,
            "speed_kmh": speed,
            "calories": cals,
            "auto_calories": is_auto_cal,
            "avg_hr": round(avg_hr, 1) if avg_hr else None,
            "is_imported": act_id in existing_strava_ids if act_id else False
        })
    return activities


def utc_to_local_iso(iso_str: Optional[str]) -> str:
    """Converts a UTC or ISO timestamp (e.g. 2026-09-29T05:48:19Z) to local Europe/Rome YYYY-MM-DDTHH:MM."""
    if not iso_str:
        return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    try:
        clean_str = iso_str.strip()
        if clean_str.endswith("Z"):
            dt = datetime.datetime.fromisoformat(clean_str[:-1] + "+00:00")
        elif "+" in clean_str[10:] or ("-" in clean_str[10:] and not clean_str[10:].startswith("-")):
            dt = datetime.datetime.fromisoformat(clean_str)
        else:
            dt = datetime.datetime.fromisoformat(clean_str).replace(tzinfo=datetime.timezone.utc)

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/Rome")
            local_dt = dt.astimezone(tz)
        except Exception:
            local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return iso_str[:16]


def parse_strava_html(content: str, filename: str) -> Dict[str, Any]:
    """Parses an HTML activity page downloaded from Strava (when export_tcx redirects for indoor/treadmill workouts)."""
    title_m = re.search(r"<h1[^>]*activity-name[^>]*>(.*?)</h1>", content, re.DOTALL)
    if not title_m:
        title_m = re.search(r"<title>(.*?)(?:\|.*)?</title>", content)
    title = clean_activity_title(title_m.group(1).strip() if title_m else filename)

    m_dist = re.search(r"distance:\s*([\d.]+)", content)
    m_time = re.search(r"moving_time:\s*([\d.]+)", content)
    m_cal = re.search(r"calories:\s*([\d.]+)", content)
    m_start = re.search(r"startDateLocal:\s*(\d+)", content)
    m_trainer = re.search(r"trainer:\s*(true|false)", content)
    m_speed = re.search(r"avg_speed:\s*([\d.]+)", content)
    m_hr = re.search(r"avg_hr:\s*([\d.]+)", content)
    m_id = re.search(r"/activities/(\d+)", content)

    dist_km = round(float(m_dist.group(1)) / 1000, 2) if m_dist else 0.0
    dur_min = round(float(m_time.group(1)) / 60, 1) if m_time else 0.0
    cals = round(float(m_cal.group(1)), 1) if m_cal else 0.0
    avg_hr = round(float(m_hr.group(1)), 1) if m_hr else None
    speed_kmh = round(float(m_speed.group(1)) * 3.6, 1) if m_speed else 4.0
    is_trainer = (m_trainer.group(1).lower() == "true") if m_trainer else False
    strava_id = int(m_id.group(1)) if m_id else None

    if not strava_id:
        strava_id_m = re.search(r"(?:strava[_-]?)(\d+)", filename.lower())
        strava_id = int(strava_id_m.group(1)) if strava_id_m else None

    if m_start:
        try:
            ts = int(m_start.group(1))
            date_str = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")
        except Exception:
            date_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    else:
        date_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

    act_type = "walking_pad" if is_trainer else "outdoor_walking"
    title_lower = title.lower()
    if "biking" in title_lower or "ciclismo" in title_lower or "cyclette" in title_lower:
        act_type = "cyclette"
    elif "aperto" in title_lower or "outdoor" in title_lower:
        act_type = "outdoor_walking"

    if cals == 0:
        cals = estimate_calories(dur_min, speed_kmh, act_type)
        is_auto_cal = True
    else:
        is_auto_cal = False

    return {
        "date": date_str,
        "activity_type": act_type,
        "description": title,
        "duration_minutes": dur_min,
        "distance_km": dist_km,
        "speed_kmh": speed_kmh,
        "calories": cals,
        "avg_hr": avg_hr,
        "auto_calories": is_auto_cal,
        "strava_id": strava_id
    }


def parse_fitness_file(filename: str, content: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    # 1. Strava activities.csv
    if filename.lower().endswith(".csv") or "activity id" in content[:250].lower():
        return parse_strava_csv(content)

    # 2. HTML downloaded from Strava (redirect for indoor / treadmill activities without GPS TCX)
    content_stripped = content.strip()
    if content_stripped.startswith("<!DOCTYPE html") or "<html" in content[:300].lower() or "pageView.activity()" in content:
        return parse_strava_html(content, filename)

    # 3. XML (TCX / GPX)
    try:
        root = ET.fromstring(content.encode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File non riconosciuto o corrotto: {str(e)}")

    tag_clean = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()

    if "trainingcenterdatabase" in tag_clean or filename.lower().endswith(".tcx"):
        activity = root.find(".//{*}Activity")
        if activity is None:
            activity = root.find(".//Activity")
        sport = (activity.attrib.get("Sport", "walking_pad") if activity is not None else "walking_pad").lower()

        act_id = root.findtext(".//{*}Id")
        if act_id is None:
            act_id = root.findtext(".//Id")
        if not act_id:
            first_lap = root.find(".//{*}Lap")
            if first_lap is None:
                first_lap = root.find(".//Lap")
            if first_lap is not None:
                act_id = first_lap.attrib.get("StartTime")

        date_str = utc_to_local_iso(act_id)

        total_seconds = 0.0
        total_distance_m = 0.0
        total_calories = 0.0
        hr_values = []

        laps = root.findall(".//{*}Lap")
        if not laps:
            laps = root.findall(".//Lap")
        for lap in laps:
            t = lap.findtext("{*}TotalTimeSeconds") or lap.findtext("TotalTimeSeconds")
            if t:
                try:
                    total_seconds += float(t)
                except ValueError:
                    pass
            d = lap.findtext("{*}DistanceMeters") or lap.findtext("DistanceMeters")
            if d:
                try:
                    total_distance_m += float(d)
                except ValueError:
                    pass
            c = lap.findtext("{*}Calories") or lap.findtext("Calories")
            if c:
                try:
                    total_calories += float(c)
                except ValueError:
                    pass

            hr_el = lap.find(".//{*}AverageHeartRateBpm/{*}Value")
            if hr_el is None:
                hr_el = lap.find(".//AverageHeartRateBpm/Value")
            if hr_el is not None and hr_el.text:
                try:
                    hr_values.append(float(hr_el.text))
                except ValueError:
                    pass

        dur_min = round(total_seconds / 60, 1)
        dist_km = round(total_distance_m / 1000, 2)
        speed = round((dist_km / (dur_min / 60)), 1) if dur_min > 0 and dist_km > 0 else 4.0
        avg_hr = round(sum(hr_values) / len(hr_values), 1) if hr_values else None

        act_type = "walking_pad"
        if "biking" in sport or "cycle" in sport:
            act_type = "cyclette"
        elif "run" in sport or "walk" in sport:
            act_type = "outdoor_walking"

        clean_title = clean_activity_title(filename)
        strava_id_m = re.search(r"(?:strava[_-]?)(\d+)", filename.lower())
        strava_id_val = int(strava_id_m.group(1)) if strava_id_m else None

        if total_calories == 0:
            total_calories = estimate_calories(dur_min, speed, act_type)
            is_auto_cal = True
        else:
            is_auto_cal = False

        return {
            "date": date_str,
            "activity_type": act_type,
            "description": clean_title,
            "duration_minutes": dur_min,
            "distance_km": dist_km,
            "speed_kmh": speed,
            "calories": total_calories,
            "avg_hr": avg_hr,
            "auto_calories": is_auto_cal,
            "strava_id": strava_id_val
        }

    elif "gpx" in tag_clean or filename.lower().endswith(".gpx"):
        trk_name = clean_activity_title(root.findtext(".//{*}name") or root.findtext(".//name") or filename)
        pts = root.findall(".//{*}trkpt")
        if not pts:
            pts = root.findall(".//trkpt")

        coords = []
        times = []
        hrs = []

        for pt in pts:
            lat = float(pt.attrib.get("lat", 0))
            lon = float(pt.attrib.get("lon", 0))
            coords.append((lat, lon))
            t_str = pt.findtext("{*}time") or pt.findtext("time")
            if t_str:
                times.append(t_str)

            hr_el = pt.find(".//{*}hr")
            if hr_el is None:
                hr_el = pt.find(".//hr")
            if hr_el is not None and hr_el.text:
                try:
                    hrs.append(float(hr_el.text))
                except ValueError:
                    pass

        tot_dist = 0.0
        for i in range(len(coords) - 1):
            tot_dist += haversine_km(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])

        date_str = utc_to_local_iso(times[0]) if times else datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
        dur_min = 0.0
        if len(times) >= 2:
            try:
                t0 = datetime.datetime.fromisoformat(times[0].replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
                dur_min = round(abs((t1 - t0).total_seconds()) / 60, 1)
            except Exception:
                dur_min = 0.0

        dist_km = round(tot_dist, 2)
        speed = round((dist_km / (dur_min / 60)), 1) if dur_min > 0 and dist_km > 0 else 4.0
        avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None

        act_type = "walking_pad" if "tapis" in trk_name.lower() or "pad" in trk_name.lower() else "outdoor_walking"
        strava_id_m = re.search(r"(?:strava[_-]?)(\d+)", filename.lower())
        strava_id_val = int(strava_id_m.group(1)) if strava_id_m else None
        gpx_cals = estimate_calories(dur_min, speed, act_type)

        return {
            "date": date_str,
            "activity_type": act_type,
            "description": trk_name,
            "duration_minutes": dur_min,
            "distance_km": dist_km,
            "speed_kmh": speed,
            "calories": gpx_cals,
            "avg_hr": avg_hr,
            "auto_calories": True,
            "strava_id": strava_id_val
        }

    else:
        raise HTTPException(status_code=400, detail="Formato file non riconosciuto. Carica un file .tcx o .gpx valido.")


@app.post("/api/activities/parse-file")
def parse_activity_file(req: FileParseRequest):
    return parse_fitness_file(req.filename, req.content)


# ANALYTICS & TIMELINE ENDPOINT
@app.get("/api/analytics")
def get_analytics(days: Optional[int] = 30, start: Optional[str] = None, end: Optional[str] = None):
    today = datetime.date.today()
    if start and end:
        try:
            start_d = datetime.date.fromisoformat(start)
            end_d = datetime.date.fromisoformat(end)
        except ValueError:
            start_d = today - datetime.timedelta(days=29)
            end_d = today
    else:
        num_days = max(1, min(730, days or 30))
        end_d = today
        start_d = today - datetime.timedelta(days=num_days - 1)

    start_str = start_d.isoformat()
    end_str = end_d.isoformat()

    # 1. Weights
    raw_weights = load_json(WEIGHT_FILE, [])
    weights_map = {}
    for w in raw_weights:
        d = str(w.get("date", ""))[:10]
        if d:
            weights_map[d] = {
                "weight": float(w["weight"]) if w.get("weight") is not None else None,
                "body_fat": float(w["body_fat"]) if w.get("body_fat") is not None else None,
                "muscle": float(w["muscle"]) if w.get("muscle") is not None else None,
                "visceral_fat": float(w["visceral_fat"]) if w.get("visceral_fat") is not None else None,
                "waist": float(w["waist"]) if w.get("waist") is not None else None,
            }

    # 2. Activities
    raw_acts = load_json(ACTIVITIES_FILE, [])
    acts_map = {}
    for a in raw_acts:
        d = str(a.get("date", ""))[:10]
        if not d:
            continue
        if d not in acts_map:
            acts_map[d] = {
                "exercise_minutes": 0.0,
                "distance_km": 0.0,
                "exercise_calories": 0.0,
                "steps": 0
            }
        dur = float(a.get("duration_minutes") or 0.0)
        dist = float(a.get("distance_km") or 0.0)
        cals = float(a.get("calories") or 0.0)
        acts_map[d]["exercise_minutes"] += dur
        acts_map[d]["distance_km"] += dist
        acts_map[d]["exercise_calories"] += cals
        if dist > 0:
            acts_map[d]["steps"] += round(dist * 1350)

    # 3. Yazio Nutrients (eaten calories)
    yazio_cache = load_json(YAZIO_CACHE_FILE, {})
    settings = get_app_settings()
    y_cfg = settings.get("yazio", {})
    if y_cfg.get("username") and y_cfg.get("password"):
        try:
            token_cache = y_cfg.get("_token", {})
            access_token = token_cache.get("access_token")
            expires_at = token_cache.get("expires_at", 0)
            now = int(time.time())
            yazio_ua = "YAZIO/26.30.1 (com.yazio.ios.YAZIO; build:2607271240; iOS 27.0.0) Ktor"

            if not access_token or expires_at <= (now + 60):
                r_tok = requests.post(
                    "https://yzapi.yazio.com/v22/oauth/token",
                    headers={"user-agent": yazio_ua, "content-type": "application/json"},
                    json={
                        "username": y_cfg["username"],
                        "password": y_cfg["password"],
                        "client_id": "3_5rbw4kehpugw8ogsc8ck8oo4ogswgckcskc04gcg8kk8k48ssw",
                        "client_secret": "25gdtt1hvdi8gwowoww4oo88sgsw0oo04o0og0kkgwwks8k0k",
                        "grant_type": "password"
                    },
                    timeout=8
                )
                if r_tok.status_code == 200:
                    t_data = r_tok.json()
                    access_token = t_data.get("access_token")
                    y_cfg["_token"] = {"access_token": access_token, "expires_at": now + t_data.get("expires_in", 3600)}
                    settings["yazio"] = y_cfg
                    save_app_settings(settings)

            if access_token:
                r_range = requests.get(
                    f"https://yzapi.yazio.com/v22/user/consumed-items/nutrients-daily?start={start_str}&end={end_str}",
                    headers={"user-agent": yazio_ua, "authorization": f"Bearer {access_token}"},
                    timeout=8
                )
                if r_range.status_code == 200 and isinstance(r_range.json(), list):
                    for dy in r_range.json():
                        d_key = dy.get("date")
                        if d_key:
                            if d_key not in yazio_cache:
                                yazio_cache[d_key] = {}
                            yazio_cache[d_key]["calories"] = round(dy.get("energy", 0))
                            yazio_cache[d_key]["carbs"] = round(dy.get("carb", 0), 1)
                            yazio_cache[d_key]["protein"] = round(dy.get("protein", 0), 1)
                            yazio_cache[d_key]["fat"] = round(dy.get("fat", 0), 1)
                    save_json(YAZIO_CACHE_FILE, yazio_cache)
        except Exception:
            pass

    # 4. Intervals.icu Wellness (Daily steps, resting HR)
    wellness_map = {}
    int_cfg = settings.get("intervals", {})
    if int_cfg.get("athlete_id") and int_cfg.get("api_key"):
        try:
            r_well = requests.get(
                f"https://intervals.icu/api/v1/athlete/{int_cfg['athlete_id']}/wellness",
                auth=("API_KEY", int_cfg["api_key"]),
                params={"oldest": start_str, "newest": end_str},
                timeout=8
            )
            if r_well.status_code == 200 and isinstance(r_well.json(), list):
                for item in r_well.json():
                    w_id = item.get("id")
                    if w_id:
                        wellness_map[w_id] = {
                            "steps": item.get("steps"),
                            "resting_hr": item.get("restingHR")
                        }
        except Exception:
            pass

    # 5. Build timeline
    curr = start_d
    timeline = []
    while curr <= end_d:
        d_str = curr.isoformat()
        w_d = weights_map.get(d_str, {})
        a_d = acts_map.get(d_str, {})
        y_d = yazio_cache.get(d_str, {})
        well_d = wellness_map.get(d_str, {})

        well_steps = well_d.get("steps")
        act_steps = a_d.get("steps", 0)
        final_steps = well_steps if well_steps is not None and well_steps > 0 else (act_steps if act_steps > 0 else None)

        timeline.append({
            "date": d_str,
            "steps": final_steps,
            "distance_km": round(a_d.get("distance_km", 0.0), 2) if a_d.get("distance_km") else None,
            "exercise_minutes": round(a_d.get("exercise_minutes", 0.0), 1) if a_d.get("exercise_minutes") else None,
            "exercise_calories": round(a_d.get("exercise_calories", 0.0)) if a_d.get("exercise_calories") else None,
            "eaten_calories": round(y_d.get("calories", 0.0)) if y_d.get("calories") else None,
            "weight": w_d.get("weight"),
            "body_fat": w_d.get("body_fat"),
            "muscle": w_d.get("muscle"),
            "visceral_fat": w_d.get("visceral_fat"),
            "waist": w_d.get("waist")
        })
        curr += datetime.timedelta(days=1)

    return {
        "status": "success",
        "start_date": start_str,
        "end_date": end_str,
        "days": len(timeline),
        "timeline": timeline
    }


# Static Files and Root
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/kitchen")
@app.get("/cucina")
@app.get("/tablet")
def serve_kitchen():
    return FileResponse(STATIC_DIR / "kitchen.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 9999))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
