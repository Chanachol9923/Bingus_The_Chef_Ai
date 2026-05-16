# Bingus Chef

AI cooking assistant — แนะนำเมนูจากวัตถุดิบที่คุณมี พร้อมขั้นตอนละเอียด จับเวลา และแกลเลอรี

## Features

- **Find Recipes** — Pick your ingredients + cooking method, AI suggests real recipes
- **Detailed Steps** — Separated prep / cook steps with built-in timers
- **Adjust Recipe** — Missing ingredients? Tap to have AI adjust
- **Gallery** — Save and browse your completed recipes
- **Dashboard** — Nutrition stats, calorie chart per meal
- **Bingus Chat** — Chat with the cute cat cooking assistant
- **Bilingual** — Switch between English and Thai anytime

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3 + Tailwind CSS + Chart.js (single HTML file) |
| Backend | FastAPI (Python) |
| AI | Typhoon v2.5 (OpenAI-compatible API) |
| Database | SQLite |
| Deploy | Vercel (serverless) |

## How to Run

### Prerequisites
- Python 3.10+
- pip

### 1. Clone
```bash
git clone https://github.com/Chanachol9923/Bingus_The_Chef_Ai.git
cd Bingus_The_Chef_Ai
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the server
```bash
python main.py
```

Server starts at `http://localhost:5000`

### 4. Open in browser
Go to `http://localhost:5000`

### (Optional) Run metrics
```bash
python metrics.py                    # test local server
python metrics.py --url https://your-deployed-url.vercel.app  # test deployed
```

Measures JSON parsing rate, recipe adherence, and API response latency across 10 test scenarios (100 iterations).

## Deploy on Vercel

```bash
npm i -g vercel
vercel --prod
```

Set environment variable `TYPHOON_API_KEY` (optional — a default key is bundled for demo).

**Note:** Gallery / Kitchen data is stored in SQLite (`/tmp`) which is ephemeral on Vercel serverless. Data is backed up in browser's localStorage.

## Project Structure

```
Bingus_The_Chef_Ai/
├── main.py            # FastAPI backend — all API routes, DB, AI integration
├── index.html         # Vue 3 + Tailwind + Chart.js frontend (single file)
├── metrics.py         # Reliability tester
├── api/index.py       # Vercel serverless entry point
├── vercel.json        # Vercel deployment config
├── requirements.txt   # Python dependencies
├── BingusProf.jpg     # AI assistant profile picture
└── uploads/           # Uploaded food photos
```
