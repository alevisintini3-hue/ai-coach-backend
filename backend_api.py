"""
backend_api.py - v5
Novità: chat con flusso di conferma per creare allenamenti
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime, date
from dotenv import load_dotenv
from garminconnect import Garmin
import anthropic
from collections import defaultdict
import json

load_dotenv()

app = FastAPI(title="AI Triathlon Coach API", version="5.0.0")

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
    conversation_id: Optional[str] = "default"

class WorkoutStep(BaseModel):
    type: str
    duration_seconds: Optional[int] = None
    distance_meters: Optional[float] = None
    description: Optional[str] = None
    repeat_count: Optional[int] = None
    repeat_steps: Optional[List[dict]] = None

class CreateWorkoutRequest(BaseModel):
    name: str
    sport: str
    scheduled_date: str
    steps: List[WorkoutStep]
    description: Optional[str] = None
    pool_length: Optional[int] = 50

class AIWorkoutRequest(BaseModel):
    description: str
    sport: str
    scheduled_date: str
    duration_minutes: Optional[int] = 60

class ConfirmWorkoutRequest(BaseModel):
    conversation_id: Optional[str] = "default"

# ─────────────────────────────────────────────────────────────────────────────
# SESSIONE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────

user_session = None

# Stato della conversazione per ogni session_id
# Struttura: { "default": { "pending_workout": {...}, "history": [...] } }
conversation_states = {}

# ─────────────────────────────────────────────────────────────────────────────
# GARMIN HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def login_garmin() -> Garmin:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise Exception("GARMIN_EMAIL/GARMIN_PASSWORD mancanti")
    garmin = Garmin(email=email, password=password, is_cn=False)
    garmin.login(os.path.expanduser("~/.garminconnect"))
    return garmin


def fetch_activities(garmin: Garmin) -> tuple:
    raw = []
    offset = 0
    while True:
        batch = garmin.get_activities(offset, 100)
        if not batch:
            break
        raw.extend(batch)
        offset += 100

    attivita_raw = []
    metriche_sport = defaultdict(lambda: {
        "count": 0, "total_distance_m": 0, "total_duration_sec": 0,
        "avg_hr_values": [], "max_hr": 0, "total_calories": 0, "attivita": [],
    })

    for a in raw:
        sport = a.get("activityType", {}).get("typeKey", "unknown")
        start_time = a.get("startTimeLocal", "")
        distance_m = a.get("distance", 0) or 0
        duration_sec = a.get("duration", 0) or 0
        avg_hr = a.get("averageHR", 0) or 0
        max_hr = a.get("maxHR", 0) or 0
        calories = a.get("calories", 0) or 0

        if distance_m > 0 and duration_sec > 0:
            pace_sec_km = duration_sec / (distance_m / 1000)
            m, s = divmod(int(pace_sec_km), 60)
            pace_str = f"{m}:{s:02d}/km"
        else:
            pace_str = None

        h, rem = divmod(int(duration_sec), 3600)
        mn, sc = divmod(rem, 60)

        activity = {
            "data": start_time.split("T")[0] if "T" in start_time else start_time,
            "sport": sport,
            "nome": a.get("activityName", ""),
            "distanza_km": round(distance_m / 1000, 2),
            "durata_min": round(duration_sec / 60, 1),
            "durata_str": f"{h}:{mn:02d}:{sc:02d}",
            "fc_media": avg_hr if avg_hr > 0 else None,
            "fc_max": max_hr if max_hr > 0 else None,
            "calorie": calories if calories > 0 else None,
            "pace": pace_str,
            "garmin_id": a.get("activityId"),
        }
        attivita_raw.append(activity)

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
    context = "=== PROFILO ATLETA ===\n"
    context += "Nome: Alessandro | Paese: Germania\n"
    context += "Obiettivo: Triathlon olimpico\n"
    context += "Baseline: nuoto 2km/40min, corsa 12km a 5:40/km\n"
    context += f"Data oggi: {date.today().isoformat()}\n\n"
    context += "=== STATISTICHE PER SPORT ===\n\n"

    for sport, m in sorted(metriche_sport.items()):
        if m["count"] == 0:
            continue
        avg_hr = sum(m["avg_hr_values"]) / len(m["avg_hr_values"]) if m["avg_hr_values"] else None
        context += f"{sport.upper()}: {m['count']} sessioni | "
        context += f"{m['total_distance_m']/1000:.1f}km totali | "
        context += f"{m['total_duration_sec']/3600:.1f}h totali"
        if avg_hr:
            context += f" | FC media {avg_hr:.0f}bpm"
        context += "\n"
        for att in m["attivita"][:3]:
            context += (
                f"  • {att['data']}: {att['distanza_km']}km "
                f"{att['durata_str']} FC:{att['fc_media']}bpm\n"
            )
        context += "\n"

    return context

# ─────────────────────────────────────────────────────────────────────────────
# WORKOUT BUILDER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

SPORT_TYPE_MAP = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running"},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling"},
    "swimming": {"sportTypeId": 4, "sportTypeKey": "swimming"},
    "strength_training": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    "other": {"sportTypeId": 89, "sportTypeKey": "other"},
}

STEP_TYPE_MAP = {
    "warmup":   {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "active":   {"stepTypeId": 4, "stepTypeKey": "active"},
    "rest":     {"stepTypeId": 5, "stepTypeKey": "rest"},
    "repeat":   {"stepTypeId": 6, "stepTypeKey": "repeat"},
    "main":     {"stepTypeId": 8, "stepTypeKey": "main"},
}


def build_executable_step(step_key, order, distance_m=None, duration_sec=None, description=""):
    if distance_m:
        end_condition = {"conditionTypeId": 3, "conditionTypeKey": "distance",
                         "displayOrder": 3, "displayable": True}
        end_value = distance_m
        unit = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
    elif duration_sec:
        end_condition = {"conditionTypeId": 2, "conditionTypeKey": "time",
                         "displayOrder": 2, "displayable": True}
        end_value = duration_sec
        unit = {"unitId": 28, "unitKey": "second", "factor": 1.0}
    else:
        end_condition = {"conditionTypeId": 1, "conditionTypeKey": "lap.button",
                         "displayOrder": 1, "displayable": True}
        end_value = 0
        unit = {"unitId": 1, "unitKey": "meter", "factor": 100.0}

    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": STEP_TYPE_MAP.get(step_key, STEP_TYPE_MAP["main"]),
        "childStepId": None,
        "description": description or "",
        "endCondition": end_condition,
        "endConditionValue": end_value,
        "preferredEndConditionUnit": unit,
        "targetType": None, "targetValueOne": None, "targetValueTwo": None,
        "strokeType": {"strokeTypeId": 0, "strokeTypeKey": None, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "equipmentTypeKey": None, "displayOrder": 0},
    }


def build_repeat_group(order, repeat_count, child_steps):
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": STEP_TYPE_MAP["repeat"],
        "childStepId": 1,
        "numberOfIterations": repeat_count,
        "smartRepeat": False,
        "skipLastRestStep": None,
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                         "displayOrder": 7, "displayable": False},
        "endConditionValue": float(repeat_count),
        "workoutSteps": child_steps,
    }


def steps_to_garmin_format(steps: list) -> list:
    garmin_steps = []
    order = 1
    for step in steps:
        step_type = step.get("type") if isinstance(step, dict) else step.type
        if step_type == "repeat":
            repeat_steps_raw = step.get("repeat_steps") if isinstance(step, dict) else step.repeat_steps
            repeat_count = step.get("repeat_count") if isinstance(step, dict) else step.repeat_count
            child_steps = []
            child_order = order + 1
            for child in (repeat_steps_raw or []):
                cs = build_executable_step(
                    step_key=child.get("type", "main"),
                    order=child_order,
                    distance_m=child.get("distance_meters"),
                    duration_sec=child.get("duration_seconds"),
                    description=child.get("description", ""),
                )
                cs["childStepId"] = 1
                child_steps.append(cs)
                child_order += 1
            garmin_steps.append(build_repeat_group(order, repeat_count or 1, child_steps))
            order = child_order
        else:
            dist = step.get("distance_meters") if isinstance(step, dict) else step.distance_meters
            dur = step.get("duration_seconds") if isinstance(step, dict) else step.duration_seconds
            desc = step.get("description", "") if isinstance(step, dict) else (step.description or "")
            garmin_steps.append(build_executable_step(
                step_key=step_type, order=order,
                distance_m=dist, duration_sec=dur, description=desc,
            ))
            order += 1
    return garmin_steps


def build_garmin_workout_payload(name, sport, steps_garmin, description="", pool_length=50):
    sport_info = SPORT_TYPE_MAP.get(sport, SPORT_TYPE_MAP["other"])
    payload = {
        "sportType": sport_info,
        "workoutName": name,
        "description": description or "",
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport_info, "workoutSteps": steps_garmin}],
    }
    if sport == "swimming":
        payload["poolLength"] = float(pool_length)
        payload["poolLengthUnit"] = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
    return payload


def upload_to_garmin(garmin, workout_payload, scheduled_date):
    """Carica il workout su Garmin e lo schedula."""
    result = garmin.upload_workout(workout_payload)
    workout_id = result.get("workoutId") or result.get("detailId")
    if not workout_id:
        raise Exception(f"Garmin non ha ritornato un workout ID: {result}")
    garmin.schedule_workout(workout_id, scheduled_date)
    return workout_id


def format_workout_preview(workout_data: dict) -> str:
    """Formatta un workout in testo leggibile per la chat."""
    lines = []
    lines.append(f"📋 **{workout_data['name']}**")
    if workout_data.get("description"):
        lines.append(f"_{workout_data['description']}_")
    lines.append(f"📅 Data: **{workout_data['scheduled_date']}**")
    lines.append(f"🏋️ Sport: **{workout_data['sport']}**")
    lines.append("")
    lines.append("**Step:**")

    for s in workout_data.get("steps", []):
        if s["type"] == "repeat":
            lines.append(f"🔁 Ripeti **{s.get('repeat_count')}x**:")
            for sub in s.get("repeat_steps", []):
                icon = {"main": "💪", "rest": "⏸️"}.get(sub["type"], "•")
                dist = f"{sub['distance_meters']}m" if sub.get("distance_meters") else ""
                dur = f"{sub['duration_seconds']}s" if sub.get("duration_seconds") else ""
                lines.append(f"  {icon} {sub['type']}: {dist}{dur} — {sub.get('description','')}")
        else:
            icon = {"warmup": "🔥", "cooldown": "❄️", "main": "💪", "rest": "⏸️"}.get(s["type"], "•")
            dist = f"{s['distance_meters']}m" if s.get("distance_meters") else ""
            dur = f"{s['duration_seconds']}s" if s.get("duration_seconds") else ""
            lines.append(f"{icon} {s['type']}: {dist}{dur} — {s.get('description','')}")

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# INTENT DETECTION — capisce cosa vuole l'utente
# ─────────────────────────────────────────────────────────────────────────────

def detect_intent(message: str, pending_workout: dict) -> str:
    """
    Ritorna:
    - "confirm"   → utente conferma il workout pendente
    - "cancel"    → utente annulla
    - "change_date" → vuole cambiare data
    - "create_workout" → vuole creare un nuovo workout
    - "chat"      → domanda normale
    """
    msg_lower = message.lower().strip()

    # Se c'è un workout pendente, controlla prima le risposte sì/no
    if pending_workout:
        confirm_words = ["sì", "si", "yes", "ok", "confermo", "carica", "vai", "procedi",
                         "perfetto", "ottimo", "va bene", "certo", "sure", "yep", "sip"]
        cancel_words = ["no", "annulla", "cancel", "stop", "aspetta", "modifica",
                        "cambia", "non caricare"]

        if any(w in msg_lower for w in confirm_words):
            return "confirm"
        if any(w in msg_lower for w in cancel_words):
            return "cancel"

        # Controlla se vuole cambiare data
        date_keywords = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì",
                         "sabato", "domenica", "domani", "dopodomani", "oggi",
                         "2026", "gennaio", "febbraio", "marzo", "aprile", "maggio",
                         "giugno", "luglio", "agosto", "settembre", "ottobre",
                         "novembre", "dicembre"]
        if any(w in msg_lower for w in date_keywords):
            return "change_date"

    # Controlla se vuole creare un workout
    create_keywords = ["crea", "crea un", "voglio fare", "metti", "aggiungi",
                       "pianifica", "schedula", "nuovo allenamento", "allena",
                       "workout", "allenamento", "sessione", "carica sul calendario",
                       "metti in calendario"]
    if any(w in msg_lower for w in create_keywords):
        return "create_workout"

    return "chat"

# ─────────────────────────────────────────────────────────────────────────────
# GENERA WORKOUT CON CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

def generate_workout_with_claude(client, message: str, context: str, today: str) -> dict:
    """Chiede a Claude di generare un workout in JSON."""

    prompt = f"""
{context}

L'utente ha scritto: "{message}"

Genera un workout strutturato in JSON PURO (zero markdown, zero backtick, zero testo extra).
Se l'utente non specifica una data, usa domani ({today}).
Se l'utente non specifica la durata, usa 60 minuti.
Se l'utente non specifica lo sport, deducilo dal contesto.

JSON da ritornare (struttura ESATTA):
{{
  "name": "Nome breve del workout",
  "description": "Descrizione breve",
  "sport": "running",
  "scheduled_date": "2026-06-16",
  "duration_minutes": 60,
  "steps": [
    {{
      "type": "warmup",
      "distance_meters": 1000,
      "description": "Riscaldamento tranquillo"
    }},
    {{
      "type": "repeat",
      "repeat_count": 6,
      "repeat_steps": [
        {{"type": "main", "distance_meters": 400, "description": "Veloce"}},
        {{"type": "rest", "duration_seconds": 90, "description": "Recupero"}}
      ]
    }},
    {{
      "type": "cooldown",
      "distance_meters": 1000,
      "description": "Defaticamento"
    }}
  ]
}}

Sport validi: running, swimming, cycling, strength_training
Tipi step validi: warmup, cooldown, main, rest, repeat
Per nuoto e corsa: usa distance_meters
Per riposo: usa duration_seconds
Adatta l'intensità al profilo reale di Alessandro.
RISPONDI SOLO CON IL JSON.
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS BASE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "version": "5.0.0"}


@app.post("/login")
async def login():
    global user_session
    if user_session is not None:
        return {"status": "already_logged_in",
                "total_activities": len(user_session.get("attivita_raw", []))}
    garmin = login_garmin()
    attivita_raw, metriche = fetch_activities(garmin)
    user_session = {
        "email": os.getenv("GARMIN_EMAIL"),
        "garmin": garmin,
        "metriche": metriche,
        "attivita_raw": attivita_raw,
        "last_sync": datetime.now(),
    }
    return {"status": "success", "total_activities": len(attivita_raw),
            "sports": list(metriche.keys())}


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
async def get_activities(sport: Optional[str] = Query(None), limit: int = Query(50)):
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")
    attivita = user_session["attivita_raw"]
    if sport:
        attivita = [a for a in attivita if a["sport"].lower() == sport.lower()]
    return {"total": len(attivita[:limit]), "sport_filter": sport, "activities": attivita[:limit]}


@app.get("/sync")
async def sync():
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")
    attivita_raw, metriche = fetch_activities(user_session["garmin"])
    user_session["attivita_raw"] = attivita_raw
    user_session["metriche"] = metriche
    user_session["last_sync"] = datetime.now()
    return {"status": "synced", "total_activities": len(attivita_raw)}


@app.get("/calendar")
async def get_calendar(year: int = None, month: int = None):
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    try:
        calendar_data = user_session["garmin"].get_scheduled_workouts(year, month)
        items = calendar_data.get("calendarItems", [])
        workouts = [{
            "id": item.get("id"),
            "workout_id": item.get("workoutId"),
            "data": item.get("date"),
            "titolo": item.get("title"),
            "sport": item.get("sportTypeKey"),
            "tipo": item.get("itemType"),
            "distanza_m": item.get("distance"),
            "durata_sec": item.get("duration"),
            "fc_media": item.get("averageHR"),
            "calorie": item.get("calories"),
        } for item in items]
        return {"year": year, "month": month, "total": len(workouts), "items": workouts}
    except Exception as e:
        raise HTTPException(500, f"Errore calendario: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# CHAT CON FLUSSO DI CONFERMA
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(request: ChatMessage):
    """
    Chat intelligente con flusso di conferma per i workout.

    Flusso:
    1. Utente: "Crea un allenamento di corsa per domani"
    2. Coach: mostra preview e chiede conferma
    3. Utente: "Sì" → carica su Garmin
    4. Coach: "✅ Caricato!"
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    conv_id = request.conversation_id or "default"

    # Inizializza stato conversazione
    if conv_id not in conversation_states:
        conversation_states[conv_id] = {
            "pending_workout": None,
            "history": [],
        }

    state = conversation_states[conv_id]
    pending = state.get("pending_workout")
    message = request.message.strip()

    client_ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    context = build_context_for_claude(user_session["metriche"], user_session["attivita_raw"])
    today = date.today().isoformat()
    tomorrow = str(date.today().replace(day=date.today().day + 1))

    # ── INTENT DETECTION ──────────────────────────────────────────────────────
    intent = detect_intent(message, pending)

    # ── CONFERMA → CARICA SU GARMIN ───────────────────────────────────────────
    if intent == "confirm" and pending:
        try:
            garmin_steps = steps_to_garmin_format(pending["steps"])
            payload = build_garmin_workout_payload(
                name=pending["name"],
                sport=pending["sport"],
                steps_garmin=garmin_steps,
                description=pending.get("description", ""),
                pool_length=pending.get("pool_length", 50),
            )
            workout_id = upload_to_garmin(
                user_session["garmin"], payload, pending["scheduled_date"]
            )

            # Pulisci il pending
            state["pending_workout"] = None

            reply = (
                f"✅ **Perfetto! Workout caricato su Garmin!**\n\n"
                f"📋 **{pending['name']}** è ora nel tuo calendario "
                f"per il **{pending['scheduled_date']}**.\n\n"
                f"Trovi l'allenamento direttamente sull'orologio e su Garmin Connect. "
                f"Buon allenamento Alessandro! 💪"
            )

            return {
                "status": "success",
                "message": reply,
                "action": "workout_uploaded",
                "workout_id": workout_id,
                "scheduled_date": pending["scheduled_date"],
            }

        except Exception as e:
            state["pending_workout"] = None
            raise HTTPException(500, f"Errore caricamento Garmin: {str(e)}")

    # ── ANNULLA ───────────────────────────────────────────────────────────────
    if intent == "cancel" and pending:
        state["pending_workout"] = None
        return {
            "status": "success",
            "message": "❌ Workout annullato. Dimmi pure se vuoi crearne uno diverso!",
            "action": "workout_cancelled",
        }

    # ── CAMBIA DATA ───────────────────────────────────────────────────────────
    if intent == "change_date" and pending:
        # Chiedi a Claude di estrarre la nuova data
        date_prompt = f"""
Oggi è {today}.
L'utente ha scritto: "{message}"
Estrai la data che vuole in formato ISO YYYY-MM-DD.
Rispondi SOLO con la data, niente altro. Es: 2026-06-20
"""
        date_response = client_ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{"role": "user", "content": date_prompt}]
        )
        new_date = date_response.content[0].text.strip()

        pending["scheduled_date"] = new_date
        state["pending_workout"] = pending

        preview = format_workout_preview(pending)
        reply = (
            f"📅 Data aggiornata a **{new_date}**!\n\n"
            f"{preview}\n\n"
            f"---\n"
            f"Vuoi che lo carico su Garmin? Rispondi **Sì** per confermare o **No** per annullare."
        )
        return {"status": "success", "message": reply, "action": "date_changed",
                "pending_workout": pending}

    # ── CREA WORKOUT ──────────────────────────────────────────────────────────
    if intent == "create_workout":
        try:
            workout_data = generate_workout_with_claude(client_ai, message, context, tomorrow)

            # Salva come pending
            state["pending_workout"] = workout_data

            # Mostra preview e chiedi conferma
            preview = format_workout_preview(workout_data)

            reply = (
                f"Ho creato questo workout per te:\n\n"
                f"{preview}\n\n"
                f"---\n"
                f"Vuoi che lo carico su Garmin per il **{workout_data['scheduled_date']}**?\n"
                f"Rispondi **Sì** per confermare, **No** per annullare, "
                f"o dimmi una data diversa (es: 'mettilo giovedì')."
            )

            return {
                "status": "success",
                "message": reply,
                "action": "workout_preview",
                "pending_workout": workout_data,
            }

        except json.JSONDecodeError as e:
            return {
                "status": "success",
                "message": "Scusa, ho avuto un problema a strutturare l'allenamento. Puoi ripetere con più dettagli?",
                "action": "error",
            }
        except Exception as e:
            raise HTTPException(500, f"Errore generazione workout: {str(e)}")

    # ── CHAT NORMALE ──────────────────────────────────────────────────────────
    state["history"].append({"role": "user", "content": message})

    # Mantieni max 10 messaggi di storia
    if len(state["history"]) > 20:
        state["history"] = state["history"][-20:]

    messages_for_claude = [
        {"role": "user", "content": f"{context}\n\n{state['history'][0]['content']}"}
    ] + state["history"][1:]

    response = client_ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="""Sei un coach esperto di triathlon che allena Alessandro.
Hai accesso ai suoi VERI dati Garmin.
Rispondi SEMPRE in italiano. Sii specifico con i numeri reali.
Sii costruttivo e motivante.
Se l'utente chiede di creare o caricare un allenamento, digli che può farlo
semplicemente scrivendo cosa vuole fare (es: 'crea ripetute di corsa per domani').""",
        messages=messages_for_claude,
    )

    reply = response.content[0].text
    state["history"].append({"role": "assistant", "content": reply})

    return {"status": "success", "message": reply, "action": "chat"}


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT DI CONFERMA DIRETTO (opzionale, per il frontend)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/workout/confirm")
async def confirm_workout(request: ConfirmWorkoutRequest):
    """Conferma e carica il workout pendente."""
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    conv_id = request.conversation_id or "default"
    state = conversation_states.get(conv_id, {})
    pending = state.get("pending_workout")

    if not pending:
        raise HTTPException(400, "Nessun workout in attesa di conferma")

    try:
        garmin_steps = steps_to_garmin_format(pending["steps"])
        payload = build_garmin_workout_payload(
            name=pending["name"],
            sport=pending["sport"],
            steps_garmin=garmin_steps,
            description=pending.get("description", ""),
        )
        workout_id = upload_to_garmin(user_session["garmin"], payload, pending["scheduled_date"])
        state["pending_workout"] = None

        return {
            "status": "success",
            "message": f"✅ Workout '{pending['name']}' caricato per {pending['scheduled_date']}!",
            "workout_id": workout_id,
        }
    except Exception as e:
        raise HTTPException(500, f"Errore: {str(e)}")


@app.post("/workout/cancel")
async def cancel_workout(request: ConfirmWorkoutRequest):
    """Annulla il workout pendente."""
    conv_id = request.conversation_id or "default"
    state = conversation_states.get(conv_id, {})
    state["pending_workout"] = None
    return {"status": "success", "message": "Workout annullato."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
