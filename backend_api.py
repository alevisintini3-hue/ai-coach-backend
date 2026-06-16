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
    # Il frontend rimanda il pending state ad ogni chiamata
    # Questo garantisce che funzioni anche dopo restart del server
    pending_workout: Optional[dict] = None
    pending_plan: Optional[List[dict]] = None

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
            # workoutId presente = l'attività e stata eseguita da un workout strutturato
            "workout_id": str(a.get("workoutId")) if a.get("workoutId") else None,
            "is_structured": bool(a.get("workoutId")),
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

        # Garmin a volte ritorna {"lapDTOs": [...]} invece di una lista diretta
        if isinstance(splits, dict):
            splits = splits.get("lapDTOs") or splits.get("splits") or []

        if not splits:
            print(f"⚠️ Nessun lap per {activity_id}")
            return []

        lap_data = []
        for lap in splits:
            distance_m = lap.get("distance", 0) or 0
            duration_sec = lap.get("duration", 0) or lap.get("movingDuration", 0) or 0
            avg_speed = lap.get("averageSpeed", 0) or lap.get("avgSpeed", 0) or 0
            pace_sec_km = (1000 / avg_speed) if avg_speed > 0 else 0
            avg_cadence = (lap.get("averageRunCadence") or lap.get("avgRunCadence")
                           or lap.get("averageBikeCadence") or 0)

            lap_data.append({
                "lap": lap.get("lapIndex", len(lap_data) + 1),
                "distance_km": round(distance_m / 1000, 3),
                "duration_str": f"{int(duration_sec//60)}:{int(duration_sec%60):02d}",
                "pace": sec_to_pace(pace_sec_km),
                "pace_sec_km": round(pace_sec_km, 1),
                "fc_media": lap.get("averageHR") or lap.get("avgHR") or None,
                "fc_max": lap.get("maxHR") or None,
                "cadenza_cicli": avg_cadence or None,
                "cadenza_passi_min": int(avg_cadence * 2) if avg_cadence else None,
                "passo_cm": lap.get("avgStrideLength") or None,
                "dislivello_m": lap.get("elevationGain") or None,
            })
        print(f"  ✓ {len(lap_data)} lap scaricati")
        return lap_data
    except Exception as e:
        import traceback
        print(f"⚠️ Lap error per {activity_id}: {e}")
        print(traceback.format_exc())
        return []


def fetch_detailed_metrics(garmin: Garmin, activity_id: str) -> list:
    """
    Scarica le metriche dettagliate punto per punto dalla Garmin API.
    Campiona per avere ~1 punto ogni minuto/200m.
    Robusto ai diversi nomi di campo che Garmin usa.
    """
    try:
        details = garmin.get_activity_details(activity_id, maxChartSize=2000)

        if not details:
            print(f"⚠️ get_activity_details ha ritornato vuoto per {activity_id}")
            return []

        metric_descriptors = details.get("metricDescriptors", [])
        activity_detail_metrics = details.get("activityDetailMetrics", [])

        print(f"  📈 Details: {len(activity_detail_metrics)} campioni, "
              f"{len(metric_descriptors)} metriche disponibili")

        if not activity_detail_metrics:
            print(f"⚠️ Nessun activityDetailMetrics per {activity_id}")
            return []

        # Mappa indice → tipo metrica (i nomi sono tipo "directSpeed", "directHeartRate")
        descriptor_map = {}
        for desc in metric_descriptors:
            key = desc.get("key") or desc.get("metricsType", "")
            idx = desc.get("metricsIndex", -1)
            descriptor_map[idx] = key

        # Log dei nomi metriche disponibili (utile per debug)
        available_keys = list(descriptor_map.values())
        print(f"  📊 Metriche: {', '.join(available_keys[:12])}")

        total = len(activity_detail_metrics)
        # Campiona per avere circa 60-80 punti totali (buon dettaglio, non troppo testo)
        sample_rate = max(1, total // 70)

        points = []
        for i, entry in enumerate(activity_detail_metrics):
            if i % sample_rate != 0:
                continue

            metrics = entry.get("metrics", [])
            raw = {}
            for idx, val in enumerate(metrics):
                key = descriptor_map.get(idx, "")
                if key:
                    raw[key] = val

            # Distanza cumulativa (prova diversi nomi)
            dist_val = (raw.get("sumDistance") or raw.get("directDistance") or 0)
            cumulative_km = dist_val / 1000 if dist_val else 0

            # Velocità → pace (m/s)
            speed = (raw.get("directSpeed") or raw.get("sumMovingDuration")
                     or raw.get("directRunCadence") and 0 or 0)
            speed = raw.get("directSpeed") or raw.get("weightedMeanSpeed") or 0
            if speed and speed > 0:
                pace_sec = 1000 / speed
                pace_str = sec_to_pace(pace_sec)
            else:
                pace_sec = None
                pace_str = None

            # Cadenza
            cad = (raw.get("directRunCadence") or raw.get("directBikeCadence")
                   or raw.get("directDoubleCadence") or 0)
            cadence_spm = int(cad * 2) if cad and cad < 130 else (int(cad) if cad else None)

            # HR
            hr = raw.get("directHeartRate") or raw.get("heartRate") or None

            # Elevazione
            elevation = raw.get("directElevation")
            if elevation is None:
                elevation = raw.get("directAltitude")

            # Performance condition
            perf = raw.get("directPerformanceCondition")

            points.append({
                "km": round(cumulative_km, 3),
                "pace": pace_str,
                "pace_sec_km": round(pace_sec, 1) if pace_sec else None,
                "hr": int(hr) if hr else None,
                "elevation_m": round(elevation, 1) if elevation is not None else None,
                "cadence_spm": cadence_spm,
                "performance_condition": perf,
            })

        # Conta quanti punti hanno dati utili
        with_pace = sum(1 for p in points if p["pace"])
        with_hr = sum(1 for p in points if p["hr"])
        print(f"  ✓ {len(points)} punti campionati | {with_pace} con pace | {with_hr} con HR")

        return points

    except Exception as e:
        import traceback
        print(f"⚠️ Detailed metrics error per {activity_id}: {e}")
        print(traceback.format_exc())
        return []


def fetch_gps_data(garmin: Garmin, activity_id: str, sample_every: int = 5) -> list:
    """Scarica punti GPS — campiona ogni 5 punti (più denso di prima)."""
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
                "elevation_m": round(float(ele.text), 1) if ele is not None else None,
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


def build_granular_context(activity: dict, lap_data: list,
                           detailed_metrics: list, gps_points: list) -> str:
    """
    Costruisce il contesto analitico completo per Claude.
    Include: lap, pace istantaneo punto per punto, HR, elevazione,
    cadenza, performance condition.
    """
    ctx = f"\n=== ANALISI DETTAGLIATA ===\n"
    ctx += f"Attività: {activity.get('nome')} | Data: {activity.get('data')}\n"
    ctx += f"Sport: {activity.get('sport')} | Distanza: {activity.get('distanza_km')}km\n"
    ctx += f"Durata: {activity.get('durata_str')} | Pace medio: {activity.get('pace')}\n"
    ctx += f"FC media: {activity.get('fc_media')}bpm | FC max: {activity.get('fc_max')}bpm\n\n"

    # ── LAP KM PER KM ─────────────────────────────────────────────────────────
    if lap_data:
        paces = [l["pace_sec_km"] for l in lap_data if l["pace_sec_km"] > 0]
        ctx += "SPLIT KM PER KM:\n"
        for lap in lap_data:
            ctx += (
                f"  Km {lap['lap']:2d}: pace {lap['pace']:8s} | "
                f"FC {str(lap['fc_media'] or 'N/A'):>6s}bpm | "
                f"cad {str(lap['cadenza_passi_min'] or 'N/A'):>5s}spm | "
                f"passo {str(lap['passo_cm'] or 'N/A'):>5s}cm | "
                f"dislivello {str(lap.get('dislivello_m') or 'N/A'):>5s}m\n"
            )
        if paces:
            best = min(paces)
            worst = max(paces)
            avg = sum(paces) / len(paces)
            ctx += f"\n  📊 Best km: {sec_to_pace(best)} | Worst km: {sec_to_pace(worst)} "
            ctx += f"| Variazione: {int(worst-best)}sec/km\n"
            # Rileva calo progressivo
            if len(paces) >= 3:
                first_half = paces[:len(paces)//2]
                second_half = paces[len(paces)//2:]
                avg_first = sum(first_half) / len(first_half)
                avg_second = sum(second_half) / len(second_half)
                delta = avg_second - avg_first
                if delta > 10:
                    ctx += f"  ⚠️ Calo di ritmo nella seconda metà: +{int(delta)}sec/km\n"
                elif delta < -10:
                    ctx += f"  ✅ Negative split! Accelerazione nella seconda metà: {int(abs(delta))}sec/km\n"
        ctx += "\n"

    # ── METRICHE PUNTO PER PUNTO ──────────────────────────────────────────────
    if detailed_metrics:
        ctx += f"DATI PUNTO PER PUNTO ({len(detailed_metrics)} campioni):\n"
        ctx += f"{'km':>6} | {'pace':>8} | {'HR':>5} | {'ele':>5} | {'cad':>5} | {'PC':>5}\n"
        ctx += f"{'─'*6}-+-{'─'*8}-+-{'─'*5}-+-{'─'*5}-+-{'─'*5}-+-{'─'*5}\n"

        # Per non fare troppo testo, mostra ogni punto (già campionato ogni 5)
        # ma limita a max 100 righe
        step = max(1, len(detailed_metrics) // 100)
        for pt in detailed_metrics[::step]:
            ctx += (
                f"  {pt['km']:>5.2f} | "
                f"{pt['pace'] or 'N/A':>8} | "
                f"{str(pt['hr'] or ''):>5} | "
                f"{str(pt['elevation_m'] or ''):>5} | "
                f"{str(pt['cadence_spm'] or ''):>5} | "
                f"{str(pt['performance_condition'] or ''):>5}\n"
            )

        # Statistiche derivate
        hrs = [p["hr"] for p in detailed_metrics if p.get("hr")]
        eles = [p["elevation_m"] for p in detailed_metrics if p.get("elevation_m")]
        cads = [p["cadence_spm"] for p in detailed_metrics if p.get("cadence_spm")]
        pcs = [p["performance_condition"] for p in detailed_metrics
               if p.get("performance_condition")]
        paces_inst = [p["pace_sec_km"] for p in detailed_metrics
                      if p.get("pace_sec_km") and 180 < p["pace_sec_km"] < 900]

        ctx += "\nSTATISTICHE DERIVATE:\n"
        if hrs:
            ctx += f"  HR: min {min(hrs)} | max {max(hrs)} | media {sum(hrs)//len(hrs)}bpm\n"
        if eles:
            ctx += f"  Elevazione: min {min(eles):.0f}m | max {max(eles):.0f}m | "
            ctx += f"dislivello totale +{max(eles)-min(eles):.0f}m\n"
        if cads:
            ctx += f"  Cadenza: media {sum(cads)//len(cads)}spm | "
            ctx += f"min {min(cads)} | max {max(cads)}spm\n"
            under170 = sum(1 for c in cads if c < 170)
            ctx += f"  Punti sotto 170spm (sotto-ottimale): {under170}/{len(cads)} "
            ctx += f"({100*under170//len(cads)}%)\n"
        if pcs:
            ctx += f"  Performance Condition: media {sum(pcs)/len(pcs):.1f} | "
            ctx += f"min {min(pcs):.1f} | max {max(pcs):.1f}\n"
        if paces_inst:
            ctx += f"  Pace istantaneo: min {sec_to_pace(min(paces_inst))} | "
            ctx += f"max {sec_to_pace(max(paces_inst))}\n"

        ctx += "\n"

    # ── GPS ────────────────────────────────────────────────────────────────────
    if gps_points:
        ctx += f"GPS: {len(gps_points)} punti campionati\n"
        # Solo ogni 20% del percorso per non appesantire troppo
        step = max(1, len(gps_points) // 5)
        for pt in gps_points[::step]:
            ctx += (
                f"  @{pt['cumulative_km']:.1f}km: "
                f"lat {pt['lat']:.5f} lon {pt['lon']:.5f}"
                f"{' ele:'+str(pt['elevation_m'])+'m' if pt.get('elevation_m') else ''}"
                f"{' FC:'+str(pt['hr'])+'bpm' if pt.get('hr') else ''}\n"
            )

    return ctx

# ─────────────────────────────────────────────────────────────────────────────
# CONTESTO BASE PER CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

def build_base_context(metriche_sport: dict, attivita_raw: list) -> str:
    now = datetime.now()
    day_ita = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]
    month_ita = ["","gennaio","febbraio","marzo","aprile","maggio","giugno",
                 "luglio","agosto","settembre","ottobre","novembre","dicembre"]

    ctx = "=== PROFILO ATLETA ===\n"
    ctx += "Nome: Alessandro | Paese: Germania\n"
    ctx += "Obiettivo: Triathlon olimpico\n"
    ctx += "Baseline: nuoto 2km/40min (2:00/100m), corsa 12km a 5:40/km\n"
    ctx += (f"Data e ora attuale: {day_ita[now.weekday()]} "
            f"{now.day} {month_ita[now.month]} {now.year}, "
            f"ore {now.strftime('%H:%M')}\n\n")

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
    import re as _re
    msg = message.lower().strip()
    pending = state.get("pending_workout")
    pending_plan = state.get("pending_plan")

    NUM_WORDS = ["due", "tre", "quattro", "cinque", "sei",
                 "sette", "otto", "nove", "dieci"]

    CONFIRM_WORDS = [
        "sì", "si", "yes", "ok", "confermo", "carica", "caricali",
        "carica tutto", "caricali sul garmin", "vai", "procedi",
        "perfetto", "ottimo", "certo", "sure", "fatto", "dai",
        "mettili", "aggiungili", "salvali", "li voglio",
        "tutti", "tutti e tre", "tutti e due", "tutte",
    ]
    CANCEL_WORDS = [
        "no", "annulla", "cancel", "stop", "lascia perdere",
        "non caricare", "elimina", "cancella",
    ]

    if pending or pending_plan:
        if any(w in msg for w in CONFIRM_WORDS):
            return "confirm"
        if any(w in msg for w in CANCEL_WORDS):
            return "cancel"
        if any(w in msg for w in ["dettagli", "mostra", "vedi step"]):
            return "show_details"
        if any(w in msg for w in ["lunedì", "martedì", "mercoledì", "giovedì",
                                   "venerdì", "sabato", "domenica", "domani",
                                   "dopodomani", "2026", "prossimo"]):
            return "change_date"

    if any(w in msg for w in ["caricali sul garmin", "carica sul garmin",
                               "carica tutto sul garmin", "metti sul garmin"]):
        return "confirm"

    # PIANO: numeri (cifre O parole) + plurale sport/giorni
    has_num = (_re.search(r"\b[2-9]\b|\b1[0-9]\b", msg) is not None
               or any(n in msg for n in NUM_WORDS))
    if has_num and any(w in msg for w in ["allenament", "session", "workout",
                                           "giorn", "cors", "nuot", "bici",
                                           "ciclism", "palestr"]):
        return "create_plan"

    if any(w in msg for w in [
        "piano", "settimana", "settimane", "programma",
        "prossimi giorni", "prossimi tre", "prossimi 3", "prossimi 5",
        "prossimi 7", "più allenamenti", "tutta la settimana", "mese",
    ]):
        return "create_plan"

    # SINGOLO WORKOUT
    if any(w in msg for w in [
        "crea", "fammi", "fai", "voglio fare", "voglio", "metti", "aggiungi",
        "pianifica", "schedula", "allenamento", "workout", "sessione",
        "carica sul calendario",
    ]):
        return "create_workout"

    # ANALISI
    if any(w in msg for w in [
        "analizza", "analisi", "ultima", "ultimo", "recente",
        "come è andata", "lap", "km per km", "cadenza", "passo",
        "gps", "come sono andato", "performance", "dati",
    ]):
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
    raw = r.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    import re as _re
    match = _re.search(r'\{.*\}', raw, _re.DOTALL)
    if match:
        raw = match.group(0)

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
    raw = r.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    # Estrai solo l'array JSON (dal primo [ all'ultimo ])
    import re as _re
    match = _re.search(r'\[.*\]', raw, _re.DOTALL)
    if match:
        raw = match.group(0)

    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# WORKOUT STRUTTURATI: TARGET vs ESEGUITO
# ─────────────────────────────────────────────────────────────────────────────

def speed_target_to_pace(value_one, value_two):
    """
    Converte un target di velocità Garmin (m/s) in pace mm:ss/km.
    Garmin salva i target di velocita in m/s. Ritorna (pace_min, pace_max) come stringhe.
    """
    def ms_to_pace(ms):
        if not ms or ms <= 0:
            return None
        sec_km = 1000 / ms
        return sec_to_pace(sec_km)

    # value_one e value_two sono i limiti del range di velocita
    p1 = ms_to_pace(value_one) if value_one else None
    p2 = ms_to_pace(value_two) if value_two else None
    return p1, p2


def fetch_structured_workout(garmin: Garmin, workout_id: str) -> dict:
    """
    Scarica un workout strutturato pianificato con i suoi target (pace/HR per step).
    Ritorna una struttura leggibile con gli step e i loro obiettivi.
    """
    try:
        wo = garmin.get_workout_by_id(workout_id)
        if not wo:
            return None

        result = {
            "name": wo.get("workoutName", ""),
            "sport": wo.get("sportType", {}).get("sportTypeKey", ""),
            "steps": [],
        }

        segments = wo.get("workoutSegments", [])
        for seg in segments:
            for step in seg.get("workoutSteps", []):
                parsed = _parse_target_step(step)
                if parsed:
                    if isinstance(parsed, list):
                        result["steps"].extend(parsed)
                    else:
                        result["steps"].append(parsed)

        return result

    except Exception as e:
        print(f"⚠️ fetch_structured_workout error: {e}")
        return None


def _parse_target_step(step: dict, repeat_prefix: str = "") -> any:
    """Estrae il target da uno step del workout (ricorsivo per i repeat)."""
    step_type = step.get("type", "")

    # Repeat group → espandi
    if step_type == "RepeatGroupDTO":
        iterations = step.get("numberOfIterations", 1)
        child_results = []
        for child in step.get("workoutSteps", []):
            parsed = _parse_target_step(child, repeat_prefix=f"{iterations}x ")
            if parsed:
                if isinstance(parsed, list):
                    child_results.extend(parsed)
                else:
                    child_results.append(parsed)
        return child_results

    # Step eseguibile
    step_type_key = step.get("stepType", {}).get("stepTypeKey", "")

    # Durata/distanza obiettivo
    end_cond = step.get("endCondition", {}).get("conditionTypeKey", "")
    end_val = step.get("endConditionValue", 0)

    target_desc = ""
    if end_cond == "distance":
        target_desc = f"{int(end_val)}m" if end_val < 1000 else f"{end_val/1000:.1f}km"
    elif end_cond == "time":
        m, s = divmod(int(end_val), 60)
        target_desc = f"{m}:{s:02d}min" if m else f"{int(end_val)}s"
    elif end_cond == "lap.button":
        target_desc = "fino a lap"

    # Target di pace/velocita
    target_type = step.get("targetType", {})
    target_type_key = target_type.get("workoutTargetTypeKey", "") if target_type else ""

    pace_target = None
    hr_target = None

    if target_type_key in ("pace.zone", "speed.zone"):
        v1 = step.get("targetValueOne")
        v2 = step.get("targetValueTwo")
        p1, p2 = speed_target_to_pace(v1, v2)
        if p1 and p2:
            # ordina (pace piu lento = numero piu grande)
            pace_target = f"{p2}–{p1}"  # p2 e il limite veloce
    elif target_type_key == "heart.rate.zone":
        v1 = step.get("targetValueOne")
        v2 = step.get("targetValueTwo")
        if v1 and v2:
            hr_target = f"{int(v1)}–{int(v2)}bpm"

    return {
        "tipo": step_type_key,
        "obiettivo": f"{repeat_prefix}{target_desc}".strip(),
        "pace_target": pace_target,
        "hr_target": hr_target,
        "descrizione": step.get("description", ""),
    }


def build_target_vs_executed_context(structured: dict, lap_data: list) -> str:
    """
    Costruisce il contesto di confronto TARGET (pianificato) vs ESEGUITO (lap reali).
    Questo e il cuore del valore aggiunto: dice se l'atleta ha rispettato i target.
    """
    if not structured or not structured.get("steps"):
        return ""

    ctx = "\n=== CONFRONTO TARGET vs ESEGUITO ===\n"
    ctx += f"Questo allenamento era STRUTTURATO: \"{structured['name']}\"\n"
    ctx += "L'atleta lo ha selezionato dall'orologio e seguito.\n\n"

    ctx += "TARGET PIANIFICATI:\n"
    for i, s in enumerate(structured["steps"], 1):
        line = f"  Step {i} [{s['tipo']}]: {s['obiettivo']}"
        if s.get("pace_target"):
            line += f" | pace target: {s['pace_target']}/km"
        if s.get("hr_target"):
            line += f" | FC target: {s['hr_target']}"
        if s.get("descrizione"):
            line += f" | {s['descrizione']}"
        ctx += line + "\n"

    ctx += "\nESEGUITO REALE (lap):\n"
    for lap in lap_data:
        ctx += (f"  Lap {lap['lap']}: {lap['distance_km']}km in {lap['duration_str']} "
                f"| pace reale {lap['pace']} | FC {lap.get('fc_media','N/A')}bpm\n")

    ctx += ("\nISTRUZIONE: confronta ogni step pianificato col pace/FC realmente eseguito. "
            "Dì chiaramente se l'atleta e rimasto DENTRO o FUORI dal target, "
            "di quanti secondi/km ha sbagliato, e se e andato troppo forte o troppo piano. "
            "Questo e il dato piu importante dell'analisi.\n")

    return ctx


def ai_analyze_activity(client, message: str, context: str,
                        attivita_raw: list, garmin: Garmin) -> str:
    """
    Trova l'attività rilevante, scarica GPS + metriche punto per punto,
    e ritorna analisi completa con pace istantaneo, HR, elevazione,
    cadenza, performance condition.
    Se l'attivita era strutturata, confronta target vs eseguito.
    """
    msg_lower = message.lower()

    # Determina lo sport richiesto (se specificato)
    sport_richiesto = None
    if any(w in msg_lower for w in ["corsa", "running", "run", "corro", "corse"]):
        sport_richiesto = "running"
    elif any(w in msg_lower for w in ["nuoto", "swimming", "swim", "piscina", "nuotato"]):
        sport_richiesto = "swimming"
    elif any(w in msg_lower for w in ["bici", "cycling", "bike", "ciclismo", "pedalato"]):
        sport_richiesto = "cycling"
    elif any(w in msg_lower for w in ["palestra", "strength", "pesi", "gym"]):
        sport_richiesto = "strength_training"

    candidate = None

    # 1. Se è specificato uno sport, prendi l'ULTIMA attività DI QUELLO SPORT
    if sport_richiesto:
        for att in attivita_raw:
            if sport_richiesto in att.get("sport", ""):
                candidate = att
                break
        if candidate:
            print(f"🎯 Sport richiesto: {sport_richiesto} → {candidate['nome']} ({candidate['data']})")

    # 2. Se chiede "ultima/recente" senza sport, prendi l'ultima in assoluto
    if not candidate and any(w in msg_lower for w in ["ultima", "recente", "ultimo", "last"]):
        candidate = attivita_raw[0] if attivita_raw else None

    # 3. Match per nome attività
    if not candidate:
        for att in attivita_raw[:30]:
            nome = att.get("nome", "").lower()
            if any(word in nome for word in msg_lower.split() if len(word) > 3):
                candidate = att
                break

    # 4. Fallback: ultima attività
    if not candidate and attivita_raw:
        candidate = attivita_raw[0]

    if not candidate:
        return "Non ho trovato attività nel tuo storico Garmin."

    activity_id = candidate.get("garmin_id", "")
    lap_data = []
    detailed_metrics = []
    gps_points = []

    if activity_id:
        print(f"📊 Analisi: {candidate['nome']} ({candidate['data']}, sport={candidate['sport']}, id={activity_id})")
        lap_data = fetch_lap_data(garmin, activity_id)
        detailed_metrics = fetch_detailed_metrics(garmin, activity_id)
        gps_points = fetch_gps_data(garmin, activity_id, sample_every=10)
        print(f"  ✓ {len(lap_data)} lap | {len(detailed_metrics)} metriche | {len(gps_points)} GPS")

    granular_ctx = build_granular_context(candidate, lap_data, detailed_metrics, gps_points)

    # ── CONFRONTO TARGET vs ESEGUITO (solo se allenamento strutturato) ────────
    is_structured = candidate.get("is_structured")
    structured_ctx = ""
    workout_id = candidate.get("workout_id")

    if is_structured and workout_id:
        print(f"  🎯 Allenamento strutturato (workout {workout_id}) — confronto target")
        structured = fetch_structured_workout(garmin, workout_id)
        if structured:
            structured_ctx = build_target_vs_executed_context(structured, lap_data)

    full_ctx = context + granular_ctx + structured_ctx

    # System prompt diverso a seconda del tipo di allenamento
    ANTI_DISCLAIMER = """
IMPORTANTE: Usa i dati che trovi nel contesto. NON scrivere lunghi elenchi di
"cosa non ho accesso" o "problema con i dati". Se un dato specifico manca,
ignoralo silenziosamente e analizza con quello che hai. Vai dritto all'analisi utile.
Non dire mai "ho accesso solo ai dati aggregati": analizza i dati granulari presenti."""

    if structured_ctx:
        system = """Sei un coach esperto di triathlon che analizza i dati reali di Alessandro.
Questo era un ALLENAMENTO STRUTTURATO: Alessandro aveva dei TARGET precisi di pace/FC.
Il tuo compito principale e confrontare TARGET vs ESEGUITO step per step.
Hai accesso a: target pianificati, pace reale, HR, cadenza, elevazione.
Rispondi SEMPRE in italiano. Sii diretto con i numeri: di di quanti sec/km ha sbagliato.
Non usare emoji decorative.""" + ANTI_DISCLAIMER
        question = (
            f"{full_ctx}\n\n"
            f"Richiesta: {message}\n\n"
            f"Analizza in questo ordine:\n"
            f"1. CONFRONTO TARGET vs ESEGUITO: per ogni fase dell'allenamento, "
            f"l'atleta e rimasto nel target di pace? Di quanto ha sbagliato? "
            f"E andato troppo forte o troppo piano?\n"
            f"2. Gestione dello sforzo: ha tenuto il ritmo costante o e calato?\n"
            f"3. HR: coerente con l'intensita richiesta?\n"
            f"4. Cadenza media e % sotto 170spm\n"
            f"5. Valutazione complessiva: ha eseguito bene l'allenamento? Voto sintetico.\n"
            f"6. Cosa migliorare nella prossima sessione strutturata"
        )
    else:
        system = """Sei un coach esperto di triathlon che analizza i dati reali di Alessandro.
Questo era un allenamento LIBERO (corsa casuale, senza target preimpostati).
Hai accesso a: pace istantaneo punto per punto, HR, elevazione, cadenza (spm),
performance condition, split km per km.
Rispondi SEMPRE in italiano. Sii specifico: cita i numeri esatti dai dati.
Non usare emoji decorative.""" + ANTI_DISCLAIMER
        question = (
            f"{full_ctx}\n\n"
            f"Richiesta: {message}\n\n"
            f"Questo e un allenamento libero, quindi confronta col la BASELINE di Alessandro "
            f"(corsa 12km a 5:40/km). Analizza:\n"
            f"1. Pace km per km — calo? negative split? come si confronta con la baseline?\n"
            f"2. HR — trend, zone, picchi\n"
            f"3. Elevazione — impatto sul ritmo\n"
            f"4. Cadenza — media, % sotto 170spm\n"
            f"5. Performance Condition — trend durante la sessione\n"
            f"6. Punti di forza e cosa migliorare\n"
            f"7. Confronto con sessioni precedenti"
        )

    r = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": question}]
    )

    return r.content[0].text


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS BASE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "version": "8.0.0"}


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


@app.get("/debug/activity/{activity_id}")
async def debug_activity(activity_id: str):
    """
    Endpoint diagnostico: mostra cosa ritorna Garmin per una specifica attivita.
    Utile per capire perche i dati granulari non arrivano.
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    garmin = user_session["garmin"]
    result = {"activity_id": activity_id}

    # Test lap data
    try:
        lap = fetch_lap_data(garmin, activity_id)
        result["lap_count"] = len(lap)
        result["lap_sample"] = lap[:3]
    except Exception as e:
        result["lap_error"] = str(e)

    # Test detailed metrics
    try:
        metrics = fetch_detailed_metrics(garmin, activity_id)
        result["metrics_count"] = len(metrics)
        result["metrics_sample"] = metrics[:5]
    except Exception as e:
        result["metrics_error"] = str(e)

    # Test raw details (nomi dei campi disponibili)
    try:
        details = garmin.get_activity_details(activity_id, maxChartSize=100)
        descriptors = details.get("metricDescriptors", [])
        result["available_metrics"] = [
            d.get("key") or d.get("metricsType") for d in descriptors
        ]
        result["total_samples_available"] = len(details.get("activityDetailMetrics", []))
    except Exception as e:
        result["details_error"] = str(e)

    return result


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

    # ── RIPRISTINA STATO DAL FRONTEND PRIMA DI TUTTO ──────────────────────────
    # Il frontend rimanda sempre pending_workout e pending_plan.
    # Se il server Render si è riavviato e ha perso la RAM,
    # questo garantisce che la conferma funzioni comunque.
    if request.pending_workout and not state.get("pending_workout"):
        state["pending_workout"] = request.pending_workout
        print(f"[RESTORE] pending_workout ripristinato: {request.pending_workout.get('name')}")
    if request.pending_plan and not state.get("pending_plan"):
        state["pending_plan"] = request.pending_plan
        print(f"[RESTORE] pending_plan ripristinato: {len(request.pending_plan)} workout")

    client_ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    base_ctx = build_base_context(user_session["metriche"], user_session["attivita_raw"])

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def save_to_history(user_msg: str, assistant_msg: str):
        state["history"].append({"role": "user", "content": user_msg})
        state["history"].append({"role": "assistant", "content": assistant_msg})
        if len(state["history"]) > 40:
            state["history"] = state["history"][:2] + state["history"][-38:]

    def build_messages(current_user_msg: str) -> list:
        if not state["history"]:
            return [{"role": "user", "content": f"{base_ctx}\n\n{current_user_msg}"}]
        messages = list(state["history"])
        messages.append({"role": "user", "content": current_user_msg})
        return messages

    SYSTEM = """Sei un coach esperto di triathlon e fitness che allena Alessandro.
Hai accesso a tutti i suoi dati Garmin reali: attivita passate, GPS, lap, cadenza, passo.
Ricordi TUTTA la conversazione precedente e ci fai riferimento naturalmente.
Rispondi SEMPRE in italiano. Sii specifico, motivante e coerente.

Alessandro si allena in: corsa, nuoto, ciclismo e PALESTRA.
La palestra e parte integrante del training da triatleta:
- Upper body: petto, dorsali, spalle, tricipiti, bicipiti
- Lower body: squat, leg press, affondi, leg curl, calf raise
- Core: plank, russian twist, dead bug, bird dog, hollow hold
- Full body: circuit training funzionale
- Mobilita e stretching: fondamentale per il recupero

Quando crei sessioni di palestra, specifica sempre: esercizi, serie, ripetizioni, recupero.
Non usare emoji decorative nelle risposte.

REGOLA CRITICA: Questa app e INTEGRATA con Garmin Connect.
Il sistema carica automaticamente gli allenamenti su Garmin quando l'utente conferma con un PULSANTE.
Non dire MAI frasi come "non posso caricare su Garmin" o "non ho accesso a Garmin".
Non dire MAI "sto caricando" o "il sistema sta processando il caricamento": il caricamento
avviene SOLO quando l'utente preme il pulsante di conferma, non quando scrivi tu.
Non chiedere MAI "quali vuoi caricare?" o "tutti e tre?": ci pensa il sistema con i pulsanti.
Tu devi solo descrivere gli allenamenti. Il resto e automatico."""

    intent = detect_intent(message, state)

    # ── CONFERMA WORKOUT SINGOLO ──────────────────────────────────────────────
    if intent == "confirm" and state.get("pending_workout"):
        wo = state["pending_workout"]
        try:
            gsteps = steps_to_garmin(wo["steps"])
            payload = make_payload(wo["name"], wo["sport"], gsteps, wo.get("description", ""))
            wid = upload_workout(user_session["garmin"], payload, wo["scheduled_date"])
            state["pending_workout"] = None
            reply = f"{wo['name']} caricato su Garmin per il {wo['scheduled_date']}. Buon allenamento!"
            save_to_history(message, reply)
            return {"status": "success", "message": reply,
                    "action": "workout_uploaded", "workout_id": wid}
        except Exception as e:
            state["pending_workout"] = None
            raise HTTPException(500, f"Errore Garmin: {str(e)}")

    # ── CONFERMA PIANO ────────────────────────────────────────────────────────
    # Ritorna il piano completo al frontend che carica uno alla volta
    if intent == "confirm" and state.get("pending_plan"):
        plan = state["pending_plan"]
        reply = f"Avvio caricamento di {len(plan)} allenamenti su Garmin..."
        save_to_history(message, reply)
        return {
            "status": "success",
            "message": reply,
            "action": "plan_uploading",
            "pending_plan": plan,
            "conversation_id": conv_id,
        }

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
        reply = "\n".join(lines)
        save_to_history(message, reply)
        return {"status": "success", "message": reply,
                "action": "plan_details", "pending_plan": plan}

    # ── CAMBIA DATA ───────────────────────────────────────────────────────────
    if intent == "change_date" and state.get("pending_workout"):
        r = client_ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=20,
            messages=[{"role": "user",
                       "content": f"Oggi è {today}. Utente scrive: \"{message}\". "
                                  f"Estrai data ISO YYYY-MM-DD. Solo la data."}]
        )
        new_date = r.content[0].text.strip()
        state["pending_workout"]["scheduled_date"] = new_date
        preview = format_single_workout(state["pending_workout"])
        reply = f"📅 Data aggiornata a **{new_date}**!\n\n{preview}"
        save_to_history(message, reply)
        return {"status": "success", "message": reply,
                "action": "date_changed", "pending_workout": state["pending_workout"]}

    # ── ANALISI ───────────────────────────────────────────────────────────────
    if intent == "analyze":
        try:
            analysis = ai_analyze_activity(
                client_ai, message, base_ctx,
                user_session["attivita_raw"], user_session["garmin"]
            )
            save_to_history(message, analysis)
            return {"status": "success", "message": analysis, "action": "analysis"}
        except Exception as e:
            reply = "Ho avuto un problema nel scaricare i dati granulari. Ti do l'analisi dai dati sommari."
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "analysis_error"}

    # ── CREA PIANO ────────────────────────────────────────────────────────────
    if intent == "create_plan":
        try:
            plan = ai_generate_training_plan(client_ai, message, base_ctx, today)
            state["pending_plan"] = plan
            state["pending_workout"] = None
            preview = format_plan_preview(plan)
            reply = f"Ho creato questo piano per te:\n\n{preview}"
            save_to_history(message, reply)
            return {"status": "success", "message": reply,
                    "action": "plan_preview", "pending_plan": plan}
        except Exception as e:
            reply = "Scusa, riprova descrivendo il piano (quanti giorni, quali sport, ecc.)"
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "error"}

    # ── CREA WORKOUT SINGOLO ──────────────────────────────────────────────────
    if intent == "create_workout":
        try:
            wo = ai_generate_single_workout(client_ai, message, base_ctx, tomorrow)
            state["pending_workout"] = wo
            state["pending_plan"] = None
            preview = format_single_workout(wo)
            reply = f"Ho creato questo workout:\n\n{preview}"
            save_to_history(message, reply)
            return {"status": "success", "message": reply,
                    "action": "workout_preview", "pending_workout": wo}
        except Exception as e:
            reply = "Scusa, riprova con più dettagli sull'allenamento."
            save_to_history(message, reply)
            return {"status": "success", "message": reply, "action": "error"}

    # ── CHAT NORMALE ──────────────────────────────────────────────────────────
    messages_for_claude = build_messages(message)

    r = client_ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM,
        messages=messages_for_claude,
    )
    reply = r.content[0].text

    if not state["history"]:
        state["history"].append({"role": "user", "content": f"{base_ctx}\n\n{message}"})
        state["history"].append({"role": "assistant", "content": reply})
    else:
        save_to_history(message, reply)

    return {"status": "success", "message": reply, "action": "chat"}


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD PIANO — UN WORKOUT ALLA VOLTA (evita timeout Render)
# ─────────────────────────────────────────────────────────────────────────────

class UploadWorkoutDirectRequest(BaseModel):
    """Il frontend manda il workout completo — zero dipendenza dallo state del server."""
    workout: dict          # il singolo workout con name, sport, scheduled_date, steps
    conversation_id: Optional[str] = "default"


@app.post("/plan/upload-one")
async def plan_upload_one(request: UploadWorkoutDirectRequest):
    """
    Carica UN singolo workout mandato direttamente nel body.
    Non usa nessuno state in RAM — sopravvive a qualsiasi restart di Render.
    Il frontend chiama questo endpoint in un loop, uno per workout.
    """
    global user_session
    if user_session is None:
        raise HTTPException(401, "Chiama /login prima")

    wo = request.workout

    try:
        gsteps = steps_to_garmin(wo["steps"])
        payload = make_payload(
            wo["name"],
            wo["sport"],
            gsteps,
            wo.get("description", ""),
        )
        wid = upload_workout(user_session["garmin"], payload, wo["scheduled_date"])

        return {
            "status": "success",
            "uploaded": {
                "name": wo["name"],
                "sport": wo["sport"],
                "date": wo["scheduled_date"],
                "workout_id": wid,
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "name": wo.get("name", "?"),
            "error": str(e),
        }


@app.post("/plan/cancel")
async def plan_cancel(request: ConfirmWorkoutRequest):
    conv_id = request.conversation_id or "default"
    state = conversation_states.get(conv_id, {})
    state["pending_plan"] = None
    state["pending_workout"] = None
    return {"status": "success", "message": "Piano annullato."}


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
