from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import json, sqlite3, os, uuid, re
from pathlib import Path
from openai import OpenAI
import tempfile

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = OpenAI(
    api_key=os.getenv("TYPHOON_API_KEY", "YOUR_TYPHOON_API_KEY_HERE"),
    base_url="https://api.opentyphoon.ai/v1"
)

import tempfile
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

class DetailRequest(BaseModel):
    name: str
    ingredients: str
    tools: str
    method: str
    notes: str = ""

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

# ── Endpoints ──

FALLBACK_SUGGESTIONS = [
    {"name": "ข้าวผัดไข่", "calories": 320, "description": "ข้าวสวย 2 ถ้วย ไข่ 2 ฟอง ต้นหอม ซีอิ๊วขาว พริกไทย", "emoji": "🍚", "ingredients": ["ข้าวสวย", "ไข่", "ต้นหอม", "ซีอิ๊วขาว", "พริกไทย", "น้ำมันพืช"], "missing": ["ข้าวสวย", "ต้นหอม"]},
    {"name": "ไข่เจียวหมูสับ", "calories": 280, "description": "ไข่ 3 ฟอง หมูสับ 100g ต้นหอมซอย น้ำปลา พริกไทย", "emoji": "🍳", "ingredients": ["ไข่", "หมูสับ", "ต้นหอม", "น้ำปลา", "พริกไทย", "น้ำมันพืช"], "missing": ["หมูสับ", "ต้นหอม"]},
    {"name": "ผัดผักรวมมิตร", "calories": 150, "description": "ผักรวม 300g กระเทียม ซอสหอยนางรม น้ำมันหอย", "emoji": "🥬", "ingredients": ["ผักรวม", "กระเทียม", "ซอสหอยนางรม", "น้ำมันพืช"], "missing": ["ผักรวม", "ซอสหอยนางรม"]},
    {"name": "ยำไข่ต้ม", "calories": 220, "description": "ไข่ต้ม 3 ฟอง หอมใหญ่ พริก มะนาว น้ำปลา ผักชี", "emoji": "🥗", "ingredients": ["ไข่", "หอมใหญ่", "พริก", "มะนาว", "น้ำปลา", "ผักชี"], "missing": ["มะนาว", "หอมใหญ่", "ผักชี"]},
    {"name": "ก๋วยเตี๋ยวน้ำใสหมู", "calories": 300, "description": "เส้นหมี่ 200g หมูเด้ง หมูสับ ถั่วงอก ผักชี ต้นหอม", "emoji": "🍜", "ingredients": ["เส้นหมี่", "หมูเด้ง", "หมูสับ", "ถั่วงอก", "ผักชี", "ต้นหอม"], "missing": ["เส้นหมี่", "ถั่วงอก", "ผักชี"]}
]

@app.post("/suggest")
async def suggest_recipes(req: SuggestRequest):
    prompt = f"""วัตถุดิบในครัว: {req.ingredients}
อุปกรณ์ที่มีให้ใช้: {req.tools}
วิธีปรุงที่ต้องการ: {req.method}
หมายเหตุเพิ่มเติม: {req.notes}

แนะนำเมนูที่ใช้อุปกรณ์เท่าที่มี"""
    system = """You are Bingus Chef, a realistic Thai home cook. Recommend ONLY dishes that can ACTUALLY BE MADE with the user's available tools and ingredients.

TOOL-FIRST RULES (MOST IMPORTANT):
- Analyze tools FIRST. If user has only กระทะ + เตา → only stir-fry, deep-fry, fried rice dishes.
- If user has หม้อ → soups, curries, boiled dishes.
- If user has หม้อหุงข้าว → rice dishes, steamed dishes.
- If user has NO heat source → cold dishes only (ยำ, น้ำตก, ลาบ — no cooking required).
- NEVER suggest a dish that requires heat if user has no stove/fire.
- NEVER suggest a dish that requires an oven if user has none.
- If tools are very limited, suggest fewer dishes (even 1-2 is fine) rather than forcing unrealistic suggestions.

INGREDIENT RULES:
- Base on ingredients user has. Simple ingredients = simple dishes.
- "missing" = minimal extra ingredients needed. Keep it short.

OUTPUT: up to 5 suggestions, but can be fewer if tools are limited.
Output ONLY valid JSON. No markdown, no code blocks.
{"suggestions": [
  {"name": "ผัดกระเพราไก่", "calories": 350, "description": "ไก่ 200g กระเทียม พริก ใบกระเพรา ซอสปรุงรส", "emoji": "🍳", "ingredients": ["เนื้อไก่", "กระเทียม", "พริก", "ใบกระเพรา", "ซอสปรุงรส", "น้ำปลา", "น้ำตาล"], "missing": ["ใบกระเพรา"]}
]}"""
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
    prompt = f"""เมนู: {req.name}
วัตถุดิบที่มี: {req.ingredients}
อุปกรณ์ที่มีให้ใช้: {req.tools}
วิธีปรุง: {req.method}
หมายเหตุ: {req.notes}

ให้สูตรละเอียดของเมนูนี้ ใช้ได้จริง ทำตามได้จริง"""
    system = """You are Bingus Chef, a realistic Thai home cook. Give a detailed recipe that ACTUALLY WORKS in a real kitchen.

REALISM RULES:
- Only include ingredients and steps that make sense for this specific dish. Don't add random extras.
- Quantities must be realistic (e.g. น้ำปลา 2 tbsp for a stir-fry, not 1 tsp or 1 cup).
- CHECK user's tools. Only include steps that use tools the user HAS. No heat source → only cold-prep steps.
- NEVER reference a tool the user doesn't have (e.g. don't say "เปิดเตาอบ" if no oven, don't say "ตั้งกระทะ" if no stove).
- Steps must follow real cooking order and technique for this Thai dish.
- "ingredients": complete list of every ingredient needed, with quantities.
- prep_steps = preparing ingredients with exact quantities (e.g. "หั่นหมู 200g เป็นชิ้นบาง", "ตำพริกกระเทียม 3-4 เม็ด")
- cook_steps = actual cooking process (heat, fry, boil, season, plate)
- timer = minutes. 0 means no timer needed. Only set timer if that step genuinely needs waiting (boiling, simmering, steaming).
- nutrition = realistic values for this dish
- missing_ingredients = what user needs to buy, keep it real

Output ONLY valid JSON. No markdown, no code blocks.
{
  "name": "ผัดกระเพราไก่",
  "description": "เมนูผัดกระเพราไก่ ใช้ไก่ 200g กระเทียม พริก ใบกระเพรา ซอสปรุงรส",
  "nutrition": {"protein": 28, "carbs": 10, "fat": 22, "fiber": 2, "calories": 350},
  "ingredients": ["เนื้อไก่ 200g", "กระเทียม 5 กลีบ", "พริก 3-4 เม็ด", "ใบกระเพรา", "น้ำปลา 1 tbsp", "ซีอิ๊วขาว 1 tbsp", "น้ำตาล 1/2 tsp", "น้ำมันพืช"],
  "prep_steps": [
    {"text": "หั่นเนื้อไก่ 200g เป็นชิ้นพอคำ", "timer": 0},
    {"text": "ตำกระเทียม 5 กลีบ + พริก 3-4 เม็ด", "timer": 0}
  ],
  "cook_steps": [
    {"text": "ตั้งกระทะ ใส่น้ำมัน 1 tbsp ผัดกระเทียมพริกให้หอม", "timer": 0},
    {"text": "ใส่ไก่ ผัดจนสุก ประมาณ 3 นาที", "timer": 3},
    {"text": "ปรุงรสด้วยน้ำปลา 1 tbsp ซีอิ๊วขาว 1 tbsp น้ำตาล 1/2 tsp", "timer": 0},
    {"text": "ใส่ใบกระเพรา ผัดเร็วๆ ปิดไฟ", "timer": 0}
  ],
  "missing_ingredients": ["ใบกระเพรา"]
}"""
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
    ctx = req.context or {}
    context_str = f"กำลังทำ: {ctx.get('recipe_name', '')}, ขั้นตอนปัจจุบัน: {ctx.get('current_step', '')}"
    messages = [
        {"role": "system", "content": f"คุณคือ Bingus Chef พ่อครัวแมวน้อย ขี้เล่น เป็นกันเอง ตอบสั้นๆ ภาษาไทย ไม่เกิน 3-4 ประโยค ให้คำแนะนำการทำอาหารที่ใช้ได้จริง เหมาะสมกับเมนูนั้นๆ\n{context_str}"}
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
        return {"reply": "เหมียว! บิงกัสขอโทษ อิ้งฉ่อยมีปัญหา แก้ไขก่อนนะ 🐾"}

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
    defaults = {"tools": [], "pantry": ["เกลือ", "พริกไทย", "น้ำปลา", "น้ำตาล", "น้ำมันพืช", "ซีอิ๊วขาว", "ซอสหอยนางรม", "ผงปรุงรส", "กระเทียม", "หอมแดง"]}
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
