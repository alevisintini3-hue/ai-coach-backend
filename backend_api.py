"""
backend_api.py - v6
Novità:
- GPS tracking punto per punto
- Ritmo per secondo
- Dati lap/km dettagliati
- Cadenza e passo
- Analisi AI su dati granulari reali
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

app = FastAPI(title="AI Triathlon Coach API", version="6.0.0")

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
# GARMIN HELPERS BASE
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
                f"{att['durata_str']} FC:{att['fc_media']}bpm pace:{att['pace']}\n"
            )
        context += "\n"

    return context

# ─────────────────────────────────────────────────────────────────────────────
# NUOVE FUNZIONI: DATI GRANULARI ATTIVITÀ
# ─────────────────────────────────────────────────────────────────────────────

def sec_to_pace(sec_per_km: float) -> str:
    """Converte secondi/km in mm:ss/km"""
    if not sec_per_km or sec_per_km <= 0:
        return "N/A"
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def parse_gps_and_metrics(garmin: Garmin, activity_id: str) -> dict:
    """
    Scarica tutti i dati granulari di un'attività:
    - GPS punto per punto
    - Ritmo per secondo
    - Lap/km dettagliati
    - Cadenza e passo
    """
    result = {
        "activity_id": activity_id,
        "gps_points": [],
        "lap_data": [],
        "splits": [],
        "metrics_per_second": [],
        "summary": {},
        "errors": [],
    }

    # ── 1. DATI GPS PUNTO PER PUNTO ──────────────────────────────────────────
    try:
        gpx_data = garmin.download_activity(activity_id, dl_fmt=garmin.ActivityDownloadFormat.GPX)

        # Parsa il GPX manualmente
        import xml.etree.ElementTree as ET
        ns = {
            "gpx": "http://www.topografix.com/GPX/1/1",
            "ns3": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
        }

        if isinstance(gpx_data, bytes):
            gpx_str = gpx_data.decode("utf-8")
        else:
            gpx_str = str(gpx_data)

        root = ET.fromstring(gpx_str)
        track_points = root.findall(".//gpx:trkpt", ns)

        gps_points = []
        prev_lat, prev_lon, prev_time = None, None, None

        for i, pt in enumerate(track_points):
            lat = float(pt.attrib.get("lat", 0))
            lon = float(pt.attrib.get("lon", 0))
            ele = pt.find("gpx:ele", ns)
            time_el = pt.find("gpx:time", ns)
            hr_el = pt.find(".//ns3:hr", ns)
            cad_el = pt.find(".//ns3:cad", ns)

            # Calcola distanza dal punto precedente (formula Haversine semplificata)
            dist_from_prev = 0
            if prev_lat and prev_lon:
                import math
                R = 6371000
                dlat = math.radians(lat - prev_lat)
                dlon = math.radians(lon - prev_lon)
                a = (math.sin(dlat/2)**2 +
                     math.cos(math.radians(prev_lat)) *
                     math.cos(math.radians(lat)) *
                     math.sin(dlon/2)**2)
                dist_from_prev = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

            point = {
                "index": i,
                "lat": lat,
                "lon": lon,
                "elevation": float(ele.text) if ele is not None else None,
                "time": time_el.text if time_el is not None else None,
                "hr": int(hr_el.text) if hr_el is not None else None,
                "cadence": int(cad_el.text) * 2 if cad_el is not None else None,  # passi/min
                "dist_from_prev_m": round(dist_from_prev, 2),
            }

            gps_points.append(point)
            prev_lat, prev_lon = lat, lon

        result["gps_points"] = gps_points
        result["gps_points_count"] = len(gps_points)
        print(f"✓ GPS: {len(gps_points)} punti scaricati")

    except Exception as e:
        result["errors"].append(f"GPS: {str(e)}")
        print(f"⚠️ GPS error: {e}")

    # ── 2. LAP / KM DETTAGLIATI ───────────────────────────────────────────────
    try:
        splits = garmin.get_activity_splits(activity_id)

        lap_data = []
        for lap in (splits or []):
            distance_m = lap.get("distance", 0) or 0
            duration_sec = lap.get("duration", 0) or 0
            avg_hr = lap.get("averageHR", 0) or 0
            avg_speed = lap.get("averageSpeed", 0) or 0  # m/s

            # Pace in sec/km
            pace_sec_km = (1000 / avg_speed) if avg_speed > 0 else 0

            lap_entry = {
                "lap_number": lap.get("lapIndex", len(lap_data) + 1),
                "distance_km": round(distance_m / 1000, 3),
                "duration_sec": duration_sec,
                "duration_str": f"{int(duration_sec//60)}:{int(duration_sec%60):02d}",
                "avg_pace": sec_to_pace(pace_sec_km),
                "avg_pace_sec_km": round(pace_sec_km, 1),
                "avg_hr": avg_hr if avg_hr > 0 else None,
                "max_hr": lap.get("maxHR", 0) or None,
                "avg_cadence": lap.get("averageRunCadence", 0) or None,  # passi/min (x2 = doppio passo)
                "avg_stride_length": lap.get("avgStrideLength", 0) or None,  # cm
                "elevation_gain": lap.get("elevationGain", 0) or None,
                "calories": lap.get("calories", 0) or None,
            }

            # Cadenza in passi/min reali (Garmin salva cicli/min)
            if lap_entry["avg_cadence"]:
                lap_entry["avg_cadence_steps_per_min"] = lap_entry["avg_cadence"] * 2

            lap_data.append(lap_entry)

        result["lap_data"] = lap_data
        result["total_laps"] = len(lap_data)
        print(f"✓ Laps: {len(lap_data)} lap scaricati")

    except Exception as e:
        result["errors"].append(f"Laps: {str(e)}")
        print(f"⚠️ Laps error: {e}")

    # ── 3. SPLITS PER KM ─────────────────────────────────────────────────────
    try:
        km_splits = garmin.get_activity_hr_in_timezones(activity_id)
        result["hr_zones"] = km_splits
    except Exception as e:
        result["errors"].append(f"HR zones: {str(e)}")

    # ── 4. DATI DETTAGLIATI (ritmo/sec, cadenza/sec) ────────────────────────
    try:
        details = garmin.get_activity_details(activity_id, maxChartSize=2000)

        metrics_per_second = []

        # Garmin ritorna i dati come serie temporali
        metric_descriptors = details.get("metricDescriptors", [])
        activity_detail_metrics = details.get("activityDetailMetrics", [])

        # Mappa indice → tipo metrica
        descriptor_map = {}
        for desc in metric_descriptors:
            key = desc.get("metricsType", "")
            idx = desc.get("metricsIndex", -1)
            descriptor_map[idx] = key

        # Estrai metriche per ogni timestamp
        for metrics_entry in activity_detail_metrics:
            metrics = metrics_entry.get("metrics", [])

            entry = {}
            for i, val in enumerate(metrics):
                metric_type = descriptor_map.get(i, f"unknown_{i}")
                entry[metric_type] = val

            # Calcola il pace in formato leggibile
            speed = entry.get("directSpeed", 0) or entry.get("Speed", 0) or 0
            if speed > 0:
                pace_sec_km = 1000 / speed
                entry["pace_sec_km"] = round(pace_sec_km, 1)
                entry["pace_str"] = sec_to_pace(pace_sec_km)
            else:
                entry["pace_sec_km"] = None
                entry["pace_str"] = None

            # Cadenza (passi/min)
            cadence = entry.get("directRunCadence", 0) or entry.get("directBikeCadence", 0) or 0
            if cadence:
                entry["cadence_steps_per_min"] = cadence * 2  # cicli → passi
            else:
                entry["cadence_steps_per_min"] = None

            metrics_per_second.append(entry)

        result["metrics_per_second"] = metrics_per_second
        result["metrics_sample_count"] = len(metrics_per_second)
        print(f"✓ Metrics: {len(metrics_per_second)} campioni")

    except Exception as e:
        result["errors"].append(f"Details: {str(e)}")
        print(f"⚠️ Details error: {e}")

    # ── 5. SUMMARY STATISTICO ─────────────────────────────────────────────────
    try:
        if result["lap_data"]:
            paces = [l["avg_pace_sec_km"] for l in result["lap_data"] if l["avg_pace_sec_km"] > 0]
            cadences = [l["avg_cadence"] for l in result["lap_data"] if l.get("avg_cadence")]
            hrs = [l["avg_hr"] for l in result["lap_data"] if l.get("avg_hr")]

            best_lap = min(result["lap_data"], key=lambda l: l["avg_pace_sec_km"]
                           if l["avg_pace_sec_km"] > 0 else 9999)
            worst_lap = max(result["lap_data"], key=lambda l: l["avg_pace_sec_km"]
                            if l["avg_pace_sec_km"] > 0 else 0)

            result["summary"] = {
                "total_laps": len(result["lap_data"]),
                "avg_pace_overall": sec_to_pace(sum(paces)/len(paces)) if paces else "N/A",
                "best_lap": {
                    "lap": best_lap["lap_number"],
                    "pace": best_lap["avg_pace"],
                    "distance_km": best_lap["distance_km"],
                },
                "worst_lap": {
                    "lap": worst_lap["lap_number"],
                    "pace": worst_lap["avg_pace"],
                    "distance_km": worst_lap["distance_km"],
                },
                "avg_cadence": round(sum(cadences)/len(cadences)) if cadences else None,
                "avg_hr": round(sum(hrs)/len(hrs)) if hrs else None,
                "pace_variation_sec": round(max(paces)-min(paces)) if paces else None,
            }
    except Exception as e:
        result["errors"].append(f"Summary: {str(e)}")

    return result


def build_granular_context_for_claude(activity_details: dict, base_activity: dict) -> str:
    """Costruisce un contesto ricco con dati granulari per Claude."""

    context = f"=== ANALISI DETTAGLIATA ATTIVITÀ ===\n"
    context += f"Attività: {base_activity.get('nome', 'N/A')}\n"
    context += f"Data: {base_activity.get('data', 'N/A')}\n"
    context += f"Sport: {base_activity.get('sport', 'N/A')}\n"
    context += f"Distanza totale: {base_activity.get('distanza_km', 0)} km\n"
    context += f"Durata: {base_activity.get('durata_str', 'N/A')}\n"
    context += f"FC media: {base_activity.get('fc_media', 'N/A')} bpm\n"
    context += f"Pace medio: {base_activity.get('pace', 'N/A')}\n\n"

    # Summary statistico
    if activity_details.get("summary"):
        s = activity_details["summary"]
        context += "=== STATISTICHE CHIAVE ===\n"
        context += f"Pace medio complessivo: {s.get('avg_pace_overall', 'N/A')}\n"
        context += f"Cadenza media: {s.get('avg_cadence', 'N/A')} cicli/min\n"
        context += f"FC media: {s.get('avg_hr', 'N/A')} bpm\n"
        context += f"Variazione pace (peggiore - migliore): {s.get('pace_variation_sec', 'N/A')} sec/km\n"
        if s.get("best_lap"):
            context += (
                f"Miglior km: km {s['best_lap']['lap']} "
                f"in {s['best_lap']['pace']}\n"
            )
        if s.get("worst_lap"):
            context += (
                f"Peggior km: km {s['worst_lap']['lap']} "
                f"in {s['worst_lap']['pace']}\n"
            )
        context += "\n"

    # Dati lap
    if activity_details.get("lap_data"):
        context += "=== DATI KM / LAP ===\n"
        for lap in activity_details["lap_data"]:
            context += (
                f"Km {lap['lap_number']}: "
                f"pace {lap['avg_pace']} | "
                f"FC {lap.get('avg_hr', 'N/A')}bpm | "
                f"cadenza {lap.get('avg_cadence', 'N/A')} cicli/min"
            )
            if lap.get("avg_stride_length"):
                context += f" | passo {lap['avg_stride_length']}cm"
            context += "\n"
        context += "\n"

    # GPS summary (non tutti i punti, troppi)
    if activity_details.get("gps_points"):
        pts = activity_details["gps_points"]
        context += f"=== GPS ===\n"
        context += f"Punti GPS totali: {len(pts)}\n"

        # Ogni 10% del percorso, mostra un punto
        step = max(1, len(pts) // 10)
        context += "Campionatura posizioni (ogni ~10% del percorso):\n"
        for i in range(0, len(pts), step):
            pt = pts[i]
            context += (
                f"  {i+1}. lat:{pt['lat']:.5f} lon:{pt['lon']:.5f}"
                f"{' ele:'+str(pt['elevation'])+'m' if pt.get('elevation') else ''}"
                f"{' FC:'+str(pt['hr'])+'bpm' if pt.get('hr') else ''}"
                f"{' cad:'+str(pt.get('cadence',''))+'spm' if pt.get('cadence') else ''}\n"
            )
        context += "\n"

    return context

# ─────────────────────────────────────────────────────────────────────────────
# WORKOUT BUILDER (invariato da v5)
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
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport_info,
                             "workoutSteps": steps_garmin}],
    }
    if sport == "swimming":
        payload["poolLength"] = float(pool_length)
        payload["poolLengthUnit"] = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
    return payload


def upload_to_garmin(garmin, workout_payload, scheduled_date):
    result = garmin.upload_workout(workout_payload)
    workout_id = result.get("workoutId") or result.get("detailId")
    if not workout_id:
        raise Exception(f"Garmin non ha ritornato un workout ID: {result}")
    garmin.schedule_workout(workout_id, scheduled_date)
    return workout_id


def format_workout_preview(workout_data: dict) -> str:
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


def detect_intent(message: str, pending_workout: dict) -> str:
    msg_lower = message.lower().strip()
    if pending_workout:
        confirm_words = ["sì", "si", "yes", "ok", "confermo", "carica", "vai",
                         "procedi", "perfetto", "ottimo", "va bene", "certo", "sure"]
        cancel_words = ["no", "annulla", "cancel", "stop", "aspetta", "modifica",
                        "cambia", "non caricare"]
        if any(w in msg_lower for w in confirm_words):
            return "confirm"
        if any(w in msg_lower for w in cancel_words):
            return "cancel"
        date_keywords = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì",
                         "sabato", "domenica", "domani", "dopodomani", "oggi", "2026"]
        if any(w in msg_lower for w in date_keywords):
            return "change_date"

    create_keywords = ["crea", "voglio fare", "metti", "aggiungi", "pianifica",
                       "schedula", "nuovo allenamento", "workout", "allenamento",
                       "sessione", "carica sul calendario"]
    if any(w in msg_lower for w in create_keywords):
        return "create_workout"
    return "chat"


def generate_workout_with_claude(client, message: str, context: str, tomorrow: str) -> dict:
    prompt = f"""
{context}

L'utente ha scritto: "{message}"

Genera un workout in JSON PURO (zero markdown, zero backtick, zero testo extra).
Se l'utente non specifica una data, usa domani ({tomorrow}).

JSON con struttura ESATTA:
{{
  "name": "Nome breve",
  "description": "Descrizione breve",
  "sport": "running",
  "scheduled_date": "{tomorrow}",
  "duration_minutes": 60,
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
RISPONDI SOLO CON IL JSON.
"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS BASE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "version": "6.0.0"}


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
        } for item in items]
        return {"year": year, "month": month, "total": len(workouts), "items": workouts}
    except Exception as e:
        raise HTTPException(500, f"Errore calendario: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# NUOVO ENDPOINT: DATI GRANULARI ATTIVITÀ
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/activity/{activity_id}/details")
async def get_activity_details(activity_id: str):
    """
    Ritorna i dati granulari di una singola attività:
    - GPS punto per punto (lat, lon, elevazione, FC, cadenza)
    - Ritmo per secondo
    - Dati lap/km dettagliati (pace, FC, cadenza, passo)
    - Statistiche chiave (miglior/peggior km, variazione pace)
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    print(f"Scaricando dati granulari per attività {activity_id}...")

    details = parse_gps_and_metrics(user_session["garmin"], activity_id)

    return {
        "activity_id": activity_id,
        "gps_points_count": details.get("gps_points_count", 0),
        "total_laps": details.get("total_laps", 0),
        "metrics_sample_count": details.get("metrics_sample_count", 0),
        "summary": details.get("summary", {}),
        "lap_data": details.get("lap_data", []),
        "gps_points": details.get("gps_points", []),
        "metrics_per_second": details.get("metrics_per_second", [])[:500],  # max 500 campioni
        "errors": details.get("errors", []),
    }


@app.get("/activity/{activity_id}/laps")
async def get_activity_laps(activity_id: str):
    """Ritorna solo i dati lap/km (veloce, senza GPS)."""
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    try:
        splits = user_session["garmin"].get_activity_splits(activity_id)
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
                "cadenza_cicli_min": avg_cadence or None,
                "cadenza_passi_min": avg_cadence * 2 if avg_cadence else None,
                "passo_cm": lap.get("avgStrideLength") or None,
                "dislivello_m": lap.get("elevationGain") or None,
                "calorie": lap.get("calories") or None,
            })

        return {"activity_id": activity_id, "total_laps": len(lap_data), "laps": lap_data}

    except Exception as e:
        raise HTTPException(500, f"Errore laps: {str(e)}")


@app.get("/activity/{activity_id}/gps")
async def get_activity_gps(activity_id: str, sample_every: int = Query(10)):
    """
    Ritorna i punti GPS dell'attività.
    sample_every: prendi 1 punto ogni N (default 10, per non restituire troppi dati)
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    try:
        gpx_data = user_session["garmin"].download_activity(
            activity_id,
            dl_fmt=user_session["garmin"].ActivityDownloadFormat.GPX
        )

        import xml.etree.ElementTree as ET
        import math
        ns = {
            "gpx": "http://www.topografix.com/GPX/1/1",
            "ns3": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
        }

        if isinstance(gpx_data, bytes):
            gpx_str = gpx_data.decode("utf-8")
        else:
            gpx_str = str(gpx_data)

        root = ET.fromstring(gpx_str)
        track_points = root.findall(".//gpx:trkpt", ns)

        gps_points = []
        prev_lat, prev_lon = None, None
        cumulative_distance = 0

        for i, pt in enumerate(track_points):
            if i % sample_every != 0:
                continue

            lat = float(pt.attrib.get("lat", 0))
            lon = float(pt.attrib.get("lon", 0))
            ele = pt.find("gpx:ele", ns)
            time_el = pt.find("gpx:time", ns)
            hr_el = pt.find(".//ns3:hr", ns)
            cad_el = pt.find(".//ns3:cad", ns)

            dist_from_prev = 0
            if prev_lat is not None:
                dlat = math.radians(lat - prev_lat)
                dlon = math.radians(lon - prev_lon)
                a = (math.sin(dlat/2)**2 +
                     math.cos(math.radians(prev_lat)) *
                     math.cos(math.radians(lat)) *
                     math.sin(dlon/2)**2)
                dist_from_prev = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

            cumulative_distance += dist_from_prev

            gps_points.append({
                "index": i,
                "lat": lat,
                "lon": lon,
                "elevation_m": float(ele.text) if ele is not None else None,
                "time": time_el.text if time_el is not None else None,
                "hr": int(hr_el.text) if hr_el is not None else None,
                "cadence_spm": int(cad_el.text) * 2 if cad_el is not None else None,
                "cumulative_km": round(cumulative_distance / 1000, 3),
            })
            prev_lat, prev_lon = lat, lon

        return {
            "activity_id": activity_id,
            "total_points": len(gps_points),
            "sample_rate": f"1 ogni {sample_every} punti originali",
            "gps_points": gps_points,
        }

    except Exception as e:
        raise HTTPException(500, f"Errore GPS: {str(e)}")


@app.post("/activity/{activity_id}/analyze")
async def analyze_activity_with_ai(activity_id: str):
    """
    Scarica i dati granulari e li analizza con Claude.
    Ritorna un'analisi dettagliata su GPS, lap, cadenza, passo.
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    # Trova l'attività base
    base_activity = next(
        (a for a in user_session["attivita_raw"] if a.get("garmin_id") == str(activity_id)),
        {"nome": "Attività", "data": "N/A", "sport": "running",
         "distanza_km": 0, "durata_str": "N/A", "fc_media": None, "pace": None}
    )

    # Scarica dati granulari
    details = parse_gps_and_metrics(user_session["garmin"], activity_id)

    # Costruisci contesto per Claude
    base_context = build_context_for_claude(user_session["metriche"], user_session["attivita_raw"])
    granular_context = build_granular_context_for_claude(details, base_activity)

    full_context = base_context + "\n\n" + granular_context

    client_ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client_ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system="""Sei un coach esperto di triathlon che analizza i dati GPS e di performance di Alessandro.
Hai accesso a dati granulari reali: GPS, lap km per km, cadenza, passo, FC.
Rispondi SEMPRE in italiano. Sii specifico con i numeri. Sii costruttivo.""",
        messages=[{
            "role": "user",
            "content": f"{full_context}\n\nAnalizza questa sessione in dettaglio:\n"
                       f"1. Come è andato il ritmo km per km?\n"
                       f"2. La cadenza è ottimale? (ideale corsa: 170-180 spm)\n"
                       f"3. C'è stato un calo di prestazione nel corso dell'attività?\n"
                       f"4. Cosa migliorare per la prossima sessione?\n"
                       f"5. Come si confronta con le sessioni precedenti?"
        }]
    )

    return {
        "status": "success",
        "activity_id": activity_id,
        "activity_name": base_activity.get("nome"),
        "analysis": response.content[0].text,
        "raw_data": {
            "summary": details.get("summary", {}),
            "lap_count": len(details.get("lap_data", [])),
            "gps_points": len(details.get("gps_points", [])),
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT CHAT (invariato da v5 con aggiunta analisi attività)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(request: ChatMessage):
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    conv_id = request.conversation_id or "default"
    if conv_id not in conversation_states:
        conversation_states[conv_id] = {"pending_workout": None, "history": []}

    state = conversation_states[conv_id]
    pending = state.get("pending_workout")
    message = request.message.strip()

    client_ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    context = build_context_for_claude(user_session["metriche"], user_session["attivita_raw"])
    today = date.today().isoformat()
    tomorrow = str(date.today() + __import__('datetime').timedelta(days=1))

    intent = detect_intent(message, pending)

    if intent == "confirm" and pending:
        try:
            garmin_steps = steps_to_garmin_format(pending["steps"])
            payload = build_garmin_workout_payload(
                name=pending["name"], sport=pending["sport"],
                steps_garmin=garmin_steps, description=pending.get("description", ""),
            )
            workout_id = upload_to_garmin(user_session["garmin"], payload, pending["scheduled_date"])
            state["pending_workout"] = None
            return {
                "status": "success",
                "message": (f"✅ **Workout caricato su Garmin!**\n\n"
                            f"**{pending['name']}** è nel tuo calendario per il "
                            f"**{pending['scheduled_date']}**. Buon allenamento! 💪"),
                "action": "workout_uploaded",
                "workout_id": workout_id,
            }
        except Exception as e:
            state["pending_workout"] = None
            raise HTTPException(500, f"Errore Garmin: {str(e)}")

    if intent == "cancel" and pending:
        state["pending_workout"] = None
        return {"status": "success",
                "message": "❌ Annullato. Dimmi se vuoi crearne uno diverso!",
                "action": "workout_cancelled"}

    if intent == "change_date" and pending:
        date_response = client_ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{"role": "user",
                       "content": f"Oggi è {today}. L'utente ha scritto: \"{message}\". "
                                  f"Estrai la data ISO YYYY-MM-DD. Solo la data."}]
        )
        new_date = date_response.content[0].text.strip()
        pending["scheduled_date"] = new_date
        state["pending_workout"] = pending
        preview = format_workout_preview(pending)
        return {"status": "success",
                "message": f"📅 Data aggiornata a **{new_date}**!\n\n{preview}\n\n"
                           f"Vuoi che lo carico? **Sì** per confermare, **No** per annullare.",
                "action": "date_changed", "pending_workout": pending}

    if intent == "create_workout":
        try:
            workout_data = generate_workout_with_claude(client_ai, message, context, tomorrow)
            state["pending_workout"] = workout_data
            preview = format_workout_preview(workout_data)
            return {
                "status": "success",
                "message": (f"Ho creato questo workout:\n\n{preview}\n\n---\n"
                            f"Vuoi che lo carico su Garmin per il **{workout_data['scheduled_date']}**?\n"
                            f"**Sì** per confermare, **No** per annullare, "
                            f"o dimmi una data diversa."),
                "action": "workout_preview",
                "pending_workout": workout_data,
            }
        except Exception as e:
            return {"status": "success",
                    "message": "Scusa, riprova con più dettagli sull'allenamento che vuoi fare.",
                    "action": "error"}

    # Chat normale
    state["history"].append({"role": "user", "content": message})
    if len(state["history"]) > 20:
        state["history"] = state["history"][-20:]

    messages_for_claude = [
        {"role": "user", "content": f"{context}\n\n{state['history'][0]['content']}"}
    ] + state["history"][1:]

    response = client_ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="""Sei un coach esperto di triathlon che allena Alessandro.
Hai accesso ai suoi VERI dati Garmin inclusi GPS, lap, cadenza, passo.
Rispondi SEMPRE in italiano. Sii specifico con i numeri reali.
Per analisi dettagliate di una corsa specifica, suggerisci di usare
la sezione Attività → Analizza con AI.""",
        messages=messages_for_claude,
    )

    reply = response.content[0].text
    state["history"].append({"role": "assistant", "content": reply})
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
    garmin_steps = steps_to_garmin_format(pending["steps"])
    payload = build_garmin_workout_payload(
        name=pending["name"], sport=pending["sport"], steps_garmin=garmin_steps)
    workout_id = upload_to_garmin(user_session["garmin"], payload, pending["scheduled_date"])
    state["pending_workout"] = None
    return {"status": "success", "workout_id": workout_id,
            "message": f"✅ Workout caricato per {pending['scheduled_date']}!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
