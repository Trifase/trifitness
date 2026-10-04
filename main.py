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
    ingredients: List[Ingredient]
    meal_prep: Optional[Union[MealPrepInfo, List[MealPrepInfo]]] = None
    notes: Optional[str] = ""


class SlotUpdate(BaseModel):
    week_number: int
    day_index: int
    slot_name: str  # colazione, merenda_mattina, pranzo, merenda_pomeriggio, cena
    recipe_id: Optional[str] = None


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
    avg_hr: Optional[float] = None


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
                    day["slots"][update.slot_name] = update.recipe_id
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
    cleaned = name.strip()
    lowered = cleaned.lower()

    if "olio" in lowered and ("extravergine" in lowered or "evo" in lowered or "oliva" in lowered):
        return "Olio extravergine d'oliva"

    if "noci" in lowered and ("sgusciate" in lowered or "mandorle" in lowered):
        return "Noci sgusciate"
    if lowered == "noci":
        return "Noci sgusciate"

    if (
        lowered == "pasta"
        or lowered.startswith("pasta (")
        or lowered.startswith("pasta integrale")
        or lowered.startswith("pasta di semola")
        or lowered.startswith("pasta semola")
    ):
        return "Pasta (integrale o semola)"

    return cleaned


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
            for slot_key in slot_names:
                recipe_id = slots.get(slot_key)
                if recipe_id and recipe_id in recipes:
                    recipe = recipes[recipe_id]
                    for ing in recipe.get("ingredients", []):
                        raw_name = ing.get("name", "").strip()
                        name = normalize_ingredient_name(raw_name)
                        qty = float(ing.get("quantity", 1))
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


# Static Files and Root
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 9999))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
