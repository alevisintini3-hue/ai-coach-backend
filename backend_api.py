"""
backend_api.py - v3
Single-user AI Triathlon Coach backend
Novità: endpoint /activities, contesto più ricco per Claude
"""

from fastapi import FastAPI, HTTPException, Query
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
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# MODELLI
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str

# ─────────────────────────────────────────────────────────────────────────────
# SESSIONE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────

user_session = None  # contiene garmin, metriche, attivita_raw, last_sync

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI
# ─────────────────────────────────────────────────────────────────────────────

def login_garmin() -> Garmin:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise Exception("GARMIN_EMAIL/GARMIN_PASSWORD mancanti")
    garmin = Garmin(email=email, password=password, is_cn=False)
    garmin.login(os.path.expanduser("~/.garminconnect"))
    return garmin


def fetch_activities(garmin: Garmin) -> tuple[list, dict]:
    """
    Scarica tutte le attività e ritorna:
    - attivita_raw: lista completa delle attività normalizzate
    - metriche_sport: dizionario aggregato per sport
    """
    print("Scaricando attività Garmin...")

    raw = []
    offset = 0
    while True:
        batch = garmin.get_activities(offset, 100)
        if not batch:
            break
        raw.extend(batch)
        offset += 100

    print(f"Scaricate {len(raw)} attività totali")

    # Normalizza
    attivita_raw = []
    metriche_sport = defaultdict(lambda: {
        "count": 0,
        "total_distance_m": 0,
        "total_duration_sec": 0,
        "avg_hr_values": [],
        "max_hr": 0,
        "total_calories": 0,
        "attivita": [],
    })

    for a in raw:
        sport = a.get("activityType", {}).get("typeKey", "unknown")
        start_time = a.get("startTimeLocal", "")
        distance_m = a.get("distance", 0) or 0
        duration_sec = a.get("duration", 0) or 0
        avg_hr = a.get("averageHR", 0) or 0
        max_hr = a.get("maxHR", 0) or 0
        calories = a.get("calories", 0) or 0

        # Calcola pace
        if distance_m > 0 and duration_sec > 0:
            pace_sec_km = duration_sec / (distance_m / 1000)
            m, s = divmod(int(pace_sec_km), 60)
            pace_str = f"{m}:{s:02d}/km"
        else:
            pace_str = None

        # Durata formattata
        h, rem = divmod(int(duration_sec), 3600)
        mn, sc = divmod(rem, 60)
        duration_str = f"{h}:{mn:02d}:{sc:02d}"

        activity = {
            "data": start_time.split("T")[0] if "T" in start_time else start_time,
            "ora": start_time.split("T")[1][:5] if "T" in start_time else "",
            "sport": sport,
            "nome": a.get("activityName", ""),
            "distanza_km": round(distance_m / 1000, 2),
            "durata_min": round(duration_sec / 60, 1),
            "durata_str": duration_str,
            "fc_media": avg_hr if avg_hr > 0 else None,
            "fc_max": max_hr if max_hr > 0 else None,
            "calorie": calories if calories > 0 else None,
            "pace": pace_str,
            "garmin_id": a.get("activityId"),
        }

        attivita_raw.append(activity)

        # Aggiorna metriche
        m = metriche_sport[sport]
        m["count"] += 1
        m["total_distance_m"] += distance_m
        m["total_duration_sec"] += duration_sec
        if avg_hr > 0:
            m["avg_hr_values"].append(avg_hr)
        m["max_hr"] = max(m["max_hr"], max_hr)
        m["total_calories"] += calories
        m["attivita"].append(activity)

    return attivita_raw, dict(metriche_sport)


def build_context_for_claude(metriche_sport: dict, attivita_raw: list) -> str:
    """Costruisce un contesto ricco per Claude con metriche + ultime attività."""

    context = "=== PROFILO ATLETA ===\n"
    context += "Nome: Alessandro\n"
    context += "Paese: Germania\n"
    context += "Obiettivo: Triathlon olimpico\n"
    context += "Baseline: nuoto 2km/40min, corsa 12km a 5:40/km\n\n"

    context += "=== STATISTICHE PER SPORT ===\n\n"
    for sport, m in sorted(metriche_sport.items()):
        if m["count"] == 0:
            continue
        avg_hr = (
            sum(m["avg_hr_values"]) / len(m["avg_hr_values"])
            if m["avg_hr_values"] else None
        )
        context += f"{sport.upper()}:\n"
        context += f"  Allenamenti totali: {m['count']}\n"
        context += f"  Distanza totale: {m['total_distance_m']/1000:.1f} km\n"
        context += f"  Ore totali: {m['total_duration_sec']/3600:.1f} h\n"
        context += f"  FC media: {avg_hr:.0f} bpm\n" if avg_hr else ""
        context += f"  FC massima: {m['max_hr']} bpm\n" if m["max_hr"] else ""
        context += f"  Calorie totali: {m['total_calories']:.0f}\n"

        context += "  Ultimi 5 allenamenti:\n"
        for att in m["attivita"][:5]:
            context += (
                f"    • {att['data']}: {att['nome']} | "
                f"{att['distanza_km']}km | {att['durata_str']} | "
                f"FC {att['fc_media']}bpm | pace {att['pace']}\n"
            )
        context += "\n"

    return context


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "version": "3.0.0"}


@app.post("/login")
async def login():
    global user_session

    if user_session is not None:
        return {
            "status": "already_logged_in",
            "total_activities": sum(
                m["count"] for m in user_session["metriche"].values()
            )
        }

    garmin = login_garmin()
    attivita_raw, metriche = fetch_activities(garmin)

    user_session = {
        "email": os.getenv("GARMIN_EMAIL"),
        "garmin": garmin,
        "metriche": metriche,
        "attivita_raw": attivita_raw,
        "last_sync": datetime.now(),
    }

    return {
        "status": "success",
        "total_activities": len(attivita_raw),
        "sports": list(metriche.keys()),
    }


@app.get("/status")
async def status():
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    return {
        "status": "active",
        "email": user_session["email"],
        "last_sync": user_session["last_sync"].isoformat(),
        "sports": list(user_session["metriche"].keys()),
        "total_activities": len(user_session["attivita_raw"]),
    }


@app.get("/activities")
async def get_activities(
    sport: Optional[str] = Query(None, description="Filtra per sport (es: running)"),
    limit: int = Query(50, description="Numero massimo di attività da ritornare"),
):
    """
    Ritorna la lista delle attività con filtro opzionale per sport.
    
    Esempi:
    - GET /activities             → tutte le attività
    - GET /activities?sport=running  → solo le corse
    - GET /activities?limit=10    → ultime 10
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    attivita = user_session["attivita_raw"]

    # Filtra per sport
    if sport:
        attivita = [a for a in attivita if a["sport"].lower() == sport.lower()]

    # Limita
    attivita = attivita[:limit]

    return {
        "total": len(attivita),
        "sport_filter": sport,
        "activities": attivita,
    }


@app.get("/sync")
async def sync():
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    attivita_raw, metriche = fetch_activities(user_session["garmin"])
    user_session["attivita_raw"] = attivita_raw
    user_session["metriche"] = metriche
    user_session["last_sync"] = datetime.now()

    return {
        "status": "synced",
        "total_activities": len(attivita_raw),
        "last_sync": user_session["last_sync"].isoformat(),
    }


@app.post("/chat")
async def chat(request: ChatMessage):
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    # Contesto ricco per Claude
    context = build_context_for_claude(
        user_session["metriche"],
        user_session["attivita_raw"],
    )

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="""Sei un coach esperto di triathlon che allena Alessandro.
Hai accesso ai VERI dati Garmin: attività completate, distanze, FC, pace.
Rispondi SEMPRE in italiano.
Sii specifico: cita i numeri reali che vedi.
Sii costruttivo e motivante.""",
        messages=[{
            "role": "user",
            "content": f"{context}\n\nDomanda di Alessandro: {request.message}"
        }]
    )

    return {
        "status": "success",
        "message": response.content[0].text,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
