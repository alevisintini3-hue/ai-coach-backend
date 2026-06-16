"""
app.py - v6
Coach AI-agent — stile TrainingPeaks: pulito, professionale, font chiari, tabelle.
"""

import streamlit as st
import requests
from datetime import date
import calendar as cal_module
import pandas as pd

API = "https://ai-coach-backend-xc9s.onrender.com"

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE PAGINA + CSS TRAININGPEAKS STYLE
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Coach AI-agent",
    page_icon="assets/logo.png" if False else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS ispirato a TrainingPeaks: font Inter, colori neutri, niente emoji decorative
st.markdown("""
<style>
/* Font system */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Header principale */
.tp-header {
    padding: 20px 0 12px 0;
    border-bottom: 2px solid #1a1a2e;
    margin-bottom: 24px;
}
.tp-title {
    font-size: 22px;
    font-weight: 700;
    color: #1a1a2e;
    letter-spacing: -0.3px;
    margin: 0;
}
.tp-subtitle {
    font-size: 13px;
    color: #6b7280;
    font-weight: 400;
    margin-top: 2px;
}

/* Card neutra */
.tp-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.tp-card-title {
    font-size: 11px;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 8px;
}

/* Pending workout/piano — stile alert discreto */
.tp-pending {
    background: #f0f9ff;
    border: 1px solid #0284c7;
    border-left: 4px solid #0284c7;
    border-radius: 4px;
    padding: 14px 18px;
    margin-bottom: 16px;
}
.tp-pending-title {
    font-size: 13px;
    font-weight: 600;
    color: #0284c7;
    margin-bottom: 4px;
}
.tp-pending-sub {
    font-size: 12px;
    color: #374151;
}

/* Tabella allenamenti */
.tp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-top: 8px;
}
.tp-table th {
    background: #f9fafb;
    color: #374151;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #e5e7eb;
}
.tp-table td {
    padding: 10px 12px;
    border-bottom: 1px solid #f3f4f6;
    color: #111827;
    vertical-align: top;
}
.tp-table tr:last-child td { border-bottom: none; }
.tp-table tr:hover td { background: #f9fafb; }

/* Badge sport */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.badge-run  { background: #fef3c7; color: #92400e; }
.badge-swim { background: #dbeafe; color: #1e40af; }
.badge-bike { background: #d1fae5; color: #065f46; }
.badge-gym  { background: #ede9fe; color: #5b21b6; }
.badge-other{ background: #f3f4f6; color: #374151; }

/* Step allenamento */
.step-row {
    display: flex;
    align-items: flex-start;
    padding: 6px 0;
    border-bottom: 1px solid #f3f4f6;
    font-size: 13px;
}
.step-type {
    width: 90px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: #6b7280;
    flex-shrink: 0;
}
.step-detail { color: #111827; }
.step-repeat-block {
    background: #f9fafb;
    border-left: 3px solid #d1d5db;
    padding: 8px 12px;
    margin: 4px 0;
    border-radius: 0 4px 4px 0;
}

/* Chat bubbles */
.chat-user {
    background: #1a1a2e;
    color: #ffffff;
    padding: 10px 14px;
    border-radius: 12px 12px 2px 12px;
    margin: 6px 0 6px 20%;
    font-size: 13px;
    line-height: 1.5;
}
.chat-coach {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    color: #111827;
    padding: 12px 16px;
    border-radius: 2px 12px 12px 12px;
    margin: 6px 20% 6px 0;
    font-size: 13px;
    line-height: 1.6;
}

/* Sidebar */
.sidebar-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #9ca3af;
    margin-bottom: 6px;
}
.sidebar-stat {
    font-size: 20px;
    font-weight: 700;
    color: #1a1a2e;
    line-height: 1;
}
.sidebar-stat-label {
    font-size: 11px;
    color: #6b7280;
    margin-top: 2px;
}

/* Pulsanti stile TP */
div[data-testid="stButton"] > button {
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 500;
    border-radius: 4px;
    letter-spacing: 0.2px;
}

/* Rimuovi padding extra streamlit */
.block-container { padding-top: 1.5rem; }

/* Nasconde hamburger menu Streamlit */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────

for k, v in {
    "logged_in": False,
    "chat_history": [],
    "pending_workout": None,
    "pending_plan": None,
    "conversation_id": "default",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

SPORT_LABEL = {
    "running": "Corsa",
    "swimming": "Nuoto",
    "cycling": "Ciclismo",
    "strength_training": "Palestra",
    "other": "Altro",
}
SPORT_BADGE = {
    "running": "badge-run",
    "swimming": "badge-swim",
    "cycling": "badge-bike",
    "strength_training": "badge-gym",
    "other": "badge-other",
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS GRAFICI
# ─────────────────────────────────────────────────────────────────────────────

def sport_badge(sport: str) -> str:
    label = SPORT_LABEL.get(sport, sport)
    css = SPORT_BADGE.get(sport, "badge-other")
    return f'<span class="badge {css}">{label}</span>'


def render_workout_table(workouts: list):
    """Tabella pulita stile TP per la lista di workout del piano."""
    rows = ""
    for i, wo in enumerate(workouts, 1):
        sport = wo.get("sport", "")
        badge = sport_badge(sport)
        steps = wo.get("steps", [])
        step_summary = _summarize_steps(steps)
        rows += f"""
        <tr>
            <td style="color:#6b7280;font-size:11px;font-weight:600;">{i}</td>
            <td>{wo.get('scheduled_date','')}</td>
            <td>{badge}</td>
            <td style="font-weight:600;">{wo.get('name','')}</td>
            <td style="color:#6b7280;">{step_summary}</td>
        </tr>"""

    st.markdown(f"""
    <table class="tp-table">
      <thead>
        <tr>
          <th>#</th><th>Data</th><th>Sport</th><th>Nome</th><th>Struttura</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)


def render_workout_detail(wo: dict):
    """Dettaglio steps di un singolo workout in stile tabella TP."""
    sport = wo.get("sport", "")
    badge = sport_badge(sport)
    steps = wo.get("steps", [])

    st.markdown(f"""
    <div class="tp-card">
        <div class="tp-card-title">Workout</div>
        <div style="font-size:16px;font-weight:700;color:#1a1a2e;margin-bottom:4px;">
            {wo.get('name','')}
        </div>
        <div style="margin-bottom:12px;">{badge}
            <span style="font-size:12px;color:#6b7280;margin-left:8px;">
                {wo.get('scheduled_date','')}
            </span>
        </div>
    """, unsafe_allow_html=True)

    if steps:
        step_rows = ""
        for s in steps:
            step_rows += _render_step_row(s)
        st.markdown(f"""
        <table class="tp-table">
          <thead>
            <tr>
              <th>Tipo</th><th>Dettaglio</th>
            </tr>
          </thead>
          <tbody>{step_rows}</tbody>
        </table>
        """, unsafe_allow_html=True)

    if wo.get("description"):
        st.markdown(
            f'<div style="font-size:12px;color:#6b7280;margin-top:8px;">'
            f'{wo["description"]}</div>',
            unsafe_allow_html=True
        )

    st.markdown("</div>", unsafe_allow_html=True)


def _render_step_row(s: dict) -> str:
    t = s.get("type", "")
    type_labels = {
        "warmup": "Riscaldamento",
        "cooldown": "Defaticamento",
        "main": "Principale",
        "rest": "Recupero",
        "repeat": "Ripetizioni",
    }
    label = type_labels.get(t, t.upper())

    if t == "repeat":
        count = s.get("repeat_count", 1)
        sub_rows = ""
        for sub in s.get("repeat_steps", []):
            sub_label = type_labels.get(sub.get("type",""), sub.get("type",""))
            sub_detail = _format_step_detail(sub)
            sub_rows += (
                f'<div style="display:flex;gap:12px;padding:3px 0;">'
                f'<span style="width:100px;font-size:11px;color:#9ca3af;">{sub_label}</span>'
                f'<span style="font-size:12px;">{sub_detail}</span></div>'
            )
        detail = (
            f'<span style="font-weight:600;">{count}x</span>'
            f'<div style="margin-top:4px;padding-left:8px;'
            f'border-left:2px solid #e5e7eb;">{sub_rows}</div>'
        )
    else:
        detail = _format_step_detail(s)
        if s.get("description"):
            detail += f' <span style="color:#9ca3af;font-size:11px;">— {s["description"]}</span>'

    return f"<tr><td><b>{label}</b></td><td>{detail}</td></tr>"


def _format_step_detail(s: dict) -> str:
    parts = []
    if s.get("distance_meters"):
        d = s["distance_meters"]
        parts.append(f"{int(d)}m" if d < 1000 else f"{d/1000:.1f}km")
    if s.get("duration_seconds"):
        sec = s["duration_seconds"]
        m, sc = divmod(sec, 60)
        parts.append(f"{m}:{sc:02d} min" if m > 0 else f"{sc}s")
    if s.get("description") and not s.get("distance_meters") and not s.get("duration_seconds"):
        parts.append(s["description"])
    return "  /  ".join(parts) if parts else "—"


def _summarize_steps(steps: list) -> str:
    parts = []
    for s in steps:
        t = s.get("type", "")
        if t == "warmup":
            d = s.get("distance_meters", "")
            parts.append(f'Risc. {int(d)}m' if d else "Risc.")
        elif t == "cooldown":
            d = s.get("distance_meters", "")
            parts.append(f'Defat. {int(d)}m' if d else "Defat.")
        elif t == "repeat":
            count = s.get("repeat_count", "")
            sub = s.get("repeat_steps", [{}])
            sub_d = sub[0].get("distance_meters", "") if sub else ""
            parts.append(f'{count}x{int(sub_d)}m' if sub_d else f'{count} rip.')
        elif t == "main":
            d = s.get("distance_meters", "")
            parts.append(f'{int(d)}m' if d else "Main")
    return "  —  ".join(parts) if parts else "—"


def render_activity_table(activities: list):
    """Tabella attività stile TP."""
    rows = ""
    for att in activities:
        sport = att.get("sport", "")
        badge = sport_badge(sport)
        rows += f"""
        <tr>
            <td>{att.get('data','')}</td>
            <td>{badge}</td>
            <td style="font-weight:500;">{att.get('nome','')}</td>
            <td>{att.get('distanza_km','—')} km</td>
            <td>{att.get('durata_str','—')}</td>
            <td>{att.get('pace','—')}</td>
            <td>{str(att.get('fc_media','—')) + ' bpm' if att.get('fc_media') else '—'}</td>
            <td>{str(att.get('calorie','—')) if att.get('calorie') else '—'}</td>
        </tr>"""

    st.markdown(f"""
    <table class="tp-table">
      <thead>
        <tr>
          <th>Data</th><th>Sport</th><th>Attività</th>
          <th>Distanza</th><th>Durata</th><th>Pace</th><th>FC media</th><th>Calorie</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="tp-header">
    <div class="tp-title">Coach AI-agent</div>
    <div class="tp-subtitle">Powered by Garmin Connect + Claude</div>
</div>
""", unsafe_allow_html=True)

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div class="tp-card" style="text-align:center;padding:32px;">
            <div style="font-size:15px;font-weight:600;color:#1a1a2e;margin-bottom:6px;">
                Benvenuto, Alessandro
            </div>
            <div style="font-size:13px;color:#6b7280;margin-bottom:24px;">
                Connetti il tuo account Garmin per iniziare
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Connetti Garmin Connect", use_container_width=True, type="primary"):
            with st.spinner("Connessione in corso..."):
                try:
                    r = requests.post(f"{API}/login", timeout=120)
                    data = r.json()
                    if data.get("status") in ("success", "already_logged_in"):
                        st.session_state.logged_in = True
                        st.rerun()
                    else:
                        st.error(str(data))
                except Exception as e:
                    st.error(str(e))
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="sidebar-label">Sistema</div>', unsafe_allow_html=True)

    try:
        r = requests.get(f"{API}/status", timeout=10)
        s = r.json()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
            <div class="sidebar-stat">{s.get('total_activities','—')}</div>
            <div class="sidebar-stat-label">Attività</div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="sidebar-stat" style="color:#16a34a;font-size:14px;">Online</div>
            <div class="sidebar-stat-label">{s.get('last_sync','')[:10]}</div>
            """, unsafe_allow_html=True)
    except:
        st.markdown('<div style="color:#dc2626;font-size:12px;">Backend non raggiungibile</div>',
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("Sincronizza Garmin", use_container_width=True):
        with st.spinner("Sincronizzando..."):
            try:
                r = requests.get(f"{API}/sync", timeout=120)
                st.success(f"{r.json().get('total_activities')} attività aggiornate")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Navigazione</div>', unsafe_allow_html=True)

    page = st.radio(
        "",
        ["Chat", "Attivita", "Calendario", "Statistiche"],
        label_visibility="collapsed",
        format_func=lambda x: {
            "Chat": "Chat con il Coach",
            "Attivita": "Attivita",
            "Calendario": "Calendario",
            "Statistiche": "Statistiche",
        }[x]
    )

    if page == "Chat":
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-label">Comandi rapidi</div>', unsafe_allow_html=True)
        st.markdown("""
<div style="font-size:12px;color:#374151;line-height:1.8;">
<b>Analisi</b><br>
Analizza la mia ultima corsa<br>
Dati lap del mio ultimo nuoto<br>
<br>
<b>Workout</b><br>
Crea ripetute di corsa per domani<br>
Crea sessione nuoto giovedi<br>
<br>
<b>Piano</b><br>
Crea un piano per questa settimana<br>
Pianifica 5 allenamenti in 7 giorni
</div>
        """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI CORE (invariate)
# ─────────────────────────────────────────────────────────────────────────────

def send_message(message: str):
    st.session_state.chat_history.append({"role": "user", "content": message})
    with st.spinner("Elaborando..."):
        try:
            r = requests.post(
                f"{API}/chat",
                json={"message": message,
                      "conversation_id": st.session_state.conversation_id},
                timeout=90,
            )
            data = r.json()
            reply = data.get("message", "Errore")
            action = data.get("action", "chat")

            if action == "workout_preview":
                st.session_state.pending_workout = data.get("pending_workout")
                st.session_state.pending_plan = None
            elif action == "plan_preview":
                st.session_state.pending_plan = data.get("pending_plan")
                st.session_state.pending_workout = None
            elif action in ("workout_uploaded", "plan_uploaded", "cancelled"):
                st.session_state.pending_workout = None
                st.session_state.pending_plan = None

            st.session_state.chat_history.append(
                {"role": "coach", "content": reply, "action": action}
            )
        except Exception as e:
            st.session_state.chat_history.append(
                {"role": "coach", "content": f"Errore: {e}", "action": "error"}
            )


def confirm_action(action_type: str):
    with st.spinner("Elaborando..."):
        try:
            r = requests.post(
                f"{API}/chat",
                json={"message": action_type,
                      "conversation_id": st.session_state.conversation_id},
                timeout=90,
            )
            data = r.json()
            reply = data.get("message", "")
            action = data.get("action", "")

            if action == "plan_uploading":
                plan = data.get("pending_plan", [])
                conv_id = data.get("conversation_id", "default")
                _upload_plan_one_by_one(plan, conv_id)
            elif action in ("workout_uploaded", "cancelled"):
                st.session_state.pending_workout = None
                st.session_state.pending_plan = None
                st.session_state.chat_history.append(
                    {"role": "coach", "content": reply, "action": action}
                )
            else:
                st.session_state.chat_history.append(
                    {"role": "coach", "content": reply, "action": action}
                )
        except Exception as e:
            st.error(str(e))


def _upload_plan_one_by_one(plan: list, conv_id: str):
    total = len(plan)
    uploaded = []
    failed = []

    progress_bar = st.progress(0)
    status_area = st.empty()

    for idx in range(total):
        wo = plan[idx]
        status_area.markdown(
            f'<div style="font-size:13px;color:#374151;">Caricamento {idx+1}/{total}: '
            f'<b>{wo["name"]}</b> — {wo["scheduled_date"]}</div>',
            unsafe_allow_html=True
        )
        try:
            r = requests.post(
                f"{API}/plan/upload-one",
                json={"workout_index": idx, "conversation_id": conv_id},
                timeout=30,
            )
            result = r.json()
            if result.get("status") == "success":
                uploaded.append(result.get("uploaded", {}))
                progress_bar.progress((idx + 1) / total)
            else:
                failed.append({"name": wo["name"], "error": result.get("error", "Errore")})
        except Exception as e:
            failed.append({"name": wo["name"], "error": str(e)})

    progress_bar.empty()
    status_area.empty()

    lines = [f"Piano caricato: {len(uploaded)}/{total} allenamenti su Garmin\n"]
    for u in uploaded:
        lines.append(f"  {u.get('name','')} — {u.get('date','')}")
    if failed:
        lines.append(f"\nErrori ({len(failed)}):")
        for f in failed:
            lines.append(f"  {f['name']}: {f['error']}")

    st.session_state.pending_plan = None
    st.session_state.pending_workout = None
    st.session_state.chat_history.append({
        "role": "coach", "content": "\n".join(lines), "action": "plan_uploaded"
    })

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CHAT
# ─────────────────────────────────────────────────────────────────────────────

if page == "Chat":

    # ── Workout pendente ──────────────────────────────────────────────────────
    if st.session_state.pending_workout:
        wo = st.session_state.pending_workout
        sport_label = SPORT_LABEL.get(wo.get("sport",""), wo.get("sport",""))
        st.markdown(f"""
        <div class="tp-pending">
            <div class="tp-pending-title">Workout pronto per il caricamento</div>
            <div class="tp-pending-sub">
                {wo.get('name','')} &nbsp;·&nbsp; {sport_label} &nbsp;·&nbsp; {wo.get('scheduled_date','')}
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_workout_detail(wo)
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Carica su Garmin", type="primary",
                         use_container_width=True, key="confirm_wo"):
                confirm_action("confermo")
                st.rerun()
        with c2:
            if st.button("Annulla", use_container_width=True, key="cancel_wo"):
                confirm_action("annulla")
                st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Piano pendente ────────────────────────────────────────────────────────
    if st.session_state.pending_plan:
        plan = st.session_state.pending_plan
        st.markdown(f"""
        <div class="tp-pending">
            <div class="tp-pending-title">Piano allenamento pronto per il caricamento</div>
            <div class="tp-pending-sub">{len(plan)} allenamenti pianificati</div>
        </div>
        """, unsafe_allow_html=True)
        render_workout_table(plan)
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            if st.button("Carica tutto su Garmin", type="primary",
                         use_container_width=True, key="confirm_plan"):
                confirm_action("carica tutto")
                st.rerun()
        with c2:
            if st.button("Vedi dettagli", use_container_width=True, key="details_plan"):
                send_message("dettagli")
                st.rerun()
        with c3:
            if st.button("Annulla", use_container_width=True, key="cancel_plan"):
                confirm_action("annulla")
                st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Quick actions ─────────────────────────────────────────────────────────
    if not st.session_state.pending_workout and not st.session_state.pending_plan:
        with st.expander("Azioni rapide", expanded=False):
            tab1, tab2, tab3 = st.tabs(["Analisi", "Workout", "Piani"])
            with tab1:
                c1, c2 = st.columns(2)
                for i, q in enumerate([
                    "Analizza la mia ultima corsa",
                    "Analizza il mio ultimo nuoto",
                    "Dati lap e cadenza ultima corsa",
                    "Come stanno le mie performance?",
                    "Sono in sovrallenamento?",
                    "Confronta le mie ultime corse",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qa_{i}", use_container_width=True):
                            send_message(q); st.rerun()

            with tab2:
                c1, c2 = st.columns(2)
                for i, q in enumerate([
                    "Crea ripetute di corsa per domani",
                    "Crea sessione nuoto per dopodomani",
                    "Crea allenamento bici per giovedi",
                    "Crea sessione palestra per oggi",
                    "Crea un lungo di corsa per domenica",
                    "Crea interval training nuoto",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qw_{i}", use_container_width=True):
                            send_message(q); st.rerun()

            with tab3:
                c1, c2 = st.columns(2)
                for i, q in enumerate([
                    "Crea un piano per questa settimana",
                    "Pianifica 5 allenamenti in 7 giorni",
                    "Piano triathlon per 2 settimane",
                    "Piano intenso: nuoto, corsa e palestra",
                    "Piano di recupero questa settimana",
                    "Piano con focus nuoto per 10 giorni",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qp_{i}", use_container_width=True):
                            send_message(q); st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Storico chat ──────────────────────────────────────────────────────────
    for idx, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            st.markdown(
                f'<div class="chat-user">{msg["content"]}</div>',
                unsafe_allow_html=True
            )
        else:
            action = msg.get("action", "chat")
            content = msg["content"]

            # Per workout preview mostra la tabella invece del testo markdown
            is_last = (idx == len(st.session_state.chat_history) - 1)

            if action == "plan_details" and st.session_state.pending_plan:
                # Mostra il contenuto testo + bottoni
                st.markdown(
                    f'<div class="chat-coach">{content}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="chat-coach">{content}</div>',
                    unsafe_allow_html=True
                )

            # Bottoni inline solo sull'ultimo messaggio pendente
            if is_last and action == "workout_preview" and st.session_state.pending_workout:
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("Carica su Garmin", type="primary",
                                 use_container_width=True, key=f"ci_wo_{idx}"):
                        confirm_action("confermo"); st.rerun()
                with c2:
                    if st.button("Annulla", use_container_width=True, key=f"cx_wo_{idx}"):
                        confirm_action("annulla"); st.rerun()

            if is_last and action == "plan_preview" and st.session_state.pending_plan:
                render_workout_table(st.session_state.pending_plan)
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    if st.button("Carica tutto su Garmin", type="primary",
                                 use_container_width=True, key=f"ci_pl_{idx}"):
                        confirm_action("carica tutto"); st.rerun()
                with c2:
                    if st.button("Vedi dettagli", use_container_width=True, key=f"cd_pl_{idx}"):
                        send_message("dettagli"); st.rerun()
                with c3:
                    if st.button("Annulla", use_container_width=True, key=f"cx_pl_{idx}"):
                        confirm_action("annulla"); st.rerun()

    # ── Input ─────────────────────────────────────────────────────────────────
    if st.session_state.pending_workout or st.session_state.pending_plan:
        st.markdown(
            '<div style="font-size:12px;color:#6b7280;margin-top:8px;">'
            'Usa i pulsanti sopra per confermare o annullare prima di continuare.</div>',
            unsafe_allow_html=True
        )
    else:
        user_input = st.chat_input("Scrivi al coach...")
        if user_input:
            send_message(user_input)
            st.rerun()

    if st.session_state.chat_history:
        if st.button("Pulisci conversazione", key="clear_chat"):
            st.session_state.chat_history = []
            st.session_state.pending_workout = None
            st.session_state.pending_plan = None
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: ATTIVITA
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Attivita":
    st.markdown('<div style="font-size:18px;font-weight:700;color:#1a1a2e;margin-bottom:16px;">Attivita</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([3, 1])
    with c1:
        sport_filter = st.selectbox(
            "Sport",
            ["Tutti", "running", "swimming", "cycling", "strength_training"],
            format_func=lambda x: "Tutti gli sport" if x == "Tutti" else SPORT_LABEL.get(x, x),
            label_visibility="collapsed",
        )
    with c2:
        limit = st.selectbox("Numero", [20, 50, 100], label_visibility="collapsed")

    try:
        params = {"limit": limit}
        if sport_filter != "Tutti":
            params["sport"] = sport_filter
        r = requests.get(f"{API}/activities", params=params, timeout=30)
        activities = r.json().get("activities", [])
    except Exception as e:
        st.error(str(e))
        activities = []

    if activities:
        st.markdown(
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:12px;">'
            f'{len(activities)} attività trovate</div>',
            unsafe_allow_html=True
        )
        render_activity_table(activities)
        st.markdown("<br>", unsafe_allow_html=True)

        # Analisi singola attività
        st.markdown('<div style="font-size:14px;font-weight:600;margin-bottom:8px;">Analizza un\'attivita</div>', unsafe_allow_html=True)
        options = {f"{a['data']} — {a['nome']} ({a['distanza_km']}km)": a for a in activities}
        selected = st.selectbox("Seleziona attivita", list(options.keys()), label_visibility="collapsed")
        if st.button("Analizza con il Coach", type="primary"):
            att = options[selected]
            q = (f"Analizza nel dettaglio questa attivita: {att['sport']} del {att['data']}, "
                 f"nome: {att['nome']}, {att['distanza_km']}km in {att['durata_str']}, "
                 f"FC {att['fc_media']}bpm, pace {att['pace']}. "
                 f"Voglio vedere pace km per km, HR, elevazione, cadenza e performance condition.")
            send_message(q)
            st.success("Analisi avviata. Vai alla sezione Chat per vedere i risultati.")
    else:
        st.info("Nessuna attivita trovata.")

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CALENDARIO
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Calendario":
    st.markdown('<div style="font-size:18px;font-weight:700;color:#1a1a2e;margin-bottom:16px;">Calendario</div>', unsafe_allow_html=True)

    today = date.today()
    c1, c2 = st.columns(2)
    with c1:
        sel_month = st.selectbox(
            "Mese", range(1, 13), index=today.month - 1,
            format_func=lambda m: cal_module.month_name[m],
            label_visibility="collapsed"
        )
    with c2:
        sel_year = st.selectbox(
            "Anno", [today.year - 1, today.year, today.year + 1],
            index=1, label_visibility="collapsed"
        )

    try:
        r = requests.get(f"{API}/calendar",
                         params={"year": sel_year, "month": sel_month}, timeout=30)
        items = r.json().get("items", [])
    except Exception as e:
        st.error(str(e))
        items = []

    # Griglia calendario
    items_by_date = {}
    for item in items:
        d = item.get("data", "")
        items_by_date.setdefault(d, []).append(item)

    day_headers = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
    header_cols = st.columns(7)
    for i, d in enumerate(day_headers):
        header_cols[i].markdown(
            f'<div style="font-size:11px;font-weight:700;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.5px;padding:4px 0;">{d}</div>',
            unsafe_allow_html=True
        )

    for week in cal_module.monthcalendar(sel_year, sel_month):
        day_cols = st.columns(7)
        for i, day_num in enumerate(week):
            with day_cols[i]:
                if day_num == 0:
                    continue
                date_str = f"{sel_year}-{sel_month:02d}-{day_num:02d}"
                is_today = (date_str == today.isoformat())
                day_color = "#0284c7" if is_today else "#1a1a2e"
                st.markdown(
                    f'<div style="font-size:13px;font-weight:{"700" if is_today else "500"};'
                    f'color:{day_color};padding:2px 0;">{day_num}</div>',
                    unsafe_allow_html=True
                )
                for item in items_by_date.get(date_str, []):
                    sport = item.get("sport", "")
                    label = SPORT_LABEL.get(sport, sport)
                    title = item.get("titolo", "")[:16]
                    tipo = item.get("tipo", "")
                    bg = "#dbeafe" if tipo == "workout" else "#f0fdf4"
                    color = "#1e40af" if tipo == "workout" else "#166534"
                    st.markdown(
                        f'<div style="background:{bg};color:{color};font-size:10px;'
                        f'font-weight:600;padding:2px 5px;border-radius:3px;margin:1px 0;">'
                        f'{title}</div>',
                        unsafe_allow_html=True
                    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Lista tabellare
    planned = [i for i in items if i.get("tipo") == "workout"]
    completed = [i for i in items if i.get("tipo") == "activity"]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div style="font-size:13px;font-weight:600;margin-bottom:8px;">Pianificati</div>', unsafe_allow_html=True)
        if planned:
            rows = ""
            for wo in sorted(planned, key=lambda x: x["data"]):
                badge = sport_badge(wo.get("sport",""))
                rows += f"<tr><td>{wo['data']}</td><td>{badge}</td><td>{wo.get('titolo','')}</td></tr>"
            st.markdown(f'<table class="tp-table"><thead><tr><th>Data</th><th>Sport</th><th>Nome</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:12px;color:#6b7280;">Nessun workout pianificato</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div style="font-size:13px;font-weight:600;margin-bottom:8px;">Completati</div>', unsafe_allow_html=True)
        if completed:
            rows = ""
            for att in sorted(completed, key=lambda x: x["data"]):
                dist = att.get("distanza_m", 0)
                dist_str = f"{dist/1000:.1f} km" if dist else "—"
                fc = att.get("fc_media", "")
                fc_str = f"{fc} bpm" if fc else "—"
                rows += f"<tr><td>{att['data']}</td><td>{att.get('titolo','')}</td><td>{dist_str}</td><td>{fc_str}</td></tr>"
            st.markdown(f'<table class="tp-table"><thead><tr><th>Data</th><th>Attivita</th><th>Distanza</th><th>FC media</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:12px;color:#6b7280;">Nessuna attivita completata</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: STATISTICHE
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Statistiche":
    st.markdown('<div style="font-size:18px;font-weight:700;color:#1a1a2e;margin-bottom:16px;">Statistiche</div>', unsafe_allow_html=True)

    try:
        r = requests.get(f"{API}/activities", params={"limit": 500}, timeout=30)
        all_activities = r.json().get("activities", [])
    except:
        all_activities = []

    if not all_activities:
        st.info("Nessun dato disponibile.")
    else:
        sport_stats = {}
        for att in all_activities:
            sport = att["sport"]
            if sport not in sport_stats:
                sport_stats[sport] = {
                    "count": 0, "total_km": 0.0, "total_min": 0.0, "fc_values": []
                }
            sport_stats[sport]["count"] += 1
            sport_stats[sport]["total_km"] += att.get("distanza_km", 0) or 0
            sport_stats[sport]["total_min"] += att.get("durata_min", 0) or 0
            if att.get("fc_media"):
                sport_stats[sport]["fc_values"].append(att["fc_media"])

        # Cards statistiche
        cols = st.columns(len(sport_stats))
        for i, (sport, s) in enumerate(sorted(sport_stats.items())):
            with cols[i]:
                badge = sport_badge(sport)
                h, m = divmod(int(s["total_min"]), 60)
                fc_avg = round(sum(s["fc_values"])/len(s["fc_values"])) if s["fc_values"] else None
                st.markdown(f"""
                <div class="tp-card">
                    <div style="margin-bottom:10px;">{badge}</div>
                    <div class="sidebar-stat">{s["count"]}</div>
                    <div class="sidebar-stat-label" style="margin-bottom:8px;">sessioni</div>
                    <div style="font-size:13px;color:#374151;line-height:1.8;">
                        {s["total_km"]:.1f} km totali<br>
                        {h}h {m}min totali
                        {"<br>" + str(fc_avg) + " bpm FC media" if fc_avg else ""}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div style="font-size:14px;font-weight:600;margin-bottom:12px;">Cronologia recente</div>', unsafe_allow_html=True)
        render_activity_table(all_activities[:50])
