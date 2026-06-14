"""
backend_api_v2.py
Single-user AI Triathlon Coach backend
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime
from dotenv import load_dotenv
from garminconnect import Garmin
import anthropic
from collections import defaultdict

load_dotenv()

app = FastAPI(
    title="AI Triathlon Coach API",
    description="Single-user backend",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    message: str

class ActivitySummary(BaseModel):
    data: str
    sport: str
    nome: str
    distanza_km: float
    durata_min: float
    fc_media: Optional[float] = None
    calorie: Optional[float] = None

user_session = None

def login_garmin() -> Garmin:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        raise Exception("GARMIN_EMAIL/GARMIN_PASSWORD mancanti nel .env")

    token_store = os.path.expanduser("~/.garminconnect")

    garmin = Garmin(email=email, password=password, is_cn=False)
    garmin.login(token_store)
    return garmin

def fetch_and_analyze_activities(garmin: Garmin) -> dict:
    attivita_totali = []
    offset = 0

    while True:
        batch = garmin.get_activities(offset, 100)
        if not batch:
            break
        attivita_totali.extend(batch)
        offset += 100

    metriche_sport = defaultdict(lambda: {
        "count": 0,
        "total_distance_m": 0,
        "total_duration_sec": 0,
        "avg_hr": [],
        "max_hr": 0,
        "total_calories": 0,
        "attivita": [],
    })

    for activity in attivita_totali[:50]:
        sport_type = activity.get("activityType", {}).get("typeKey", "unknown")
        distance_m = activity.get("distance", 0) or 0
        duration_sec = activity.get("duration", 0) or 0
        avg_hr = activity.get("averageHR", 0) or 0
        max_hr = activity.get("maxHR", 0) or 0
        calories = activity.get("calories", 0) or 0
        start_time = activity.get("startTimeLocal", "")

        m = metriche_sport[sport_type]
        m["count"] += 1
        m["total_distance_m"] += distance_m
        m["total_duration_sec"] += duration_sec
        if avg_hr > 0:
            m["avg_hr"].append(avg_hr)
        m["max_hr"] = max(m["max_hr"], max_hr)
        m["total_calories"] += calories

        m["attivita"].append({
            "data": start_time.split("T")[0] if "T" in start_time else start_time,
            "nome": activity.get("activityName", ""),
            "distanza_km": distance_m / 1000,
            "durata_min": duration_sec / 60,
            "fc_media": avg_hr,
            "calorie": calories,
        })

    return dict(metriche_sport)

def build_performance_context(metriche_sport: dict) -> str:
    context = "=== LE TUE PERFORMANCE ===\n\n"

    for sport, metriche in sorted(metriche_sport.items()):
        context += f"{sport.upper()}:\n"
        context += f"- Allenamenti: {metriche['count']}\n"
        context += f"- Distanza: {metriche['total_distance_m']/1000:.1f} km\n"
        context += f"- Durata: {metriche['total_duration_sec']/3600:.1f} h\n\n"

    return context

@app.get("/")
async def root():
    return {"status": "online", "version": "2.0.0"}

@app.post("/login")
async def login():
    global user_session

    if user_session is not None:
        return {"status": "already_logged_in"}

    garmin = login_garmin()
    metriche = fetch_and_analyze_activities(garmin)

    user_session = {
        "email": os.getenv("GARMIN_EMAIL"),
        "garmin": garmin,
        "metriche": metriche,
        "last_sync": datetime.now(),
    }

    return {
        "status": "success",
        "activities_count": sum(m["count"] for m in metriche.values())
    }

@app.get("/status")
async def status():
    global user_session

    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    metriche = user_session["metriche"]

    return {
        "status": "active",
        "email": user_session["email"],
        "last_sync": user_session["last_sync"].isoformat(),
        "sports": list(metriche.keys()),
        "total_activities": sum(m["count"] for m in metriche.values())
    }

@app.get("/sync")
async def sync():
    global user_session

    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    metriche = fetch_and_analyze_activities(user_session["garmin"])

    user_session["metriche"] = metriche
    user_session["last_sync"] = datetime.now()

    return {
        "status": "synced",
        "total_activities": sum(m["count"] for m in metriche.values())
    }

@app.post("/chat")
async def chat(request: ChatMessage):
    global user_session

    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    context = build_performance_context(user_session["metriche"])

    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY")
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"{context}\n\nDomanda: {request.message}"
        }]
    )

    return {
        "status": "success",
        "message": response.content[0].text
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
