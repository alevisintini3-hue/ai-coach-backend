"""
backend_api.py
───────────────
Server FastAPI che gestisce tutto il coaching AI.
Scarica dati Garmin, analizza con Claude, serve l'app mobile.

Esegui con: uvicorn backend_api:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from garminconnect import Garmin
import anthropic
from collections import defaultdict
import json

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Triathlon Coach API",
    description="Backend per l'app mobile del coach di triathlon",
    version="1.0.0"
)

# Abilita CORS per l'app mobile
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In produzione, specifica i domini
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# MODELLI PYDANTIC
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Login con credenziali Garmin"""
    email: str
    password: str

class ChatMessage(BaseModel):
    """Messaggio dal frontend"""
    message: str
    garmin_email: str  # Per identificare l'utente

class ActivitySummary(BaseModel):
    """Sommario di un'attività"""
    data: str
    sport: str
    nome: str
    distanza_km: float
    durata_min: float
    fc_media: Optional[float] = None
    calorie: Optional[float] = None

class PerformanceSummary(BaseModel):
    """Sommario delle performance"""
    sport: str
    count: int
    total_distance_km: float
    total_duration_hours: float
    avg_hr: Optional[float]
    max_hr: int
    attivita_recenti: List[ActivitySummary]

# ─────────────────────────────────────────────────────────────────────────────
# CACHE GLOBALE (in produzione, usare Redis)
# ─────────────────────────────────────────────────────────────────────────────

user_sessions = {}  # {email: {"garmin": Garmin(), "last_sync": datetime, "metriche": {...}}}

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI AUSILIARIE
# ─────────────────────────────────────────────────────────────────────────────

def login_garmin() -> Garmin:
    """Login automatico usando il file .env"""

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email:
        raise Exception("GARMIN_EMAIL non trovato nel .env")

    if not password:
        raise Exception("GARMIN_PASSWORD non trovato nel .env")

    token_store = os.path.expanduser("~/.garminconnect")

    garmin = Garmin(
        email=email,
        password=password,
        is_cn=False
    )

    garmin.login(token_store)

    return garmin

def fetch_and_analyze_activities(garmin: Garmin) -> dict:
    """Scarica e analizza le attività da Garmin"""
    
    print("⏳ Scaricando attività...")
    
    attivita_totali = []
    offset = 0
    while True:
        batch = garmin.get_activities(offset, 100)
        if not batch:
            break
        attivita_totali.extend(batch)
        offset += 100
    
    print(f"✓ Scaricate {len(attivita_totali)} attività")
    
    # Analizza
    metriche_sport = defaultdict(lambda: {
        "count": 0,
        "total_distance_m": 0,
        "total_duration_sec": 0,
        "avg_hr": [],
        "max_hr": 0,
        "total_calories": 0,
        "attivita": [],
    })
    
    for activity in attivita_totali[:50]:  # Ultimi 50
        sport_type = activity.get("activityType", {}).get("typeKey", "unknown")
        distance_m = activity.get("distance", 0) or 0
        duration_sec = activity.get("duration", 0) or 0
        avg_hr = activity.get("averageHR", 0) or 0
        max_hr = activity.get("maxHR", 0) or 0
        calories = activity.get("calories", 0) or 0
        start_time = activity.get("startTimeLocal", "")
        
        metriche_sport[sport_type]["count"] += 1
        metriche_sport[sport_type]["total_distance_m"] += distance_m
        metriche_sport[sport_type]["total_duration_sec"] += duration_sec
        if avg_hr > 0:
            metriche_sport[sport_type]["avg_hr"].append(avg_hr)
        metriche_sport[sport_type]["max_hr"] = max(metriche_sport[sport_type]["max_hr"], max_hr)
        metriche_sport[sport_type]["total_calories"] += calories
        
        metriche_sport[sport_type]["attivita"].append({
            "data": start_time.split("T")[0] if "T" in start_time else start_time,
            "nome": activity.get("activityName", ""),
            "distanza_km": distance_m / 1000,
            "durata_min": duration_sec / 60,
            "fc_media": avg_hr,
            "calorie": calories,
        })
    
    return dict(metriche_sport)

def build_performance_context(metriche_sport: dict) -> str:
    """Costruisce il testo del contesto di performance"""
    
    context = "=== LE TUE PERFORMANCE ===\n\n"
    
    for sport, metriche in sorted(metriche_sport.items()):
        if metriche["count"] == 0:
            continue
        
        context += f"{sport.upper()}:\n"
        context += f"  • {metriche['count']} allenamenti\n"
        context += f"  • {metriche['total_distance_m']/1000:.1f}km totali\n"
        context += f"  • {metriche['total_duration_sec']/3600:.1f}h totali\n"
        
        if metriche['avg_hr']:
            fc_media = sum(metriche['avg_hr']) / len(metriche['avg_hr'])
            context += f"  • FC media: {fc_media:.0f}bpm\n"
        context += f"  • Calorie: {metriche['total_calories']:.0f}\n"
        
        context += f"  • Ultimi allenamenti:\n"
        for att in metriche["attivita"][:3]:
            context += (
                f"    - {att['data']}: {att['nome']} "
                f"({att['distanza_km']:.2f}km, {att['durata_min']:.0f}min, "
                f"FC {att['fc_media']:.0f}bpm)\n"
            )
        
        context += "\n"
    
    return context

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "online",
        "message": "🏊 🚴 🏃 AI Coach API is running",
        "endpoints": [
            "POST /login — Login con Garmin",
            "GET /status/{email} — Status della sessione",
            "POST /chat — Invia un messaggio al coach",
        ]
    }

@app.post("/login")
async def login(request: LoginRequest):
    """
    Login e caricamento iniziale dei dati Garmin.
    
    Esempio:
    ```
    POST /login
    {
        "email": "tua@email.com",
        "password": "tuapassword"
    }
    ```
    """
    try:
        email = request.email
        
        # Se è già loggato, salta
        if email in user_sessions:
            return {
                "status": "already_logged_in",
                "email": email,
                "message": "Sessione già attiva"
            }
        
        # Login a Garmin
        print(f"🔐 Login per {email}...")
        garmin = login_garmin()
        
        # Scarica e analizza attività
        metriche = fetch_and_analyze_activities(garmin)
        
        # Salva in sessione
        user_sessions[email] = {
            "garmin": garmin,
            "metriche": metriche,
            "last_sync": datetime.now(),
        }
        
        return {
            "status": "success",
            "email": email,
            "message": f"Login riuscito! Caricate {sum(m['count'] for m in metriche.values())} attività",
            "activities_count": sum(m['count'] for m in metriche.values()),
        }
    
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Login fallito: {str(e)}")

@app.get("/status/{email}")
async def status(email: str):

    print("EMAIL RICHIESTA:", repr(email))
    print("SESSIONI PRESENTI:", repr(list(user_sessions.keys())))

    if email not in user_sessions:
        raise HTTPException(
            status_code=401,
            detail="Non loggato. Chiama /login prima"
        )
    
    session = user_sessions[email]
    metriche = session["metriche"]
    
    return {
        "status": "active",
        "email": email,
        "last_sync": session["last_sync"].isoformat(),
        "sports": list(metriche.keys()),
        "total_activities": sum(m["count"] for m in metriche.values()),
    }

@app.post("/chat")
async def chat(request: ChatMessage):
    """
    Invia un messaggio al coach.
    
    Esempio:
    ```
    POST /chat
    {
        "message": "Come stanno i miei allenamenti di corsa?",
        "garmin_email": "tua@email.com"
    }
    ```
    """
    
    email = request.garmin_email
    
    if email not in user_sessions:
        raise HTTPException(status_code=401, detail="Non loggato. Chiama /login prima")
    
    session = user_sessions[email]
    metriche = session["metriche"]
    
    # Costruisci il contesto
    context = build_performance_context(metriche)
    
    # System prompt del coach
    system_prompt = """Sei un coach esperto di triathlon che allena Alessandro.

Hai accesso ai VERI dati di performance:
- Tutte le attività completate (distanza, durata, FC, calorie)
- Storie di training nel tempo

ISTRUZIONI:
1. Usa i dati reali per consigli specifici
2. Cita i numeri concreti (distanze, tempi, FC)
3. Sii motivante e costruttivo
4. Suggerisci aggiustamenti basati sui dati reali
5. Parla SEMPRE in italiano"""
    
    # Manda a Claude
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    full_message = f"{context}\n\nDomanda di Alessandro: {request.message}"
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system_prompt,
            messages=[
                {"role": "user", "content": full_message}
            ]
        )
        
        coach_response = response.content[0].text
        
        return {
            "status": "success",
            "message": coach_response,
            "timestamp": datetime.now().isoformat(),
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore API: {str(e)}")

@app.get("/sync/{email}")
async def manual_sync(email: str):
    """Sincronizza manualmente i dati Garmin"""
    
    if email not in user_sessions:
        raise HTTPException(status_code=401, detail="Non loggato")
    
    session = user_sessions[email]
    
    # Ri-scarica
    metriche = fetch_and_analyze_activities(session["garmin"])
    session["metriche"] = metriche
    session["last_sync"] = datetime.now()
    
    return {
        "status": "synced",
        "email": email,
        "timestamp": session["last_sync"].isoformat(),
        "total_activities": sum(m["count"] for m in metriche.values()),
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 80)
    print("🏊 🚴 🏃  AI COACH API")
    print("=" * 80)
    print("\n🚀 Avvio server su http://localhost:8000")
    print("📖 Documentazione: http://localhost:8000/docs\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
