# 🐱 Bingus Chef

ผู้ช่วยทำอาหาร AI ภาษาไทย — ให้ AI แนะนำเมนูจากวัตถุดิบที่มี พร้อมขั้นตอนละเอียด จับเวลา และแกลเลอรี่

## Features

- **🍳 ค้นหาเมนู** — เลือกวัตถุดิบที่มี + วิธีทำ → AI เสนอเมนูที่ทำได้จริง
- **📋 ขั้นตอนละเอียด** — แยกเตรียมวัตถุดิบ / ขั้นตอนทำ มีจับเวลาในตัว
- **🛒 ปรับสูตร** — ถ้าวัตถุดิบไม่ครบ กดปรับสูตรให้ AI คิดใหม่
- **🖼️ แกลเลอรี่** — บันทึกเมนูที่ทำแล้ว ดูย้อนหลัง
- **📊 Dashboard** — สถิติสารอาหาร แคลอรี่แต่ละเมนู
- **🐱 Bingus Chat** — พูดคุยกับแมวน้อยผู้ช่วยทำอาหาร

## Tech Stack

| ชั้น | เทคโนโลยี |
|------|-----------|
| Frontend | Vue 3 + Tailwind CSS + Chart.js (single HTML) |
| Backend | FastAPI (Python) |
| AI | Typhoon v2.5 (OpenAI-compatible API) |
| Database | SQLite |
| Deploy | Vercel (serverless) |

## รัน Local

```bash
# ติดตั้ง dependencies
pip install fastapi openai python-multipart

# รัน
python main.py
```

เปิด `http://localhost:5000`

## Deploy บน Vercel

```bash
npm i -g vercel
vercel --prod
```

ตั้ง Environment Variable: `TYPHOON_API_KEY` (ไม่ต้องตั้งก็ได้ มี key default ให้)

### ข้อจำกัดบน Vercel
- ข้อมูล Gallery / Kitchen จะหายเมื่อ instance ถูกปิด (serverless)
- รูปที่อัปโหลดจะไม่คงอยู่
- ถ้าต้องการ persistent → เปลี่ยนไปใช้ PostgreSQL หรือ Vercel KV
