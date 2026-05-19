from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import json, sqlite3, os, uuid, re
from pathlib import Path
from openai import OpenAI

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

api_key = os.getenv("TYPHOON_API_KEY")
if not api_key:
    raise RuntimeError("TYPHOON_API_KEY environment variable is not set")
client = OpenAI(api_key=api_key, base_url="https://api.opentyphoon.ai/v1")

UPLOAD_DIR = Path(os.getenv("BINGUS_UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

DB_PATH = os.getenv("BINGUS_DB_PATH", "kitchen.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT DEFAULT '',
            nutrition TEXT DEFAULT '{}',
            steps TEXT DEFAULT '[]',
            note TEXT DEFAULT '',
            image_url TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS kitchen (
            id INTEGER PRIMARY KEY,
            tools TEXT DEFAULT '[]',
            pantry TEXT DEFAULT '[]'
        );
    """)
    # Migration: add missing columns for old databases
    for col, col_type in [("description", "TEXT DEFAULT ''"), ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")]:
        try:
            conn.execute(f"SELECT {col} FROM gallery LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE gallery ADD COLUMN {col} {col_type}")
    conn.commit()
    conn.close()

init_db()

def parse_json(text: str) -> dict:
    import logging
    text = text.strip()
    # remove markdown code fences
    text = re.sub(r'```(?:json)?\s*', '', text).strip()
    # remove trailing ``` if any
    text = re.sub(r'```\s*$', '', text).strip()
    # remove BOM
    text = text.lstrip('\ufeff')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # try to find first { ... } block
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == '{':
            if start == -1:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    start = -1
    raise HTTPException(500, f"AI returned invalid JSON. Raw: {text[:300]}")

# ── Models ──
class SuggestRequest(BaseModel):
    ingredients: str
    tools: str
    method: str
    notes: str = ""
    locale: str = "en"

class DetailRequest(BaseModel):
    name: str
    ingredients: str
    tools: str
    method: str
    notes: str = ""
    locale: str = "en"

class SaveRecipeRequest(BaseModel):
    name: str
    description: str = ""
    nutrition: dict = {}
    steps: list = []
    note: str = ""
    image_url: str = ""

class KitchenRequest(BaseModel):
    tools: list
    pantry: list

class ChatRequest(BaseModel):
    message: str
    context: dict = {}
    history: list = []
    locale: str = "en"

# ── Endpoints ──

FALLBACK_SUGGESTIONS = [
    {"name": "Fried Rice with Egg", "calories": 320, "description": "2 cups rice, 2 eggs, green onion, soy sauce, pepper", "emoji": "🍚", "ingredients": ["Rice", "Eggs", "Green onion", "Soy sauce", "Pepper", "Cooking oil"], "missing": ["Rice", "Green onion"]},
    {"name": "Minced Pork Omelette", "calories": 280, "description": "3 eggs, 100g minced pork, green onion, fish sauce, pepper", "emoji": "🍳", "ingredients": ["Eggs", "Minced pork", "Green onion", "Fish sauce", "Pepper", "Cooking oil"], "missing": ["Minced pork", "Green onion"]},
    {"name": "Stir-fried Mixed Vegetables", "calories": 150, "description": "300g mixed veggies, garlic, oyster sauce", "emoji": "🥬", "ingredients": ["Mixed vegetables", "Garlic", "Oyster sauce", "Cooking oil"], "missing": ["Mixed vegetables", "Oyster sauce"]},
    {"name": "Boiled Egg Salad", "calories": 220, "description": "3 boiled eggs, onion, chili, lime, fish sauce, cilantro", "emoji": "🥗", "ingredients": ["Eggs", "Onion", "Chili", "Lime", "Fish sauce", "Cilantro"], "missing": ["Lime", "Onion", "Cilantro"]},
    {"name": "Clear Soup with Pork", "calories": 300, "description": "200g rice noodles, pork balls, minced pork, bean sprouts, cilantro, green onion", "emoji": "🍜", "ingredients": ["Rice noodles", "Pork balls", "Minced pork", "Bean sprouts", "Cilantro", "Green onion"], "missing": ["Rice noodles", "Bean sprouts", "Cilantro"]}
]

@app.post("/suggest")
async def suggest_recipes(req: SuggestRequest):
    lang = "Thai" if req.locale == "th" else "English"
    prompt = f"""Kitchen ingredients: {req.ingredients}
Available tools/equipment: {req.tools}
Preferred cooking method: {req.method}
Additional notes: {req.notes}

Suggest recipes that work with the available equipment.
Respond in {lang}. All text — names, descriptions, ingredient names, and missing items — must be in {lang}."""
    system = f"""You are Bingus Chef, a realistic home cook. Recommend ONLY dishes that can ACTUALLY BE MADE with the user's available tools and ingredients.

TOOL-FIRST RULES (MOST IMPORTANT):
- Analyze tools FIRST. Only pan + stove → stir-fry, deep-fry, fried rice.
- Only pot → soups, curries, boiled dishes.
- Only rice cooker → rice dishes, steamed dishes.
- NO heat source → cold dishes only (salads, no cooking required).
- NEVER suggest a dish requiring heat if user has no stove.
- NEVER suggest a dish requiring an oven if user has none.
- If tools are very limited, suggest fewer dishes (even 1-2 is fine).

INGREDIENT RULES:
- Base on ingredients user has. Simple ingredients = simple dishes.
- "missing" = minimal extra ingredients needed. Keep it short.

CRITICAL: Respond in {lang}. All text (names, descriptions, ingredient names, missing items) must be in {lang}.

OUTPUT: up to 5 suggestions, can be fewer if tools limited.
Output ONLY valid JSON. No markdown, no code blocks.
{{"suggestions": [
  {{"name": "Stir-fried Basil Chicken", "calories": 350, "description": "200g chicken, garlic, chili, basil, seasoning sauce", "emoji": "🍳", "ingredients": ["Chicken", "Garlic", "Chili", "Basil", "Seasoning sauce", "Fish sauce", "Sugar"], "missing": ["Basil"]}}
]}}"""
    try:
        res = client.chat.completions.create(
            model="typhoon-v2.5-30b-a3b-instruct",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048
        )
        try:
            return parse_json(res.choices[0].message.content)
        except HTTPException:
            return {"suggestions": FALLBACK_SUGGESTIONS}
    except Exception as e:
        return {"suggestions": FALLBACK_SUGGESTIONS}

@app.post("/detail")
async def get_recipe_detail(req: DetailRequest):
    lang = "Thai" if req.locale == "th" else "English"
    prompt = f"""Recipe: {req.name}
Available ingredients: {req.ingredients}
Available tools: {req.tools}
Cooking method: {req.method}
Notes: {req.notes}

Give a detailed recipe that actually works.
Respond in {lang}. All text — ingredient names, step descriptions, and everything else — must be in {lang}."""
    system = f"""You are Bingus Chef, a realistic home cook. Give a detailed recipe that ACTUALLY WORKS in a real kitchen.

REALISM RULES:
- Only include ingredients and steps that make sense for this specific dish. No random extras.
- Quantities must be realistic (e.g. 2 tbsp fish sauce for stir-fry, not 1 tsp or 1 cup).
- CHECK user's tools. Only include steps using the tools the user HAS. No heat source → cold-prep only.
- NEVER reference a tool the user doesn't have (e.g. don't say "preheat oven" if no oven).
- Steps must follow real cooking order and technique for this dish.
- "ingredients": complete list of every ingredient needed, with quantities.
- prep_steps = preparing ingredients with exact quantities (e.g. "Slice 200g pork into thin pieces")
- cook_steps = actual cooking process (heat, fry, boil, season, plate)
- timer = minutes. 0 = no timer. Only set timer if that step genuinely needs waiting (boiling, simmering, steaming).
- nutrition = realistic values for this dish
- missing_ingredients = what user needs to buy, keep it real

CRITICAL: Respond in {lang}. All text (ingredient names, step descriptions, everything) must be in {lang}.

Output ONLY valid JSON. No markdown, no code blocks.
{{
  "name": "Stir-fried Basil Chicken",
  "description": "Stir-fried basil chicken with 200g chicken, garlic, chili, basil, seasoning sauce",
  "nutrition": {{"protein": 28, "carbs": 10, "fat": 22, "fiber": 2, "calories": 350}},
  "ingredients": ["200g chicken thigh", "5 cloves garlic", "3-4 bird chilies", "1 cup basil leaves", "1 tbsp fish sauce", "1 tbsp soy sauce", "1/2 tsp sugar", "1 tbsp oil"],
  "prep_steps": [
    {{"text": "Slice 200g chicken into bite-sized pieces", "timer": 0}},
    {{"text": "Pound 5 garlic cloves + 3-4 chilies", "timer": 0}}
  ],
  "cook_steps": [
    {{"text": "Heat pan with 1 tbsp oil, fry garlic and chili until fragrant", "timer": 0}},
    {{"text": "Add chicken, stir-fry until cooked through, about 3 minutes", "timer": 3}},
    {{"text": "Season with 1 tbsp fish sauce, 1 tbsp soy sauce, 1/2 tsp sugar", "timer": 0}},
    {{"text": "Toss in basil leaves, stir quickly, turn off heat", "timer": 0}}
  ],
  "missing_ingredients": ["Basil leaves"]
}}"""
    try:
        res = client.chat.completions.create(
            model="typhoon-v2.5-30b-a3b-instruct",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=2048
        )
        raw = res.choices[0].message.content
        return parse_json(raw)
    except Exception as e:
        raise HTTPException(500, f"AI error: {str(e)}")

@app.post("/chat")
async def chat_with_bingus(req: ChatRequest):
    lang = "Thai" if req.locale == "th" else "English"
    ctx = req.context or {}
    context_str = f"Cooking: {ctx.get('recipe_name', '')}, Current step: {ctx.get('current_step', '')}"
    messages = [
        {"role": "system", "content": f"You are Bingus Chef, a cute little cat chef. Friendly, playful, keep replies short (2-3 sentences). Give practical cooking advice.\n{context_str}\n\nCRITICAL: Respond in {lang}. All text must be in {lang}."}
    ]
    for h in req.history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": req.message})
    try:
        res = client.chat.completions.create(
            model="typhoon-v2.5-30b-a3b-instruct",
            messages=messages, temperature=0.7, max_tokens=300
        )
        return {"reply": res.choices[0].message.content}
    except:
        return {"reply": "Meow! Bingus is sorry, having trouble connecting. Try again later 🐾"}

@app.post("/save-recipe")
async def save_recipe(req: SaveRecipeRequest):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO gallery (name, description, nutrition, steps, note, image_url) VALUES (?, ?, ?, ?, ?, ?)",
        (req.name, req.description, json.dumps(req.nutrition, ensure_ascii=False),
         json.dumps(req.steps, ensure_ascii=False), req.note, req.image_url)
    )
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return {"status": "ok", "id": rid}

@app.get("/gallery")
async def get_gallery():
    conn = get_db()
    rows = conn.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{
        "id": r["id"], "name": r["name"], "description": r["description"],
        "nutrition": json.loads(r["nutrition"]) if r["nutrition"] else {},
        "steps": json.loads(r["steps"]) if r["steps"] else [],
        "note": r["note"], "image_url": r["image_url"], "created_at": r["created_at"]
    } for r in rows]

@app.delete("/gallery/{rid}")
async def delete_gallery(rid: int):
    conn = get_db()
    row = conn.execute("SELECT image_url FROM gallery WHERE id = ?", (rid,)).fetchone()
    if row and row["image_url"]:
        img_path = (Path(".") / row["image_url"].lstrip("/")).resolve()
        if img_path.exists():
            img_path.unlink()
    conn.execute("DELETE FROM gallery WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/kitchen")
async def get_kitchen():
    conn = get_db()
    row = conn.execute("SELECT * FROM kitchen WHERE id = 1").fetchone()
    conn.close()
    if row:
        return {"tools": json.loads(row["tools"]), "pantry": json.loads(row["pantry"])}
    defaults = {"tools": [], "pantry": ["Salt", "Black pepper", "Fish sauce", "Sugar", "Cooking oil", "Soy sauce", "Oyster sauce", "Seasoning powder", "Garlic", "Shallot"]}
    return defaults

@app.post("/kitchen")
async def save_kitchen(req: KitchenRequest):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO kitchen (id, tools, pantry) VALUES (1, ?, ?)",
                 (json.dumps(req.tools, ensure_ascii=False), json.dumps(req.pantry, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    name = f"{uuid.uuid4()}.{ext}"
    (UPLOAD_DIR / name).write_bytes(await file.read())
    return {"url": f"/uploads/{name}"}

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/BingusProf.jpg")
async def get_profile():
    return FileResponse("BingusProf.jpg")

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("BingusProf.jpg")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
