"""
app.py - v7
Coach AI-agent
- Tema scuro coerente ovunque
- Full width mobile
- Niente emoji nei messaggi coach
- Palestra come sport completo con esercizi
- Titoli compatti nell'analisi
"""

import streamlit as st
import requests
from datetime import date
import calendar as cal_module

API = "https://ai-coach-backend-xc9s.onrender.com"

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG + DARK THEME CSS
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Coach AI-agent",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Reset e font ── */
html, body, [class*="css"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ── Sfondo scuro globale ── */
.stApp {
    background-color: #0f1117 !important;
}
.stApp > header {
    background-color: #0f1117 !important;
}

/* ── Main content area ── */
.block-container {
    padding: 16px 16px 32px 16px !important;
    max-width: 100% !important;
}

/* ── Sidebar scura ── */
[data-testid="stSidebar"] {
    background-color: #161b22 !important;
    border-right: 1px solid #21262d !important;
}
[data-testid="stSidebar"] * {
    color: #c9d1d9 !important;
}
[data-testid="stSidebar"] .stRadio label {
    font-size: 13px !important;
    color: #c9d1d9 !important;
}

/* ── Header app ── */
.app-header {
    padding: 12px 0 16px 0;
    border-bottom: 1px solid #21262d;
    margin-bottom: 20px;
}
.app-title {
    font-size: 18px;
    font-weight: 700;
    color: #f0f6fc;
    letter-spacing: -0.2px;
    margin: 0;
}
.app-sub {
    font-size: 11px;
    color: #8b949e;
    margin-top: 2px;
}

/* ── Card ── */
.tp-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 12px;
}
.tp-card-label {
    font-size: 10px;
    font-weight: 600;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
}

/* ── Pending alert ── */
.tp-pending {
    background: #0d1117;
    border: 1px solid #1f6feb;
    border-left: 3px solid #1f6feb;
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 14px;
}
.tp-pending-title {
    font-size: 12px;
    font-weight: 600;
    color: #58a6ff;
    margin-bottom: 3px;
}
.tp-pending-sub {
    font-size: 12px;
    color: #8b949e;
}

/* ── Tabelle ── */
.tp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin-top: 6px;
}
.tp-table th {
    background: #21262d;
    color: #8b949e;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 7px 10px;
    text-align: left;
    border-bottom: 1px solid #30363d;
    white-space: nowrap;
}
.tp-table td {
    padding: 9px 10px;
    border-bottom: 1px solid #21262d;
    color: #c9d1d9;
    vertical-align: top;
    word-break: break-word;
}
.tp-table tr:last-child td { border-bottom: none; }
.tp-table tr:hover td { background: #161b22; }

/* ── Badge sport ── */
.badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
    white-space: nowrap;
}
.badge-run  { background: #3d2c00; color: #f0a500; }
.badge-swim { background: #0c2a4a; color: #58a6ff; }
.badge-bike { background: #0d2e1e; color: #3fb950; }
.badge-gym  { background: #2d1f47; color: #bc8cff; }
.badge-other{ background: #21262d; color: #8b949e; }

/* ── Chat bubbles ── */
.chat-user {
    background: #1f6feb;
    color: #ffffff;
    padding: 10px 13px;
    border-radius: 12px 12px 3px 12px;
    margin: 8px 0 8px 15%;
    font-size: 13px;
    line-height: 1.5;
    word-break: break-word;
}
.chat-coach {
    background: #161b22;
    border: 1px solid #21262d;
    color: #c9d1d9;
    padding: 12px 14px;
    border-radius: 3px 12px 12px 12px;
    margin: 8px 15% 8px 0;
    font-size: 13px;
    line-height: 1.65;
    word-break: break-word;
}
/* Mobile: chat full width */
@media (max-width: 768px) {
    .chat-user  { margin-left: 5% !important; }
    .chat-coach { margin-right: 5% !important; }
    .block-container { padding: 8px 8px 24px 8px !important; }
}

/* ── Sidebar stat ── */
.s-stat { font-size: 22px; font-weight: 700; color: #f0f6fc; line-height: 1; }
.s-label { font-size: 10px; color: #8b949e; margin-top: 2px; }
.s-section {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #6e7681;
    margin: 14px 0 6px 0;
}

/* ── Testi generali nella dark area ── */
p, span, div, label, h1, h2, h3, h4, h5, h6 {
    color: #c9d1d9;
}

/* ── Input chat ── */
[data-testid="stChatInput"] {
    background-color: #161b22 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px !important;
}
[data-testid="stChatInput"] textarea {
    color: #c9d1d9 !important;
    background: transparent !important;
}

/* ── Pulsanti ── */
div[data-testid="stButton"] > button {
    font-family: 'Inter', sans-serif !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    border-radius: 4px !important;
    border: 1px solid #30363d !important;
    background: #21262d !important;
    color: #c9d1d9 !important;
    letter-spacing: 0.2px !important;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: #1f6feb !important;
    border-color: #1f6feb !important;
    color: #ffffff !important;
}
div[data-testid="stButton"] > button:hover {
    border-color: #58a6ff !important;
    color: #f0f6fc !important;
}

/* ── Select, input ── */
[data-baseweb="select"] {
    background-color: #21262d !important;
}
[data-baseweb="select"] * {
    background-color: #21262d !important;
    color: #c9d1d9 !important;
    border-color: #30363d !important;
}

/* ── Progress bar ── */
[data-testid="stProgressBar"] > div {
    background-color: #1f6feb !important;
}

/* ── Divider ── */
hr { border-color: #21262d !important; }

/* ── Nasconde elementi Streamlit ── */
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #161b22 !important;
    border: 1px solid #21262d !important;
    border-radius: 6px !important;
}
[data-testid="stExpander"] summary {
    color: #c9d1d9 !important;
    font-size: 13px !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# COSTANTI
# ─────────────────────────────────────────────────────────────────────────────

SPORT_LABEL = {
    "running": "Corsa",
    "swimming": "Nuoto",
    "cycling": "Ciclismo",
    "strength_training": "Palestra",
    "other": "Altro",
}
SPORT_BADGE_CLASS = {
    "running": "badge-run",
    "swimming": "badge-swim",
    "cycling": "badge-bike",
    "strength_training": "badge-gym",
    "other": "badge-other",
}

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

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS GRAFICI
# ─────────────────────────────────────────────────────────────────────────────

def sport_badge(sport: str) -> str:
    label = SPORT_LABEL.get(sport, sport)
    css   = SPORT_BADGE_CLASS.get(sport, "badge-other")
    return f'<span class="badge {css}">{label}</span>'


def clean_message(text: str) -> str:
    """Rimuove emoji, converte markdown in HTML per la visualizzazione nella chat."""
    import re

    # 1. Rimuovi emoji decorative
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub("", text)

    # 2. Rimuovi righe vuote eccessive (max 1 riga vuota consecutiva)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # 3. Converti markdown → HTML

    # Grassetto **testo** → <strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Corsivo *testo* → <em>  (solo singolo asterisco rimasto)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    # Titoli ### → testo più grande (non H tag enormi)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<span style="font-weight:600;color:#f0f6fc;">\1</span>', text, flags=re.MULTILINE)

    # Liste con - o • → righe con un punto
    text = re.sub(r'^[-•]\s+(.+)$', r'&nbsp;&nbsp;— \1', text, flags=re.MULTILINE)

    # Newline → <br>
    text = text.replace('\n', '<br>')

    # Rimuovi <br> doppi eccessivi
    text = re.sub(r'(<br>){3,}', '<br><br>', text)

    return text


def render_workout_table(workouts: list):
    """Tabella compatta del piano allenamenti."""
    rows = ""
    for i, wo in enumerate(workouts, 1):
        badge = sport_badge(wo.get("sport", ""))
        summary = _summarize_steps(wo.get("steps", []))
        rows += f"""<tr>
            <td style="color:#8b949e;font-size:11px;">{i}</td>
            <td style="white-space:nowrap;">{wo.get('scheduled_date','')}</td>
            <td>{badge}</td>
            <td style="font-weight:500;color:#f0f6fc;">{wo.get('name','')}</td>
            <td style="color:#8b949e;font-size:11px;">{summary}</td>
        </tr>"""
    st.markdown(f"""
    <table class="tp-table">
      <thead><tr><th>#</th><th>Data</th><th>Sport</th><th>Nome</th><th>Struttura</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)


def render_workout_detail(wo: dict):
    """Dettaglio steps di un workout in card scura."""
    badge = sport_badge(wo.get("sport", ""))
    steps = wo.get("steps", [])

    step_rows = "".join(_render_step_row(s) for s in steps)

    st.markdown(f"""
    <div class="tp-card">
        <div style="font-size:15px;font-weight:700;color:#f0f6fc;margin-bottom:6px;">
            {wo.get('name','')}
        </div>
        <div style="margin-bottom:12px;font-size:12px;color:#8b949e;">
            {badge}&nbsp;&nbsp;{wo.get('scheduled_date','')}
        </div>
        <table class="tp-table">
          <thead><tr><th>Tipo</th><th>Dettaglio</th></tr></thead>
          <tbody>{step_rows}</tbody>
        </table>
        {"<div style='font-size:11px;color:#8b949e;margin-top:8px;'>"+wo['description']+"</div>" if wo.get('description') else ""}
    </div>
    """, unsafe_allow_html=True)


def _render_step_row(s: dict) -> str:
    t = s.get("type", "")
    labels = {
        "warmup": "Riscaldamento", "cooldown": "Defaticamento",
        "main": "Principale", "rest": "Recupero", "repeat": "Ripetizioni",
        "exercise": "Esercizio",
    }
    label = labels.get(t, t.upper())

    if t == "repeat":
        count = s.get("repeat_count", 1)
        sub_html = ""
        for sub in s.get("repeat_steps", []):
            sub_label = labels.get(sub.get("type",""), sub.get("type",""))
            sub_detail = _format_step_detail(sub)
            sub_desc = f" — {sub['description']}" if sub.get("description") else ""
            sub_html += (
                f'<div style="display:flex;gap:10px;padding:3px 0;font-size:11px;">'
                f'<span style="width:90px;color:#6e7681;">{sub_label}</span>'
                f'<span style="color:#c9d1d9;">{sub_detail}{sub_desc}</span></div>'
            )
        detail = (
            f'<span style="font-weight:600;color:#f0f6fc;">{count}x</span>'
            f'<div style="margin-top:4px;padding-left:8px;border-left:2px solid #30363d;">'
            f'{sub_html}</div>'
        )
    else:
        detail_str = _format_step_detail(s)
        desc = f' <span style="color:#6e7681;font-size:11px;">— {s["description"]}</span>' if s.get("description") else ""
        detail = f'{detail_str}{desc}'

    return f'<tr><td style="font-weight:600;color:#8b949e;font-size:11px;white-space:nowrap;">{label}</td><td>{detail}</td></tr>'


def _format_step_detail(s: dict) -> str:
    parts = []
    if s.get("distance_meters"):
        d = s["distance_meters"]
        parts.append(f"{int(d)}m" if d < 1000 else f"{d/1000:.1f}km")
    if s.get("duration_seconds"):
        sec = int(s["duration_seconds"])
        m, sc = divmod(sec, 60)
        parts.append(f"{m}:{sc:02d} min" if m > 0 else f"{sc}s")
    if s.get("reps"):
        parts.append(f"{s['reps']} rip.")
    if s.get("sets"):
        parts.append(f"{s['sets']} serie")
    if s.get("weight_kg"):
        parts.append(f"{s['weight_kg']}kg")
    if not parts and s.get("description"):
        parts.append(s["description"])
    return "  /  ".join(parts) if parts else "—"


def _summarize_steps(steps: list) -> str:
    parts = []
    for s in steps:
        t = s.get("type", "")
        if t == "warmup":
            d = s.get("distance_meters", "")
            parts.append(f"Risc.{int(d)}m" if d else "Risc.")
        elif t == "cooldown":
            d = s.get("distance_meters", "")
            parts.append(f"Defat.{int(d)}m" if d else "Defat.")
        elif t == "repeat":
            count = s.get("repeat_count", "")
            sub = s.get("repeat_steps", [{}])
            sub_d = sub[0].get("distance_meters", "") if sub else ""
            sub_r = sub[0].get("reps", "") if sub else ""
            if sub_d:
                parts.append(f"{count}x{int(sub_d)}m")
            elif sub_r:
                parts.append(f"{count}x{sub_r}rip")
            else:
                parts.append(f"{count} rip.")
        elif t == "main":
            d = s.get("distance_meters", "")
            parts.append(f"{int(d)}m" if d else "Main")
        elif t == "exercise":
            parts.append(s.get("description", "Esercizio")[:20])
    return " — ".join(parts) if parts else "—"


def render_activity_table(activities: list):
    rows = ""
    for att in activities:
        badge = sport_badge(att.get("sport", ""))
        # Indicatore allenamento strutturato (con target)
        struct = ""
        if att.get("is_structured"):
            struct = ('<span style="display:inline-block;margin-left:6px;padding:1px 5px;'
                      'border-radius:3px;font-size:9px;font-weight:600;background:#1f3a5f;'
                      'color:#79c0ff;">TARGET</span>')
        rows += f"""<tr>
            <td style="white-space:nowrap;color:#8b949e;">{att.get('data','')}</td>
            <td>{badge}</td>
            <td style="font-weight:500;color:#f0f6fc;">{att.get('nome','')}{struct}</td>
            <td style="white-space:nowrap;">{att.get('distanza_km','—')} km</td>
            <td style="white-space:nowrap;">{att.get('durata_str','—')}</td>
            <td style="white-space:nowrap;">{att.get('pace','—')}</td>
            <td style="white-space:nowrap;">{str(att.get('fc_media','—'))+" bpm" if att.get('fc_media') else '—'}</td>
        </tr>"""
    st.markdown(f"""
    <table class="tp-table">
      <thead><tr>
        <th>Data</th><th>Sport</th><th>Attivita</th>
        <th>Dist.</th><th>Durata</th><th>Pace</th><th>FC media</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
    <div class="app-title">Coach AI-agent</div>
    <div class="app-sub">Garmin Connect + Claude AI</div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div class="tp-card" style="text-align:center;padding:28px 20px;">
            <div style="font-size:14px;font-weight:600;color:#f0f6fc;margin-bottom:4px;">
                Benvenuto, Alessandro
            </div>
            <div style="font-size:12px;color:#8b949e;margin-bottom:20px;">
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
    st.markdown('<div class="s-section">Sistema</div>', unsafe_allow_html=True)
    try:
        r = requests.get(f"{API}/status", timeout=10)
        s = r.json()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="s-stat">{s.get("total_activities","—")}</div>'
                        f'<div class="s-label">Attivita</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="s-stat" style="color:#3fb950;font-size:13px;">Online</div>'
                        f'<div class="s-label">{s.get("last_sync","")[:10]}</div>', unsafe_allow_html=True)
    except:
        st.markdown('<div style="color:#f85149;font-size:12px;">Backend non raggiungibile</div>',
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sincronizza Garmin", use_container_width=True):
        with st.spinner("Sincronizzando..."):
            try:
                r = requests.get(f"{API}/sync", timeout=120)
                st.success(f"{r.json().get('total_activities')} attivita aggiornate")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown('<div class="s-section">Navigazione</div>', unsafe_allow_html=True)
    page = st.radio(
        "", ["Chat", "Attivita", "Calendario", "Statistiche"],
        label_visibility="collapsed",
        format_func=lambda x: {
            "Chat": "Chat con il Coach",
            "Attivita": "Attivita",
            "Calendario": "Calendario",
            "Statistiche": "Statistiche",
        }[x]
    )

    if page == "Chat":
        st.markdown('<div class="s-section">Esempi di richieste</div>', unsafe_allow_html=True)
        st.markdown("""
<div style="font-size:11px;color:#8b949e;line-height:2.0;">
Analisi<br>
— Analizza la mia ultima corsa<br>
— Dati lap e cadenza ultimo nuoto<br>
<br>
Workout singolo<br>
— Crea ripetute di corsa per domani<br>
— Crea sessione nuoto giovedi<br>
— Crea sessione palestra gambe<br>
<br>
Piano<br>
— Crea un piano per questa settimana<br>
— Piano triathlon per 2 settimane<br>
— Piano palestra + corsa 5 giorni
</div>
        """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI CORE
# ─────────────────────────────────────────────────────────────────────────────

def send_message(message: str):
    st.session_state.chat_history.append({"role": "user", "content": message})
    with st.spinner("Elaborando..."):
        try:
            payload = {
                "message": message,
                "conversation_id": st.session_state.conversation_id,
                "pending_workout": st.session_state.pending_workout,
                "pending_plan": st.session_state.pending_plan,
            }
            r = requests.post(f"{API}/chat", json=payload, timeout=90)
            data = r.json()
            reply = data.get("message", "Errore")
            action = data.get("action", "chat")

            # Salva PRIMA lo state, poi aggiungi alla history
            if action == "workout_preview":
                st.session_state.pending_workout = data.get("pending_workout")
                st.session_state.pending_plan = None
            elif action == "plan_preview":
                # CRITICO: salva il piano nello state prima di qualsiasi rerun
                plan = data.get("pending_plan")
                if plan:
                    st.session_state.pending_plan = plan
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
    """
    Per il piano: carica direttamente uno alla volta senza passare per /chat.
    Per workout singolo e annulla: passa per /chat come prima.
    """
    if action_type == "carica_piano" and st.session_state.pending_plan:
        _upload_plan_one_by_one(
            st.session_state.pending_plan,
            st.session_state.conversation_id
        )
        return

    with st.spinner("Elaborando..."):
        try:
            payload = {
                "message": action_type,
                "conversation_id": st.session_state.conversation_id,
                "pending_workout": st.session_state.pending_workout,
                "pending_plan": st.session_state.pending_plan,
            }
            r = requests.post(f"{API}/chat", json=payload, timeout=90)
            data = r.json()
            reply = data.get("message", "")
            action = data.get("action", "")

            if action in ("workout_uploaded", "cancelled"):
                st.session_state.pending_workout = None
                st.session_state.pending_plan = None
                st.session_state.chat_history.append(
                    {"role": "coach", "content": reply, "action": action}
                )
            elif action == "plan_uploading":
                plan = data.get("pending_plan") or st.session_state.pending_plan or []
                conv_id = data.get("conversation_id", st.session_state.conversation_id)
                _upload_plan_one_by_one(plan, conv_id)
            else:
                st.session_state.chat_history.append(
                    {"role": "coach", "content": reply, "action": action}
                )
        except Exception as e:
            st.error(str(e))


def _upload_plan_one_by_one(plan: list, conv_id: str):
    """
    Carica ogni workout uno alla volta.
    Manda il workout COMPLETO nel body di ogni request —
    zero dipendenza dallo state del server, funziona sempre.
    """
    import time
    total = len(plan)
    uploaded = []
    failed = []

    SPORT_LABELS = {
        "running": "Corsa", "swimming": "Nuoto",
        "cycling": "Ciclismo", "strength_training": "Palestra",
    }

    progress_bar = st.progress(0)
    status_area = st.empty()

    for idx, wo in enumerate(plan):
        sport_label = SPORT_LABELS.get(wo.get("sport", ""), wo.get("sport", ""))

        status_area.markdown(
            f'<div style="font-size:12px;color:#8b949e;padding:4px 0;">'
            f'Caricamento {idx+1}/{total}: '
            f'<span style="color:#c9d1d9;font-weight:500;">{wo["name"]}</span>'
            f' &nbsp;·&nbsp; {sport_label} &nbsp;·&nbsp; {wo["scheduled_date"]}'
            f'</div>',
            unsafe_allow_html=True
        )

        try:
            # Manda il workout direttamente nel body — niente state in RAM
            r = requests.post(
                f"{API}/plan/upload-one",
                json={"workout": wo, "conversation_id": conv_id},
                timeout=30,
            )
            result = r.json()

            if result.get("status") == "success":
                uploaded.append({
                    "name": wo["name"],
                    "date": wo["scheduled_date"],
                    "sport": wo.get("sport", ""),
                })
                progress_bar.progress((idx + 1) / total)
                time.sleep(1.5)   # pausa tra upload — Garmin blocca richieste troppo rapide
            else:
                failed.append({
                    "name": wo["name"],
                    "error": result.get("error", "Errore sconosciuto"),
                })

        except Exception as e:
            failed.append({"name": wo["name"], "error": str(e)})

    progress_bar.empty()
    status_area.empty()

    # Messaggio finale
    if len(uploaded) == total and total > 0:
        header = f"Piano caricato su Garmin: {total}/{total} allenamenti"
    elif len(uploaded) > 0:
        header = f"Piano parzialmente caricato: {len(uploaded)}/{total} allenamenti"
    else:
        header = f"Caricamento fallito: 0/{total} allenamenti"

    lines = [header + "\n"]
    for u in uploaded:
        sl = SPORT_LABELS.get(u.get("sport", ""), "")
        lines.append(f"  {u['name']} — {u['date']}" + (f" ({sl})" if sl else ""))
    if failed:
        lines.append(f"\nErrori ({len(failed)}):")
        for f in failed:
            lines.append(f"  {f['name']}: {f['error']}")

    st.session_state.pending_plan = None
    st.session_state.pending_workout = None
    st.session_state.chat_history.append({
        "role": "coach",
        "content": "\n".join(lines),
        "action": "plan_uploaded",
    })
    st.session_state.chat_history.append({
        "role": "coach",
        "content": "\n".join(lines),
        "action": "plan_uploaded",
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
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Carica su Garmin", type="primary",
                         use_container_width=True, key="confirm_wo_top"):
                confirm_action("confermo"); st.rerun()
        with c2:
            if st.button("Annulla", use_container_width=True, key="cancel_wo_top"):
                confirm_action("annulla"); st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Piano pendente ────────────────────────────────────────────────────────
    if st.session_state.pending_plan:
        plan = st.session_state.pending_plan
        st.markdown(f"""
        <div class="tp-pending">
            <div class="tp-pending-title">Piano pronto per il caricamento</div>
            <div class="tp-pending-sub">{len(plan)} allenamenti pianificati</div>
        </div>
        """, unsafe_allow_html=True)
        render_workout_table(plan)
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            if st.button("Carica tutto su Garmin", type="primary",
                         use_container_width=True, key="confirm_plan_top"):
                confirm_action("carica_piano"); st.rerun()
        with c2:
            if st.button("Vedi dettagli", use_container_width=True, key="details_plan_top"):
                send_message("dettagli"); st.rerun()
        with c3:
            if st.button("Annulla", use_container_width=True, key="cancel_plan_top"):
                confirm_action("annulla"); st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Azioni rapide ─────────────────────────────────────────────────────────
    if not st.session_state.pending_workout and not st.session_state.pending_plan:
        with st.expander("Azioni rapide", expanded=False):
            tab1, tab2, tab3, tab4 = st.tabs(["Analisi", "Corsa/Nuoto/Bici", "Palestra", "Piani"])

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
                    "Crea un lungo di corsa per domenica",
                    "Crea interval training nuoto",
                    "Crea tempo run 8km per venerdi",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qw_{i}", use_container_width=True):
                            send_message(q); st.rerun()

            with tab3:
                c1, c2 = st.columns(2)
                for i, q in enumerate([
                    "Crea sessione palestra upper body per oggi",
                    "Crea sessione palestra gambe e core",
                    "Crea full body per triatleta domani",
                    "Crea sessione core e stabilita",
                    "Crea circuito forza funzionale",
                    "Crea sessione mobilita e stretching",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qg_{i}", use_container_width=True):
                            send_message(q); st.rerun()

            with tab4:
                c1, c2 = st.columns(2)
                for i, q in enumerate([
                    "Crea un piano per questa settimana",
                    "Pianifica 5 allenamenti in 7 giorni",
                    "Piano triathlon per 2 settimane",
                    "Piano con corsa, nuoto e palestra",
                    "Piano di recupero questa settimana",
                    "Piano con focus forza per 10 giorni",
                ]):
                    with (c1 if i % 2 == 0 else c2):
                        if st.button(q, key=f"qp_{i}", use_container_width=True):
                            send_message(q); st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Storico messaggi ──────────────────────────────────────────────────────
    for idx, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            st.markdown(
                f'<div class="chat-user">{msg["content"]}</div>',
                unsafe_allow_html=True
            )
        else:
            action = msg.get("action", "chat")
            # Rimuovi emoji decorative dal testo del coach
            content = clean_message(msg["content"])
            is_last = (idx == len(st.session_state.chat_history) - 1)

            st.markdown(
                f'<div class="chat-coach">{content}</div>',
                unsafe_allow_html=True
            )

            # Bottoni solo sull'ultimo messaggio
            if is_last and action == "workout_preview" and st.session_state.pending_workout:
                c1, c2 = st.columns(2)
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
                        confirm_action("carica_piano"); st.rerun()
                with c2:
                    if st.button("Vedi dettagli", use_container_width=True, key=f"cd_pl_{idx}"):
                        send_message("dettagli"); st.rerun()
                with c3:
                    if st.button("Annulla", use_container_width=True, key=f"cx_pl_{idx}"):
                        confirm_action("annulla"); st.rerun()

    # ── Input ─────────────────────────────────────────────────────────────────
    if st.session_state.pending_workout or st.session_state.pending_plan:
        st.markdown(
            '<div style="font-size:11px;color:#6e7681;margin-top:8px;padding:8px 0;">'
            'Usa i pulsanti sopra per confermare o annullare prima di continuare.</div>',
            unsafe_allow_html=True
        )
    else:
        user_input = st.chat_input("Scrivi al coach...")
        if user_input:
            send_message(user_input); st.rerun()

    if st.session_state.chat_history:
        if st.button("Pulisci conversazione", key="clear"):
            st.session_state.chat_history = []
            st.session_state.pending_workout = None
            st.session_state.pending_plan = None
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: ATTIVITA
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Attivita":
    st.markdown('<div style="font-size:16px;font-weight:700;color:#f0f6fc;margin-bottom:14px;">Attivita</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([3, 1])
    with c1:
        sport_filter = st.selectbox(
            "", ["Tutti", "running", "swimming", "cycling", "strength_training"],
            format_func=lambda x: "Tutti gli sport" if x == "Tutti" else SPORT_LABEL.get(x, x),
            label_visibility="collapsed",
        )
    with c2:
        limit = st.selectbox("", [20, 50, 100], label_visibility="collapsed")

    try:
        params = {"limit": limit}
        if sport_filter != "Tutti":
            params["sport"] = sport_filter
        r = requests.get(f"{API}/activities", params=params, timeout=30)
        activities = r.json().get("activities", [])
    except Exception as e:
        st.error(str(e)); activities = []

    if activities:
        st.markdown(f'<div style="font-size:11px;color:#6e7681;margin-bottom:10px;">{len(activities)} attivita</div>', unsafe_allow_html=True)
        render_activity_table(activities)
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div style="font-size:13px;font-weight:600;color:#c9d1d9;margin-bottom:8px;">Analizza un\'attivita</div>', unsafe_allow_html=True)
        options = {f"{a['data']} — {a['nome']} ({a['distanza_km']}km)"
                   + (" [TARGET]" if a.get("is_structured") else ""): a
                   for a in activities}
        selected = st.selectbox("", list(options.keys()), label_visibility="collapsed")
        if st.button("Analizza con il Coach", type="primary"):
            att = options[selected]
            if att.get("is_structured"):
                q = (f"Analizza questo allenamento strutturato: {att['sport']} del {att['data']}, "
                     f"nome: {att['nome']}, {att['distanza_km']}km in {att['durata_str']}, "
                     f"FC {att['fc_media']}bpm, pace {att['pace']}. "
                     f"Avevo dei target precisi: confronta TARGET vs ESEGUITO e dimmi "
                     f"se ho rispettato gli obiettivi di pace, di quanto ho sbagliato.")
            else:
                q = (f"Analizza nel dettaglio questa corsa libera: {att['sport']} del {att['data']}, "
                     f"nome: {att['nome']}, {att['distanza_km']}km in {att['durata_str']}, "
                     f"FC {att['fc_media']}bpm, pace {att['pace']}. "
                     f"Confronta con la baseline e mostra pace km per km, HR, elevazione, cadenza.")
            send_message(q)
            st.success("Analisi avviata. Vai alla sezione Chat per vedere i risultati.")
    else:
        st.markdown('<div style="color:#6e7681;font-size:13px;">Nessuna attivita trovata.</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CALENDARIO
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Calendario":
    st.markdown('<div style="font-size:16px;font-weight:700;color:#f0f6fc;margin-bottom:14px;">Calendario</div>', unsafe_allow_html=True)

    today = date.today()
    c1, c2 = st.columns(2)
    with c1:
        sel_month = st.selectbox("", range(1, 13), index=today.month - 1,
                                 format_func=lambda m: cal_module.month_name[m],
                                 label_visibility="collapsed")
    with c2:
        sel_year = st.selectbox("", [today.year - 1, today.year, today.year + 1],
                                index=1, label_visibility="collapsed")

    try:
        r = requests.get(f"{API}/calendar",
                         params={"year": sel_year, "month": sel_month}, timeout=30)
        items = r.json().get("items", [])
    except Exception as e:
        st.error(str(e)); items = []

    items_by_date = {}
    for item in items:
        d = item.get("data", "")
        items_by_date.setdefault(d, []).append(item)

    # Header giorni
    hcols = st.columns(7)
    for i, d in enumerate(["Lun","Mar","Mer","Gio","Ven","Sab","Dom"]):
        hcols[i].markdown(
            f'<div style="font-size:10px;font-weight:700;color:#6e7681;'
            f'text-transform:uppercase;letter-spacing:0.5px;padding:4px 0;">{d}</div>',
            unsafe_allow_html=True
        )

    for week in cal_module.monthcalendar(sel_year, sel_month):
        dcols = st.columns(7)
        for i, day_num in enumerate(week):
            with dcols[i]:
                if day_num == 0:
                    continue
                date_str = f"{sel_year}-{sel_month:02d}-{day_num:02d}"
                is_today = (date_str == today.isoformat())
                day_color = "#58a6ff" if is_today else "#c9d1d9"
                st.markdown(
                    f'<div style="font-size:12px;font-weight:{"700" if is_today else "400"};'
                    f'color:{day_color};padding:2px 0;">{day_num}</div>',
                    unsafe_allow_html=True
                )
                for item in items_by_date.get(date_str, []):
                    sport = item.get("sport", "")
                    title = item.get("titolo", "")[:14]
                    tipo = item.get("tipo", "")
                    bg = "#0c2a4a" if tipo == "workout" else "#0d2e1e"
                    color = "#58a6ff" if tipo == "workout" else "#3fb950"
                    st.markdown(
                        f'<div style="background:{bg};color:{color};font-size:9px;'
                        f'font-weight:600;padding:2px 4px;border-radius:3px;margin:1px 0;'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                        f'{title}</div>',
                        unsafe_allow_html=True
                    )

    st.markdown("<br>", unsafe_allow_html=True)
    planned  = [i for i in items if i.get("tipo") == "workout"]
    completed = [i for i in items if i.get("tipo") == "activity"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div style="font-size:12px;font-weight:600;color:#c9d1d9;margin-bottom:8px;">Pianificati</div>', unsafe_allow_html=True)
        if planned:
            rows = "".join(
                f"<tr><td style='color:#8b949e;white-space:nowrap;'>{w['data']}</td>"
                f"<td>{sport_badge(w.get('sport',''))}</td>"
                f"<td style='color:#c9d1d9;'>{w.get('titolo','')}</td></tr>"
                for w in sorted(planned, key=lambda x: x["data"])
            )
            st.markdown(f'<table class="tp-table"><thead><tr><th>Data</th><th>Sport</th><th>Nome</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:12px;color:#6e7681;">Nessun workout pianificato</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div style="font-size:12px;font-weight:600;color:#c9d1d9;margin-bottom:8px;">Completati</div>', unsafe_allow_html=True)
        if completed:
            rows = "".join(
                f"<tr><td style='color:#8b949e;white-space:nowrap;'>{a['data']}</td>"
                f"<td style='color:#c9d1d9;'>{a.get('titolo','')}</td>"
                f"<td style='color:#8b949e;white-space:nowrap;'>"
                f"{str(round(a['distanza_m']/1000,1))+' km' if a.get('distanza_m') else '—'}</td></tr>"
                for a in sorted(completed, key=lambda x: x["data"])
            )
            st.markdown(f'<table class="tp-table"><thead><tr><th>Data</th><th>Attivita</th><th>Dist.</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:12px;color:#6e7681;">Nessuna attivita completata</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: STATISTICHE
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Statistiche":
    st.markdown('<div style="font-size:16px;font-weight:700;color:#f0f6fc;margin-bottom:14px;">Statistiche</div>', unsafe_allow_html=True)

    try:
        r = requests.get(f"{API}/activities", params={"limit": 500}, timeout=30)
        all_activities = r.json().get("activities", [])
    except:
        all_activities = []

    if not all_activities:
        st.markdown('<div style="color:#6e7681;font-size:13px;">Nessun dato disponibile.</div>', unsafe_allow_html=True)
    else:
        sport_stats = {}
        for att in all_activities:
            sport = att["sport"]
            if sport not in sport_stats:
                sport_stats[sport] = {"count": 0, "total_km": 0.0, "total_min": 0.0, "fc_values": []}
            sport_stats[sport]["count"] += 1
            sport_stats[sport]["total_km"] += att.get("distanza_km", 0) or 0
            sport_stats[sport]["total_min"] += att.get("durata_min", 0) or 0
            if att.get("fc_media"):
                sport_stats[sport]["fc_values"].append(att["fc_media"])

        cols = st.columns(len(sport_stats))
        for i, (sport, s) in enumerate(sorted(sport_stats.items())):
            with cols[i]:
                badge = sport_badge(sport)
                h, m = divmod(int(s["total_min"]), 60)
                fc_avg = round(sum(s["fc_values"]) / len(s["fc_values"])) if s["fc_values"] else None
                st.markdown(f"""
                <div class="tp-card">
                    <div style="margin-bottom:10px;">{badge}</div>
                    <div class="s-stat">{s["count"]}</div>
                    <div class="s-label" style="margin-bottom:10px;">sessioni</div>
                    <div style="font-size:12px;color:#8b949e;line-height:1.9;">
                        {s["total_km"]:.1f} km<br>
                        {h}h {m}min
                        {"<br>"+str(fc_avg)+" bpm FC" if fc_avg else ""}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div style="font-size:13px;font-weight:600;color:#c9d1d9;margin-bottom:10px;">Cronologia</div>', unsafe_allow_html=True)
        render_activity_table(all_activities[:50])
