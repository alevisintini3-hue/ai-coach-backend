"""
app.py - v4
Chat con flusso di conferma per creare allenamenti su Garmin
"""

import streamlit as st
import requests
from datetime import datetime, date, timedelta
import calendar as cal_module

API = "https://ai-coach-backend-xc9s.onrender.com"

st.set_page_config(page_title="AI Triathlon Coach", page_icon="🏊", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────

defaults = {
    "logged_in": False,
    "chat_history": [],
    "pending_workout": None,   # workout in attesa di conferma
    "conversation_id": "default",
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

SPORT_EMOJI = {
    "running": "🏃", "swimming": "🏊",
    "cycling": "🚴", "strength_training": "🏋️", "other": "⚡",
}
SPORT_LABEL = {
    "running": "Corsa", "swimming": "Nuoto",
    "cycling": "Ciclismo", "strength_training": "Palestra",
}

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏊 🚴 🏃 AI Triathlon Coach")

if not st.session_state.logged_in:
    st.subheader("Benvenuto, Alessandro!")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔌 Connetti Garmin", use_container_width=True, type="primary"):
            with st.spinner("Connessione a Garmin..."):
                try:
                    r = requests.post(f"{API}/login", timeout=120)
                    data = r.json()
                    if data.get("status") in ("success", "already_logged_in"):
                        st.session_state.logged_in = True
                        st.success(f"✅ {data.get('total_activities', 0)} attività caricate!")
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
    st.markdown("### 🏅 Status")
    try:
        r = requests.get(f"{API}/status", timeout=10)
        s = r.json()
        st.success("🟢 Online")
        st.write(f"**Attività:** {s.get('total_activities', '?')}")
        st.write(f"**Sync:** {s.get('last_sync', '?')[:16]}")
    except:
        st.warning("⚠️ Backend non raggiungibile")

    st.divider()
    if st.button("🔄 Sync Garmin", use_container_width=True):
        with st.spinner("Sincronizzando..."):
            try:
                r = requests.get(f"{API}/sync", timeout=120)
                st.success(f"✅ {r.json().get('total_activities')} attività")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    page = st.radio(
        "",
        ["💬 Chat", "📋 Attività", "📅 Calendario", "📊 Statistiche"],
        label_visibility="collapsed"
    )

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def send_chat(message: str):
    """Invia un messaggio al backend e aggiorna lo stato."""
    st.session_state.chat_history.append({"role": "user", "content": message})

    with st.spinner("Coach sta pensando..."):
        try:
            r = requests.post(
                f"{API}/chat",
                json={"message": message, "conversation_id": st.session_state.conversation_id},
                timeout=90,
            )
            data = r.json()
            reply = data.get("message", "Errore")
            action = data.get("action", "chat")
            pending = data.get("pending_workout")

            # Salva il workout pendente nello state
            if action == "workout_preview" and pending:
                st.session_state.pending_workout = pending
            elif action in ("workout_uploaded", "workout_cancelled"):
                st.session_state.pending_workout = None

            st.session_state.chat_history.append({
                "role": "coach",
                "content": reply,
                "action": action,
            })

        except Exception as e:
            st.session_state.chat_history.append({
                "role": "coach",
                "content": f"❌ Errore: {e}",
                "action": "error",
            })

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CHAT
# ─────────────────────────────────────────────────────────────────────────────

if page == "💬 Chat":
    st.subheader("💬 Parla con il tuo Coach")

    # ── Banner workout pendente ───────────────────────────────────────────────
    if st.session_state.pending_workout:
        pending = st.session_state.pending_workout
        with st.container(border=True):
            st.markdown(
                f"⏳ **Workout in attesa di conferma:** "
                f"{SPORT_EMOJI.get(pending.get('sport',''), '⚡')} "
                f"**{pending.get('name')}** — {pending.get('scheduled_date')}"
            )
            col1, col2, col3 = st.columns([2, 1, 1])
            with col2:
                if st.button("✅ Sì, carica!", type="primary", use_container_width=True):
                    send_chat("Sì, confermo")
                    st.rerun()
            with col3:
                if st.button("❌ Annulla", use_container_width=True):
                    send_chat("No, annulla")
                    st.rerun()

    st.divider()

    # ── Domande rapide ────────────────────────────────────────────────────────
    quick = [
        "Come stanno i miei allenamenti?",
        "Crea un allenamento di corsa per domani",
        "Crea ripetute in piscina per giovedì",
        "Segnali di sovrallenamento?",
        "Come migliorare il nuoto?",
        "Crea una sessione di palestra per oggi",
    ]

    st.markdown("**Domande rapide:**")
    cols = st.columns(3)
    for i, q in enumerate(quick):
        with cols[i % 3]:
            if st.button(q, use_container_width=True, key=f"q_{i}"):
                send_chat(q)
                st.rerun()

    st.divider()

    # ── Storico messaggi ──────────────────────────────────────────────────────
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.write(msg["content"])
        else:
            action = msg.get("action", "chat")
            avatar = "✅" if action == "workout_uploaded" else "🏅"
            with st.chat_message("assistant", avatar=avatar):
                st.markdown(msg["content"])

                # Se era un preview di workout, mostra i pulsanti inline
                if action == "workout_preview" and st.session_state.pending_workout:
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button(
                            "✅ Sì, carica su Garmin!",
                            key=f"confirm_{id(msg)}",
                            type="primary",
                            use_container_width=True,
                        ):
                            send_chat("Sì, confermo")
                            st.rerun()
                    with c2:
                        if st.button(
                            "❌ Annulla",
                            key=f"cancel_{id(msg)}",
                            use_container_width=True,
                        ):
                            send_chat("No, annulla")
                            st.rerun()

    # ── Input ─────────────────────────────────────────────────────────────────
    user_input = st.chat_input(
        "Fai una domanda o di' al coach di creare un allenamento..."
    )
    if user_input:
        send_chat(user_input)
        st.rerun()

    if st.session_state.chat_history:
        if st.button("🗑️ Pulisci chat"):
            st.session_state.chat_history = []
            st.session_state.pending_workout = None
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: ATTIVITÀ
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📋 Attività":
    st.subheader("📋 Le tue Attività")
    col1, col2 = st.columns([2, 1])
    with col1:
        sport_filter = st.selectbox(
            "Sport", ["Tutti", "running", "swimming", "cycling", "strength_training"]
        )
    with col2:
        limit = st.selectbox("Quante", [20, 50, 100])

    try:
        params = {"limit": limit}
        if sport_filter != "Tutti":
            params["sport"] = sport_filter
        r = requests.get(f"{API}/activities", params=params, timeout=30)
        activities = r.json().get("activities", [])
    except Exception as e:
        st.error(str(e))
        activities = []

    st.write(f"**{len(activities)} attività**")
    for att in activities:
        emoji = SPORT_EMOJI.get(att["sport"], "⚡")
        with st.expander(
            f"{emoji} {att['data']} — {att['nome']} | {att['distanza_km']} km | {att['durata_str']}"
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Distanza", f"{att['distanza_km']} km")
            c2.metric("Durata", att["durata_str"])
            c3.metric("FC Media", f"{att['fc_media']} bpm" if att["fc_media"] else "N/A")
            c4.metric("Pace", att["pace"] or "N/A")
            if att.get("calorie"):
                st.write(f"🔥 {att['calorie']} kcal")
            if st.button("💬 Analizza con Coach", key=f"a_{att.get('garmin_id')}"):
                q = (
                    f"Analizza questa attività: {att['sport']} del {att['data']}, "
                    f"{att['distanza_km']}km in {att['durata_str']}, "
                    f"FC {att['fc_media']}bpm, pace {att['pace']}."
                )
                r2 = requests.post(f"{API}/chat",
                                   json={"message": q, "conversation_id": "activity_analysis"},
                                   timeout=60)
                st.info(r2.json().get("message", "Errore"))

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CALENDARIO
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📅 Calendario":
    st.subheader("📅 Calendario Allenamenti")

    today = date.today()
    col1, col2 = st.columns(2)
    with col1:
        selected_month = st.selectbox(
            "Mese", range(1, 13), index=today.month - 1,
            format_func=lambda m: cal_module.month_name[m],
        )
    with col2:
        selected_year = st.selectbox(
            "Anno", [today.year - 1, today.year, today.year + 1], index=1
        )

    try:
        r = requests.get(f"{API}/calendar",
                         params={"year": selected_year, "month": selected_month}, timeout=30)
        items = r.json().get("items", [])
    except Exception as e:
        st.error(str(e))
        items = []

    # Organizza per data
    items_by_date = {}
    for item in items:
        d = item.get("data", "")
        items_by_date.setdefault(d, []).append(item)

    # Griglia calendario
    st.markdown(f"### {cal_module.month_name[selected_month]} {selected_year}")
    day_cols = st.columns(7)
    for i, d in enumerate(["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]):
        day_cols[i].markdown(f"**{d}**")

    for week in cal_module.monthcalendar(selected_year, selected_month):
        day_cols = st.columns(7)
        for i, day_num in enumerate(week):
            with day_cols[i]:
                if day_num == 0:
                    st.write("")
                    continue
                date_str = f"{selected_year}-{selected_month:02d}-{day_num:02d}"
                is_today = (date_str == today.isoformat())
                st.markdown(f"**{'🔵 ' if is_today else ''}{day_num}**")
                for item in items_by_date.get(date_str, []):
                    emoji = SPORT_EMOJI.get(item.get("sport", ""), "⚡")
                    if item.get("tipo") == "workout":
                        st.success(f"{emoji} {item.get('titolo','')[:12]}")
                    else:
                        dist = item.get("distanza_m", 0)
                        label = f"{dist/1000:.1f}km" if dist else item.get("titolo","")[:10]
                        st.info(f"{emoji} {label}")

    st.divider()

    # Lista
    planned = [i for i in items if i.get("tipo") == "workout"]
    completed = [i for i in items if i.get("tipo") == "activity"]
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📋 Pianificati")
        for wo in sorted(planned, key=lambda x: x["data"]):
            emoji = SPORT_EMOJI.get(wo.get("sport", ""), "⚡")
            st.write(f"{emoji} **{wo['data']}** — {wo['titolo']}")
        if not planned:
            st.info("Nessun workout pianificato")
    with col2:
        st.markdown("#### ✅ Completati")
        for att in sorted(completed, key=lambda x: x["data"]):
            dist = att.get("distanza_m", 0)
            st.write(
                f"🏅 **{att['data']}** — {att['titolo']} "
                f"{'| '+str(round(dist/1000,1))+'km' if dist else ''}"
            )
        if not completed:
            st.info("Nessuna attività completata")

    st.divider()
    st.markdown("### ➕ Crea Workout via Chat")
    st.info(
        "💡 Vai nella sezione **💬 Chat** e scrivi cosa vuoi fare!\n\n"
        "Esempio: _\"Crea ripetute di nuoto per giovedì\"_\n\n"
        "Il coach genererà l'allenamento e ti chiederà conferma prima di caricarlo su Garmin."
    )

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: STATISTICHE
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📊 Statistiche":
    st.subheader("📊 Statistiche")
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
                sport_stats[sport] = {"count": 0, "total_km": 0,
                                       "total_min": 0, "fc_values": []}
            sport_stats[sport]["count"] += 1
            sport_stats[sport]["total_km"] += att["distanza_km"]
            sport_stats[sport]["total_min"] += att["durata_min"]
            if att["fc_media"]:
                sport_stats[sport]["fc_values"].append(att["fc_media"])

        cols = st.columns(len(sport_stats))
        for i, (sport, s) in enumerate(sorted(sport_stats.items())):
            with cols[i]:
                emoji = SPORT_EMOJI.get(sport, "⚡")
                st.metric(f"{emoji} {SPORT_LABEL.get(sport, sport)}", f"{s['count']} sessioni")
                st.write(f"📏 **{s['total_km']:.1f} km**")
                h, m = divmod(int(s["total_min"]), 60)
                st.write(f"⏱️ **{h}h {m}min**")
                if s["fc_values"]:
                    st.write(f"❤️ **{sum(s['fc_values'])/len(s['fc_values']):.0f} bpm**")

        st.divider()
        import pandas as pd
        df = pd.DataFrame([{
            "Data": a["data"], "Sport": a["sport"], "Nome": a["nome"],
            "Km": a["distanza_km"], "Durata": a["durata_str"],
            "FC": a["fc_media"], "Pace": a["pace"],
        } for a in all_activities[:50]])
        st.dataframe(df, use_container_width=True, hide_index=True)
