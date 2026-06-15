"""
backend_api.py - v7
La chat fa TUTTO:
- Analisi attività passate (GPS, lap, cadenza, passo, FC)
- Creazione singolo workout con conferma
- Creazione piano allenamenti multi-settimana con conferma e upload massivo
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from garminconnect import Garmin
import anthropic
from collections import defaultdict
import json
import math
import xml.etree.ElementTree as ET

load_dotenv()

app = FastAPI(title="AI Triathlon Coach API", version="7.0.0")
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

class ConfirmWorkoutRequest(BaseModel):
    conversation_id: Optional[str] = "default"

# ─────────────────────────────────────────────────────────────────────────────
# SESSIONE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────

user_session = None
conversation_states = {}

# ─────────────────────────────────────────────────────────────────────────────
# GARMIN LOGIN + FETCH
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

        pace_str = None
        if distance_m > 0 and duration_sec > 0:
            pace_sec_km = duration_sec / (distance_m / 1000)
            m, s = divmod(int(pace_sec_km), 60)
            pace_str = f"{m}:{s:02d}/km"

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
            "garmin_id": str(a.get("activityId", "")),
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

# ─────────────────────────────────────────────────────────────────────────────
# ANALISI GRANULARE ATTIVITÀ (GPS, LAP, CADENZA)
# ─────────────────────────────────────────────────────────────────────────────

def sec_to_pace(sec_per_km: float) -> str:
    if not sec_per_km or sec_per_km <= 0:
        return "N/A"
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def fetch_lap_data(garmin: Garmin, activity_id: str) -> list:
    """Scarica dati lap/km per una singola attività."""
    try:
        splits = garmin.get_activity_splits(activity_id)
        lap_data = []
        for lap in (splits or []):
            distance_m = lap.get("distance", 0) or 0
            duration_sec = lap.get("duration", 0) or 0
            avg_speed = lap.get("averageSpeed", 0) or 0
            pace_sec_km = (1000 / avg_speed) if avg_speed > 0 else 0
            avg_cadence = lap.get("averageRunCadence", 0) or 0

            lap_data.append({
                "lap": lap.get("lapIndex", len(lap_data) + 1),
                "distance_km": round(distance_m / 1000, 3),
                "duration_str": f"{int(duration_sec//60)}:{int(duration_sec%60):02d}",
                "pace": sec_to_pace(pace_sec_km),
                "pace_sec_km": round(pace_sec_km, 1),
                "fc_media": lap.get("averageHR") or None,
                "fc_max": lap.get("maxHR") or None,
                "cadenza_cicli": avg_cadence or None,
                "cadenza_passi_min": avg_cadence * 2 if avg_cadence else None,
                "passo_cm": lap.get("avgStrideLength") or None,
                "dislivello_m": lap.get("elevationGain") or None,
            })
        return lap_data
    except Exception as e:
        print(f"⚠️ Lap error: {e}")
        return []


def fetch_gps_data(garmin: Garmin, activity_id: str, sample_every: int = 20) -> list:
    """Scarica punti GPS di una attività."""
    try:
        gpx_data = garmin.download_activity(
            activity_id, dl_fmt=garmin.ActivityDownloadFormat.GPX
        )
        ns = {
            "gpx": "http://www.topografix.com/GPX/1/1",
            "ns3": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
        }
        gpx_str = gpx_data.decode("utf-8") if isinstance(gpx_data, bytes) else str(gpx_data)
        root = ET.fromstring(gpx_str)
        track_points = root.findall(".//gpx:trkpt", ns)

        gps_points = []
        prev_lat, prev_lon = None, None
        cumulative_km = 0

        for i, pt in enumerate(track_points):
            if i % sample_every != 0:
                continue
            lat = float(pt.attrib.get("lat", 0))
            lon = float(pt.attrib.get("lon", 0))
            ele = pt.find("gpx:ele", ns)
            time_el = pt.find("gpx:time", ns)
            hr_el = pt.find(".//ns3:hr", ns)
            cad_el = pt.find(".//ns3:cad", ns)

            dist = 0
            if prev_lat is not None:
                dlat = math.radians(lat - prev_lat)
                dlon = math.radians(lon - prev_lon)
                a = (math.sin(dlat/2)**2 +
                     math.cos(math.radians(prev_lat)) *
                     math.cos(math.radians(lat)) *
                     math.sin(dlon/2)**2)
                dist = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            cumulative_km += dist / 1000

            gps_points.append({
                "index": i,
                "lat": lat,
                "lon": lon,
                "elevation_m": float(ele.text) if ele is not None else None,
                "time": time_el.text if time_el is not None else None,
                "hr": int(hr_el.text) if hr_el is not None else None,
                "cadence_spm": int(cad_el.text) * 2 if cad_el is not None else None,
                "cumulative_km": round(cumulative_km, 3),
            })
            prev_lat, prev_lon = lat, lon

        return gps_points
    except Exception as e:
        print(f"⚠️ GPS error: {e}")
        return []


def build_granular_context(activity: dict, lap_data: list, gps_points: list) -> str:
    """Costruisce il testo di analisi granulare per Claude."""
    ctx = f"\n=== ANALISI DETTAGLIATA: {activity.get('nome', 'Attività')} ({activity.get('data')}) ===\n"
    ctx += f"Sport: {activity.get('sport')} | Distanza: {activity.get('distanza_km')}km | "
    ctx += f"Durata: {activity.get('durata_str')} | Pace medio: {activity.get('pace')} | "
    ctx += f"FC media: {activity.get('fc_media')}bpm\n\n"

    if lap_data:
        ctx += "DATI KM PER KM:\n"
        paces = [l["pace_sec_km"] for l in lap_data if l["pace_sec_km"] > 0]
        for lap in lap_data:
            ctx += (
                f"  Km {lap['lap']}: {lap['pace']} | "
                f"FC {lap['fc_media'] or 'N/A'}bpm | "
                f"cadenza {lap['cadenza_passi_min'] or 'N/A'}spm | "
                f"passo {lap['passo_cm'] or 'N/A'}cm\n"
            )
        if paces:
            best = min(paces)
            worst = max(paces)
            ctx += f"\nMiglior km: {sec_to_pace(best)} | Peggior km: {sec_to_pace(worst)} | "
            ctx += f"Variazione: {int(worst - best)}sec/km\n"

    if gps_points:
        ctx += f"\nGPS: {len(gps_points)} punti campionati\n"
        # Mostra ogni ~10% del percorso
        step = max(1, len(gps_points) // 8)
        for i in range(0, len(gps_points), step):
            pt = gps_points[i]
            ctx += (
                f"  @{pt['cumulative_km']}km: "
                f"lat {pt['lat']:.4f} lon {pt['lon']:.4f}"
                f"{' ele:'+str(pt['elevation_m'])+'m' if pt.get('elevation_m') else ''}"
                f"{' FC:'+str(pt['hr'])+'bpm' if pt.get('hr') else ''}\n"
            )

    return ctx

# ─────────────────────────────────────────────────────────────────────────────
# CONTESTO BASE PER CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

def build_base_context(metriche_sport: dict, attivita_raw: list) -> str:
    ctx = "=== PROFILO ATLETA ===\n"
    ctx += "Nome: Alessandro | Paese: Germania\n"
    ctx += "Obiettivo: Triathlon olimpico\n"
    ctx += "Baseline: nuoto 2km/40min (2:00/100m), corsa 12km a 5:40/km\n"
    ctx += f"Data oggi: {date.today().isoformat()} ({date.today().strftime('%A')})\n\n"

    ctx += "=== STORICO ALLENAMENTI ===\n\n"
    for sport, m in sorted(metriche_sport.items()):
        if m["count"] == 0:
            continue
        avg_hr = sum(m["avg_hr_values"]) / len(m["avg_hr_values"]) if m["avg_hr_values"] else None
        ctx += f"{sport.upper()}: {m['count']} sessioni | "
        ctx += f"{m['total_distance_m']/1000:.1f}km totali | "
        ctx += f"{m['total_duration_sec']/3600:.1f}h totali"
        if avg_hr:
            ctx += f" | FC media {avg_hr:.0f}bpm"
        ctx += "\n"
        for att in m["attivita"][:5]:
            ctx += (
                f"  • {att['data']}: {att['nome']} — "
                f"{att['distanza_km']}km {att['durata_str']} "
                f"pace:{att['pace']} FC:{att['fc_media']}bpm\n"
            )
        ctx += "\n"

    return ctx

# ─────────────────────────────────────────────────────────────────────────────
# WORKOUT BUILDER
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


def build_step(step_key, order, distance_m=None, duration_sec=None, description="", child_id=None):
    if distance_m:
        end_cond = {"conditionTypeId": 3, "conditionTypeKey": "distance",
                    "displayOrder": 3, "displayable": True}
        end_val = distance_m
        unit = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
    elif duration_sec:
        end_cond = {"conditionTypeId": 2, "conditionTypeKey": "time",
                    "displayOrder": 2, "displayable": True}
        end_val = duration_sec
        unit = {"unitId": 28, "unitKey": "second", "factor": 1.0}
    else:
        end_cond = {"conditionTypeId": 1, "conditionTypeKey": "lap.button",
                    "displayOrder": 1, "displayable": True}
        end_val = 0
        unit = {"unitId": 1, "unitKey": "meter", "factor": 100.0}

    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": STEP_TYPE_MAP.get(step_key, STEP_TYPE_MAP["main"]),
        "childStepId": child_id,
        "description": description or "",
        "endCondition": end_cond,
        "endConditionValue": end_val,
        "preferredEndConditionUnit": unit,
        "targetType": None, "targetValueOne": None, "targetValueTwo": None,
        "strokeType": {"strokeTypeId": 0, "strokeTypeKey": None, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "equipmentTypeKey": None, "displayOrder": 0},
    }


def build_repeat(order, count, child_steps):
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": STEP_TYPE_MAP["repeat"],
        "childStepId": 1,
        "numberOfIterations": count,
        "smartRepeat": False,
        "skipLastRestStep": None,
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                         "displayOrder": 7, "displayable": False},
        "endConditionValue": float(count),
        "workoutSteps": child_steps,
    }


def steps_to_garmin(steps: list) -> list:
    garmin_steps = []
    order = 1
    for step in steps:
        t = step.get("type") if isinstance(step, dict) else step.type
        if t == "repeat":
            repeat_raw = step.get("repeat_steps") if isinstance(step, dict) else step.repeat_steps
            count = step.get("repeat_count") if isinstance(step, dict) else step.repeat_count
            children = []
            child_order = order + 1
            for child in (repeat_raw or []):
                cs = build_step(
                    child.get("type", "main"), child_order,
                    child.get("distance_meters"), child.get("duration_seconds"),
                    child.get("description", ""),
                )
                cs["childStepId"] = 1
                children.append(cs)
                child_order += 1
            garmin_steps.append(build_repeat(order, count or 1, children))
            order = child_order
        else:
            dist = step.get("distance_meters") if isinstance(step, dict) else step.distance_meters
            dur = step.get("duration_seconds") if isinstance(step, dict) else step.duration_seconds
            desc = step.get("description", "") if isinstance(step, dict) else (step.description or "")
            garmin_steps.append(build_step(t, order, dist, dur, desc))
            order += 1
    return garmin_steps


def make_payload(name, sport, garmin_steps, description="", pool_length=50):
    sport_info = SPORT_TYPE_MAP.get(sport, SPORT_TYPE_MAP["other"])
    payload = {
        "sportType": sport_info,
        "workoutName": name,
        "description": description or "",
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport_info,
                             "workoutSteps": garmin_steps}],
    }
    if sport == "swimming":
        payload["poolLength"] = float(pool_length)
        payload["poolLengthUnit"] = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
    return payload


def upload_workout(garmin, payload, scheduled_date) -> str:
    result = garmin.upload_workout(payload)
    workout_id = result.get("workoutId") or result.get("detailId")
    if not workout_id:
        raise Exception(f"Garmin non ha ritornato workout ID: {result}")
    garmin.schedule_workout(workout_id, scheduled_date)
    return str(workout_id)

# ─────────────────────────────────────────────────────────────────────────────
# FORMAT PREVIEW
# ─────────────────────────────────────────────────────────────────────────────

def format_single_workout(wo: dict, show_steps: bool = True) -> str:
    emoji = {"running": "🏃", "swimming": "🏊", "cycling": "🚴",
             "strength_training": "🏋️"}.get(wo.get("sport", ""), "⚡")
    lines = [f"{emoji} **{wo['name']}** — {wo['scheduled_date']}"]
    if wo.get("description"):
        lines.append(f"  _{wo['description']}_")

    if show_steps:
        for s in wo.get("steps", []):
            if s["type"] == "repeat":
                lines.append(f"  🔁 {s.get('repeat_count')}x:")
                for sub in s.get("repeat_steps", []):
                    icon = {"main": "💪", "rest": "⏸️"}.get(sub["type"], "•")
                    dist = f"{sub['distance_meters']}m" if sub.get("distance_meters") else ""
                    dur = f"{sub['duration_seconds']}s" if sub.get("duration_seconds") else ""
                    lines.append(f"    {icon} {sub['type']}: {dist}{dur} — {sub.get('description','')}")
            else:
                icon = {"warmup": "🔥", "cooldown": "❄️", "main": "💪", "rest": "⏸️"}.get(s["type"], "•")
                dist = f"{s['distance_meters']}m" if s.get("distance_meters") else ""
                dur = f"{s['duration_seconds']}s" if s.get("duration_seconds") else ""
                lines.append(f"  {icon} {s['type']}: {dist}{dur} — {s.get('description','')}")

    return "\n".join(lines)


def format_plan_preview(plan: list) -> str:
    lines = [f"📅 **Piano di {len(plan)} allenamenti:**\n"]
    for i, wo in enumerate(plan, 1):
        lines.append(f"**{i}.** {format_single_workout(wo, show_steps=False)}")
    lines.append("\nVuoi vedere i dettagli di ogni allenamento? Rispondi **Sì** per caricare tutto, **No** per annullare, o **dettagli** per vedere gli step.")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# INTENT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_intent(message: str, state: dict) -> str:
    msg = message.lower().strip()
    pending = state.get("pending_workout")
    pending_plan = state.get("pending_plan")

    # Risposte a workout/piano pendente
    if pending or pending_plan:
        if any(w in msg for w in ["sì", "si", "yes", "ok", "confermo", "carica",
                                   "vai", "procedi", "perfetto", "ottimo", "certo"]):
            return "confirm"
        if any(w in msg for w in ["no", "annulla", "cancel", "stop"]):
            return "cancel"
        if "dettagli" in msg or "mostra" in msg:
            return "show_details"
        if any(w in msg for w in ["lunedì", "martedì", "mercoledì", "giovedì",
                                   "venerdì", "sabato", "domenica", "domani",
                                   "dopodomani", "2026"]):
            return "change_date"

    # Piano allenamenti
    if any(w in msg for w in ["piano", "settimana", "settimane", "più allenamenti",
                               "programma", "schedule", "4 allenamenti", "5 allenamenti",
                               "tutta la settimana", "settimane di", "mese di"]):
        return "create_plan"

    # Singolo workout
    if any(w in msg for w in ["crea", "voglio fare", "metti", "aggiungi", "pianifica",
                               "schedula", "allenamento", "workout", "sessione",
                               "carica sul calendario"]):
        return "create_workout"

    # Analisi attività passate
    if any(w in msg for w in ["analizza", "analisi", "ultima", "ultimo", "recente",
                               "come è andata", "come stà", "lap", "km per km",
                               "cadenza", "passo", "gps", "corsa di", "nuoto di",
                               "come sono andato", "performance", "dati"]):
        return "analyze"

    return "chat"

# ─────────────────────────────────────────────────────────────────────────────
# GENERAZIONE CON CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

def ai_generate_single_workout(client, message: str, context: str, tomorrow: str) -> dict:
    """Genera un singolo workout in JSON."""
    prompt = f"""{context}

Richiesta: "{message}"

Genera un workout in JSON PURO (zero markdown, zero backtick).
Se non c'è data, usa {tomorrow}.

{{
  "name": "Nome",
  "description": "Breve descrizione",
  "sport": "running",
  "scheduled_date": "{tomorrow}",
  "steps": [
    {{"type": "warmup", "distance_meters": 1000, "description": "Riscaldamento"}},
    {{"type": "repeat", "repeat_count": 6, "repeat_steps": [
      {{"type": "main", "distance_meters": 400, "description": "Veloce"}},
      {{"type": "rest", "duration_seconds": 90, "description": "Recupero"}}
    ]}},
    {{"type": "cooldown", "distance_meters": 1000, "description": "Defaticamento"}}
  ]
}}

Sport validi: running, swimming, cycling, strength_training
SOLO JSON."""

    r = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def ai_generate_training_plan(client, message: str, context: str, today: str) -> list:
    """Genera un piano multi-allenamento in JSON."""
    prompt = f"""{context}

Richiesta: "{message}"
Data di oggi: {today}

Genera un piano di allenamenti in JSON PURO (zero markdown, zero backtick).
Crea tutti gli allenamenti richiesti, ognuno con data diversa.

[
  {{
    "name": "Nome allenamento 1",
    "description": "Breve descrizione",
    "sport": "running",
    "scheduled_date": "YYYY-MM-DD",
    "steps": [
      {{"type": "warmup", "distance_meters": 1000, "description": "Riscaldamento"}},
      {{"type": "repeat", "repeat_count": 5, "repeat_steps": [
        {{"type": "main", "distance_meters": 400, "description": "Veloce"}},
        {{"type": "rest", "duration_seconds": 90, "description": "Recupero"}}
      ]}},
      {{"type": "cooldown", "distance_meters": 1000, "description": "Defaticamento"}}
    ]
  }},
  {{
    "name": "Nome allenamento 2",
    ...
  }}
]

REGOLE:
- Distribuisci i giorni con recupero adeguato (mai 2 sessioni intense consecutive)
- Alterna nuoto, corsa, bici, palestra in base alla richiesta
- Adatta intensità e volume al profilo reale di Alessandro
- Sport validi: running, swimming, cycling, strength_training
- SOLO array JSON, nient'altro."""

    r = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def ai_analyze_activity(client, message: str, context: str,
                        attivita_raw: list, garmin: Garmin) -> str:
    """
    Capisce quale attività analizzare, scarica i dati granulari
    e ritorna l'analisi completa.
    """
    # Trova l'attività più rilevante in base al messaggio
    msg_lower = message.lower()

    # Cerca per sport o parola chiave
    candidate = None
    for att in attivita_raw[:20]:  # ultimi 20
        sport = att.get("sport", "")
        nome = att.get("nome", "").lower()
        if ("ultima" in msg_lower or "recente" in msg_lower or "ultimo" in msg_lower):
            candidate = attivita_raw[0]  # ultima in assoluto
            break
        if "corsa" in msg_lower and "running" in sport:
            candidate = att
            break
        if "nuoto" in msg_lower and "swimming" in sport:
            candidate = att
            break
        if "bici" in msg_lower and "cycling" in sport:
            candidate = att
            break
        if "palestra" in msg_lower and "strength" in sport:
            candidate = att
            break
        if any(word in nome for word in msg_lower.split()):
            candidate = att
            break

    if not candidate and attivita_raw:
        candidate = attivita_raw[0]  # fallback: ultima attività

    if not candidate:
        return "Non ho trovato attività da analizzare nel tuo storico Garmin."

    # Scarica dati granulari
    activity_id = candidate.get("garmin_id", "")
    lap_data = []
    gps_points = []

    if activity_id:
        print(f"📊 Scaricando dati granulari per {candidate['nome']} ({activity_id})...")
        lap_data = fetch_lap_data(garmin, activity_id)
        gps_points = fetch_gps_data(garmin, activity_id)

    # Costruisci contesto granulare
    granular_ctx = build_granular_context(candidate, lap_data, gps_points)
    full_ctx = context + granular_ctx

    # Analisi con Claude
    r = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system="""Sei un coach esperto di triathlon che analizza i dati reali di Alessandro.
Hai accesso a dati GPS, lap km per km, cadenza, passo, FC.
Rispondi SEMPRE in italiano. Sii specifico con i numeri.
Struttura la risposta in sezioni chiare.""",
        messages=[{"role": "user", "content": (
            f"{full_ctx}\n\n"
            f"Domanda: {message}\n\n"
            f"Analizza in dettaglio:\n"
            f"1. Andamento del ritmo km per km (c'è stato un calo?)\n"
            f"2. Cadenza e passo (ottimale per triathlon: 170-180 spm)\n"
            f"3. FC nell'arco dell'attività\n"
            f"4. Punti di forza e aree di miglioramento\n"
            f"5. Confronto con le sessioni precedenti dello stesso sport"
        )}]
    )

    return r.content[0].text

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS BASE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "version": "7.0.0"}


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
    return {"total": len(attivita[:limit]), "activities": attivita[:limit]}


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
        cal = user_session["garmin"].get_scheduled_workouts(year, month)
        items = cal.get("calendarItems", [])
        return {"year": year, "month": month, "total": len(items), "items": [{
            "id": i.get("id"),
            "workout_id": i.get("workoutId"),
            "data": i.get("date"),
            "titolo": i.get("title"),
            "sport": i.get("sportTypeKey"),
            "tipo": i.get("itemType"),
            "distanza_m": i.get("distance"),
            "durata_sec": i.get("duration"),
            "fc_media": i.get("averageHR"),
        } for i in items]}
    except Exception as e:
        raise HTTPException(500, f"Errore calendario: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# CHAT — FA TUTTO
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(request: ChatMessage):
    """
    Chat intelligente che gestisce:
    - Analisi attività passate (GPS, lap, cadenza, passo)
    - Creazione singolo workout con conferma
    - Creazione piano allenamenti multi-workout con conferma
    - Conversazione generale
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    conv_id = request.conversation_id or "default"
    if conv_id not in conversation_states:
        conversation_states[conv_id] = {
            "pending_workout": None,
            "pending_plan": None,
            "history": [],
        }

    state = conversation_states[conv_id]
    message = request.message.strip()
    today = date.today().isoformat()
    tomorrow = str(date.today() + timedelta(days=1))

    client_ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    base_ctx = build_base_context(user_session["metriche"], user_session["attivita_raw"])

    intent = detect_intent(message, state)

    # ── CONFERMA ──────────────────────────────────────────────────────────────
    if intent == "confirm":

        # Singolo workout
        if state.get("pending_workout"):
            wo = state["pending_workout"]
            try:
                gsteps = steps_to_garmin(wo["steps"])
                payload = make_payload(wo["name"], wo["sport"], gsteps, wo.get("description", ""))
                wid = upload_workout(user_session["garmin"], payload, wo["scheduled_date"])
                state["pending_workout"] = None
                reply = (f"✅ **Caricato su Garmin!**\n\n"
                         f"**{wo['name']}** è nel calendario per il **{wo['scheduled_date']}**. "
                         f"Buon allenamento! 💪")
                save_to_history(message, reply)
                return {"status": "success", "message": reply,
                        "action": "workout_uploaded", "workout_id": wid}
            except Exception as e:
                state["pending_workout"] = None
                raise HTTPException(500, f"Errore Garmin: {str(e)}")

        # Piano completo
        if state.get("pending_plan"):
            plan = state["pending_plan"]
            uploaded = []
            failed = []
            for wo in plan:
                try:
                    gsteps = steps_to_garmin(wo["steps"])
                    payload = make_payload(wo["name"], wo["sport"], gsteps, wo.get("description", ""))
                    wid = upload_workout(user_session["garmin"], payload, wo["scheduled_date"])
                    uploaded.append({"name": wo["name"], "date": wo["scheduled_date"], "workout_id": wid})
                except Exception as e:
                    failed.append({"name": wo["name"], "error": str(e)})

            state["pending_plan"] = None
            lines = [f"✅ **Piano caricato! {len(uploaded)}/{len(plan)} allenamenti**\n"]
            for u in uploaded:
                lines.append(f"✅ {u['name']} — {u['date']}")
            if failed:
                lines.append(f"\n⚠️ Falliti ({len(failed)}):")
                for f in failed:
                    lines.append(f"  ❌ {f['name']}: {f['error']}")
            lines.append("\nTrovi gli allenamenti sull'orologio e su Garmin Connect. In bocca al lupo! 🏊🚴🏃")
            reply = "\n".join(lines)
            save_to_history(message, reply)
            return {"status": "success", "message": reply,
                    "action": "plan_uploaded", "uploaded": uploaded, "failed": failed}

    # ── ANNULLA ───────────────────────────────────────────────────────────────
    if intent == "cancel":
        state["pending_workout"] = None
        state["pending_plan"] = None
        reply = "❌ Annullato. Dimmi pure cosa vuoi fare!"
        save_to_history(message, reply)
        return {"status": "success", "message": reply, "action": "cancelled"}

    # ── MOSTRA DETTAGLI PIANO ─────────────────────────────────────────────────
    if intent == "show_details" and state.get("pending_plan"):
        plan = state["pending_plan"]
        lines = [f"📋 **Dettagli del piano ({len(plan)} allenamenti):**\n"]
        for i, wo in enumerate(plan, 1):
            lines.append(f"\n**{i}.** {format_single_workout(wo, show_steps=True)}")
        lines.append("\n---\nRispondi **Sì** per caricare tutto, **No** per annullare.")
        reply = "\n".join(lines)
        save_to_history(message, reply)
        return {"status": "success", "message": reply,
                "action": "plan_details", "pending_plan": plan}

    # ── CAMBIA DATA ───────────────────────────────────────────────────────────
    if intent == "change_date" and state.get("pending_workout"):
        r = client_ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=20,
            messages=[{"role": "user",
                       "content": f"Oggi è {today}. L'utente scrive: \"{message}\". "
                                  f"Estrai la data ISO YYYY-MM-DD. Solo la data."}]
        )
        new_date = r.content[0].text.strip()
        state["pending_workout"]["scheduled_date"] = new_date
        preview = format_single_workout(state["pending_workout"])
        reply = (f"📅 Data aggiornata a **{new_date}**!\n\n{preview}\n\n"
                 f"Rispondi **Sì** per confermare o **No** per annullare.")
        save_to_history(message, reply)
        return {"status": "success", "message": reply,
                "action": "date_changed", "pending_workout": state["pending_workout"]}

    # Helper: salva nella history e tronca a 40 messaggi
    def save_to_history(user_msg: str, assistant_msg: str):
        state["history"].append({"role": "user", "content": user_msg})
        state["history"].append({"role": "assistant", "content": assistant_msg})
        if len(state["history"]) > 40:
            # Tieni sempre il primo messaggio (contesto Garmin) + ultimi 38
            state["history"] = state["history"][:2] + state["history"][-38:]

    # Helper: costruisce i messaggi per Claude con tutta la history
    def build_messages_with_history(current_user_msg: str) -> list:
        """
        Prima chiamata: [user: contesto+messaggio]
        Chiamate successive: [user: contesto+msg1, assistant: reply1, user: msg2, ...]
        Il contesto Garmin viene iniettato SOLO nel primo messaggio.
        """
        if not state["history"]:
            # Prima volta: inietta il contesto nel messaggio
            return [{"role": "user", "content": f"{base_ctx}\n\n{current_user_msg}"}]
        else:
            # History esistente: primo messaggio già ha il contesto,
            # aggiungi il nuovo messaggio alla fine
            messages = []
            for i, h in enumerate(state["history"]):
                if i == 0:
                    # Primo messaggio utente: ha già il contesto
                    messages.append({"role": h["role"], "content": h["content"]})
                else:
                    messages.append({"role": h["role"], "content": h["content"]})
            # Aggiungi il messaggio corrente
            messages.append({"role": "user", "content": current_user_msg})
            return messages

    SYSTEM = """Sei un coach esperto di triathlon che allena Alessandro.
Hai accesso a tutti i suoi dati Garmin reali: attività passate, GPS, lap, cadenza, passo.
Ricordi TUTTA la conversazione precedente e ci fai riferimento naturalmente.
Rispondi SEMPRE in italiano. Sii specifico, motivante e coerente con quanto detto prima.

Puoi fare tutto dalla chat:
- Analizzare attività passate con dati reali
- Creare workout singoli e caricarli su Garmin
- Creare piani di allenamento multi-settimana"""

    # ── ANALISI ATTIVITÀ PASSATE ──────────────────────────────────────────────
    if intent == "analyze":
        try:
            analysis = ai_analyze_activity(
                client_ai, message, base_ctx,
                user_session["attivita_raw"],
                user_session["garmin"]
            )
            save_to_history(message, analysis)
            return {"status": "success", "message": analysis, "action": "analysis"}
        except Exception as e:
            reply = (f"Ho avuto un problema nel scaricare i dati granulari ({e}). "
                     f"Ti do l'analisi dai dati sommari che ho.")
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "analysis_error"}

    # ── CREA PIANO ALLENAMENTI ────────────────────────────────────────────────
    if intent == "create_plan":
        try:
            plan = ai_generate_training_plan(client_ai, message, base_ctx, today)
            state["pending_plan"] = plan
            state["pending_workout"] = None
            preview = format_plan_preview(plan)
            reply = f"Ho creato questo piano per te:\n\n{preview}"
            save_to_history(message, reply)
            return {
                "status": "success",
                "message": reply,
                "action": "plan_preview",
                "pending_plan": plan,
            }
        except Exception as e:
            reply = "Scusa, riprova descrivendo meglio il piano (quanti giorni, quali sport, ecc.)"
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "error"}

    # ── CREA SINGOLO WORKOUT ──────────────────────────────────────────────────
    if intent == "create_workout":
        try:
            wo = ai_generate_single_workout(client_ai, message, base_ctx, tomorrow)
            state["pending_workout"] = wo
            state["pending_plan"] = None
            preview = format_single_workout(wo)
            reply = (f"Ho creato questo workout:\n\n{preview}\n\n---\n"
                     f"Vuoi che lo carico su Garmin per il **{wo['scheduled_date']}**?\n"
                     f"**Sì** per confermare, **No** per annullare, "
                     f"o dimmi una data diversa.")
            save_to_history(message, reply)
            return {
                "status": "success",
                "message": reply,
                "action": "workout_preview",
                "pending_workout": wo,
            }
        except Exception as e:
            reply = "Scusa, riprova con più dettagli sull'allenamento."
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "error"}

    # ── CHAT NORMALE ──────────────────────────────────────────────────────────
    messages_for_claude = build_messages_with_history(message)

    r = client_ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM,
        messages=messages_for_claude,
    )
    reply = r.content[0].text

    # Prima volta: salva il messaggio con il contesto già iniettato
    if not state["history"]:
        state["history"].append({
            "role": "user",
            "content": f"{base_ctx}\n\n{message}"
        })
        state["history"].append({"role": "assistant", "content": reply})
    else:
        save_to_history(message, reply)

    return {"status": "success", "message": reply, "action": "chat"}


@app.post("/workout/confirm")
async def confirm_workout(request: ConfirmWorkoutRequest):
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")
    conv_id = request.conversation_id or "default"
    state = conversation_states.get(conv_id, {})
    pending = state.get("pending_workout")
    if not pending:
        raise HTTPException(400, "Nessun workout in attesa")
    gsteps = steps_to_garmin(pending["steps"])
    payload = make_payload(pending["name"], pending["sport"], gsteps)
    wid = upload_workout(user_session["garmin"], payload, pending["scheduled_date"])
    state["pending_workout"] = None
    return {"status": "success", "workout_id": wid,
            "message": f"✅ Caricato per {pending['scheduled_date']}!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
