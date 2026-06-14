"""
app.py - Streamlit frontend v2
AI Triathlon Coach con lista attività, filtri e chat
"""

import streamlit as st
import requests
from datetime import datetime

API = "https://ai-coach-backend-xc9s.onrender.com"

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE PAGINA
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Triathlon Coach",
    page_icon="🏊",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# SESSIONE
# ─────────────────────────────────────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "activities" not in st.session_state:
    st.session_state.activities = []

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏊 🚴 🏃 AI Triathlon Coach")

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

if not st.session_state.logged_in:
    st.subheader("Benvenuto, Alessandro!")
    st.write("Connettiti a Garmin Connect per iniziare.")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔌 Connetti Garmin", use_container_width=True, type="primary"):
            with st.spinner("Connessione a Garmin e download attività..."):
                try:
                    r = requests.post(f"{API}/login", timeout=120)
                    data = r.json()

                    if data.get("status") in ("success", "already_logged_in"):
                        st.session_state.logged_in = True
                        st.session_state.total_activities = data.get("total_activities", 0)
                        st.success(f"✅ Connesso! {data.get('total_activities', 0)} attività caricate.")
                        st.rerun()
                    else:
                        st.error(f"Errore: {data}")
                except Exception as e:
                    st.error(f"Errore connessione: {e}")

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR (quando loggato)
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🏅 Coach Dashboard")

    # Status
    try:
        r = requests.get(f"{API}/status", timeout=10)
        s = r.json()
        st.success(f"🟢 Online")
        st.write(f"**Attività totali:** {s.get('total_activities', '?')}")
        st.write(f"**Ultimo sync:** {s.get('last_sync', '?')[:16]}")
        sports = s.get("sports", [])
        if sports:
            st.write(f"**Sport:** {', '.join(sports)}")
    except:
        st.warning("Backend non raggiungibile")

    st.divider()

    # Sync manuale
    if st.button("🔄 Sincronizza Garmin", use_container_width=True):
        with st.spinner("Sincronizzazione..."):
            try:
                r = requests.get(f"{API}/sync", timeout=120)
                data = r.json()
                st.success(f"✅ Sync completato! {data.get('total_activities')} attività")
                st.rerun()
            except Exception as e:
                st.error(f"Errore sync: {e}")

    st.divider()

    # Navigazione
    st.markdown("### 📍 Sezioni")
    page = st.radio(
        "",
        ["💬 Chat con Coach", "📋 Attività", "📊 Statistiche"],
        label_visibility="collapsed"
    )

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: CHAT
# ─────────────────────────────────────────────────────────────────────────────

if page == "💬 Chat con Coach":
    st.subheader("💬 Parla con il tuo Coach")

    # Domande rapide
    st.markdown("**Domande rapide:**")
    cols = st.columns(3)
    quick_questions = [
        "Come stanno i miei allenamenti?",
        "Analizza la mia corsa",
        "Segnali di sovrallenamento?",
        "Come migliorare il nuoto?",
        "Consigli per questa settimana",
        "Valuta la mia progressione",
    ]

    for i, q in enumerate(quick_questions):
        with cols[i % 3]:
            if st.button(q, use_container_width=True, key=f"quick_{i}"):
                st.session_state.chat_history.append({"role": "user", "content": q})
                with st.spinner("Coach sta pensando..."):
                    try:
                        r = requests.post(
                            f"{API}/chat",
                            json={"message": q},
                            timeout=60
                        )
                        answer = r.json().get("message", "Errore")
                        st.session_state.chat_history.append({"role": "coach", "content": answer})
                    except Exception as e:
                        st.error(f"Errore: {e}")
                st.rerun()

    st.divider()

    # Storico chat
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.write(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🏅"):
                st.write(msg["content"])

    # Input chat
    user_input = st.chat_input("Fai una domanda al coach...")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.spinner("Coach sta pensando..."):
            try:
                r = requests.post(
                    f"{API}/chat",
                    json={"message": user_input},
                    timeout=60
                )
                answer = r.json().get("message", "Errore")
                st.session_state.chat_history.append({"role": "coach", "content": answer})
            except Exception as e:
                answer = f"Errore: {e}"
                st.session_state.chat_history.append({"role": "coach", "content": answer})

        st.rerun()

    # Pulsante pulisci
    if st.session_state.chat_history:
        if st.button("🗑️ Pulisci chat"):
            st.session_state.chat_history = []
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: ATTIVITÀ
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📋 Attività":
    st.subheader("📋 Le tue Attività")

    # Filtri
    col1, col2 = st.columns([2, 1])
    with col1:
        sport_filter = st.selectbox(
            "Filtra per sport",
            ["Tutti", "running", "swimming", "cycling", "strength_training", "other"],
        )
    with col2:
        limit = st.selectbox("Quante attività", [20, 50, 100, 200], index=0)

    # Carica attività
    with st.spinner("Caricando attività..."):
        try:
            params = {"limit": limit}
            if sport_filter != "Tutti":
                params["sport"] = sport_filter

            r = requests.get(f"{API}/activities", params=params, timeout=30)
            data = r.json()
            activities = data.get("activities", [])
        except Exception as e:
            st.error(f"Errore: {e}")
            activities = []

    if not activities:
        st.info("Nessuna attività trovata.")
    else:
        st.write(f"**{len(activities)} attività trovate**")
        st.divider()

        # Emoji per sport
        sport_emoji = {
            "running": "🏃",
            "swimming": "🏊",
            "cycling": "🚴",
            "strength_training": "🏋️",
            "other": "⚡",
        }

        for att in activities:
            emoji = sport_emoji.get(att["sport"], "⚡")

            with st.expander(
                f"{emoji} {att['data']} — {att['nome']} | {att['distanza_km']} km | {att['durata_str']}"
            ):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Distanza", f"{att['distanza_km']} km")
                with col2:
                    st.metric("Durata", att["durata_str"])
                with col3:
                    st.metric("FC Media", f"{att['fc_media']} bpm" if att["fc_media"] else "N/A")
                with col4:
                    st.metric("Pace", att["pace"] if att["pace"] else "N/A")

                if att.get("calorie"):
                    st.write(f"🔥 Calorie: **{att['calorie']} kcal**")
                if att.get("fc_max"):
                    st.write(f"❤️ FC massima: **{att['fc_max']} bpm**")

                # Pulsante "chiedi al coach" su questa attività
                if st.button(
                    "💬 Analizza con il Coach",
                    key=f"analyze_{att.get('garmin_id', att['data'])}",
                ):
                    question = (
                        f"Analizza questa attività: {att['sport']} del {att['data']}, "
                        f"{att['distanza_km']}km in {att['durata_str']}, "
                        f"FC media {att['fc_media']}bpm, pace {att['pace']}. "
                        f"Come è andata? Cosa posso migliorare?"
                    )
                    with st.spinner("Coach sta analizzando..."):
                        try:
                            r = requests.post(
                                f"{API}/chat",
                                json={"message": question},
                                timeout=60
                            )
                            answer = r.json().get("message", "Errore")
                            st.session_state.chat_history.append({"role": "user", "content": question})
                            st.session_state.chat_history.append({"role": "coach", "content": answer})
                            st.info(answer)
                        except Exception as e:
                            st.error(f"Errore: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA: STATISTICHE
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📊 Statistiche":
    st.subheader("📊 Le tue Statistiche")

    # Carica tutte le attività per le stats
    try:
        r = requests.get(f"{API}/activities", params={"limit": 500}, timeout=30)
        all_activities = r.json().get("activities", [])
    except:
        all_activities = []

    if not all_activities:
        st.info("Nessun dato disponibile. Fai prima il login.")
    else:
        # Aggrega per sport
        sport_stats = {}
        for att in all_activities:
            sport = att["sport"]
            if sport not in sport_stats:
                sport_stats[sport] = {
                    "count": 0,
                    "total_km": 0,
                    "total_min": 0,
                    "fc_values": [],
                }
            sport_stats[sport]["count"] += 1
            sport_stats[sport]["total_km"] += att["distanza_km"]
            sport_stats[sport]["total_min"] += att["durata_min"]
            if att["fc_media"]:
                sport_stats[sport]["fc_values"].append(att["fc_media"])

        # Cards per sport
        sport_emoji = {
            "running": "🏃",
            "swimming": "🏊",
            "cycling": "🚴",
            "strength_training": "🏋️",
        }

        cols = st.columns(len(sport_stats))
        for i, (sport, stats) in enumerate(sorted(sport_stats.items())):
            emoji = sport_emoji.get(sport, "⚡")
            with cols[i]:
                st.metric(f"{emoji} {sport}", f"{stats['count']} sessioni")
                st.write(f"📏 **{stats['total_km']:.1f} km**")
                h, m = divmod(int(stats["total_min"]), 60)
                st.write(f"⏱️ **{h}h {m}min**")
                if stats["fc_values"]:
                    avg_fc = sum(stats["fc_values"]) / len(stats["fc_values"])
                    st.write(f"❤️ **FC media: {avg_fc:.0f} bpm**")

        st.divider()

        # Tabella ultime attività
        st.markdown("### 📅 Cronologia recente")

        import pandas as pd

        df_data = []
        for att in all_activities[:30]:
            df_data.append({
                "Data": att["data"],
                "Sport": att["sport"],
                "Nome": att["nome"],
                "Distanza (km)": att["distanza_km"],
                "Durata": att["durata_str"],
                "FC Media": att["fc_media"],
                "Pace": att["pace"],
            })

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
