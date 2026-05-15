# 🐱 Bingus Chef

AI cooking assistant — AI suggests recipes from your ingredients, with detailed steps, timers, and a gallery.

## Features

- **🍳 Find Recipes** — Pick your ingredients + cooking method → AI suggests real recipes
- **📋 Detailed Steps** — Separated prep / cook steps with built-in timers
- **🛒 Adjust Recipe** — Missing ingredients? Tap to have AI adjust the recipe
- **🖼️ Gallery** — Save and browse your completed recipes
- **📊 Dashboard** — Nutrition stats, calorie chart per meal
- **🐱 Bingus Chat** — Chat with the cute cat cooking assistant

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3 + Tailwind CSS + Chart.js (single HTML) |
| Backend | FastAPI (Python) |
| AI | Typhoon v2.5 (OpenAI-compatible API) |
| Database | SQLite |
| Deploy | Vercel (serverless) |

## Run Locally

```bash
# Install dependencies
pip install fastapi openai python-multipart

# Run
python main.py
```

Open `http://localhost:5000`

## Deploy on Vercel

```bash
npm i -g vercel
vercel --prod
```

Set Environment Variable: `TYPHOON_API_KEY` (optional, a default key is provided)

### Vercel Limitations
- Gallery / Kitchen data is lost when the instance is recycled (serverless)
- Uploaded images are not persisted
- For persistence → switch to PostgreSQL or Vercel KV
