"""
app.py - v5
Chat che fa tutto: analisi passato, workout singoli, piani multi-allenamento
"""

import streamlit as st
import requests
from datetime import date
import calendar as cal_module

API = "https://ai-coach-backend-xc9s.onrender.com"

st.set_page_config(page_title="AI Triathlon Coach", page_icon="🏊", layout="wide")

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

SPORT_EMOJI = {"running": "🏃", "swimming": "🏊",
               "cycling": "🚴", "strength_training": "🏋️", "other": "⚡"}
SPORT_LABEL = {"running": "Corsa", "swimming": "Nuoto",
               "cycling": "Ciclismo", "strength_training": "Palestra"}

# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏊 🚴 🏃 AI Triathlon Coach")

if not st.session_state.logged_in:
    st.subheader("Benvenuto, Alessandro!")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔌 Connetti Garmin", use_container_width=True, type="primary"):
            with st.spinner("Connessione e download attività..."):
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
        st.write(f"**Attività:** {s.get('total_activities')}")
        st.write(f"**Sync:** {s.get('last_sync','')[:16]}")
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
        "", ["💬 Chat", "📋 Attività", "📅 Calendario", "📊 Statistiche"],
        label_visibility="collapsed"
    )

    # Suggerimenti comandi
    if page == "💬 Chat":
        st.divider()
        st.markdown("#### 💡 Cosa puoi chiedere")
        st.markdown("""
**📊 Analisi:**
- "Analizza la mia ultima corsa"
- "Dati lap del mio ultimo nuoto"
- "Come è andata la corsa di ieri?"

**🏋️ Workout singolo:**
- "Crea ripetute di corsa per domani"
- "Crea una sessione di nuoto giovedì"
- "Aggiungi palestra per lunedì"

**📅 Piano allenamenti:**
- "Crea un piano per questa settimana"
- "Pianifica 4 allenamenti per i prossimi 7 giorni"
- "Fai un piano triathlon per le prossime 2 settimane"

**💬 Consigli:**
- "Come posso migliorare il pace?"
- "Sono in sovrallenamento?"
- "Consigli per la settimana"
        """)

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE INVIO MESSAGGIO
# ─────────────────────────────────────────────────────────────────────────────

def send_message(message: str):
    """Invia messaggio al backend e aggiorna lo stato."""
    st.session_state.chat_history.append({"role": "user", "content": message})

    with st.spinner("Coach sta elaborando..."):
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


def confirm_action(action_type: str):
    """Chiama direttamente il backend per conferma o annulla."""
    with st.spinner("Caricando su Garmin..."):
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

            if action in ("workout_uploaded", "plan_uploaded", "cancelled"):
                st.session_state.pending_workout = None
                st.session_state.pending_plan = None

            st.session_state.chat_history.append({
                "role": "coach", "content": reply, "action": action
            })
        except Exception as e:
            st.error(str(e))

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA CHAT
# ─────────────────────────────────────────────────────────────────────────────

if page == "💬 Chat":
    st.subheader("💬 Parla con il tuo Coach")

    # ── Banner workout pendente — SEMPRE BOTTONI, MAI TESTO ──────────────────
    if st.session_state.pending_workout:
        wo = st.session_state.pending_workout
        emoji = SPORT_EMOJI.get(wo.get("sport", ""), "⚡")
        with st.container(border=True):
            st.markdown(
                f"### ⏳ Workout pronto per essere caricato\n"
                f"{emoji} **{wo.get('name')}** — 📅 {wo.get('scheduled_date')} "
                f"| 🏋️ {SPORT_LABEL.get(wo.get('sport',''), wo.get('sport',''))}"
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ CARICA SU GARMIN", type="primary",
                             use_container_width=True, key="confirm_wo_top"):
                    confirm_action("confermo")
                    st.rerun()
            with c2:
                if st.button("❌ Annulla", use_container_width=True, key="cancel_wo_top"):
                    confirm_action("annulla")
                    st.rerun()

    # ── Banner piano pendente ─────────────────────────────────────────────────
    if st.session_state.pending_plan:
        plan = st.session_state.pending_plan
        sports_in_plan = list({w.get("sport","") for w in plan})
        sport_emojis = " ".join(SPORT_EMOJI.get(s,"⚡") for s in sports_in_plan)
        with st.container(border=True):
            st.markdown(
                f"### ⏳ Piano pronto per essere caricato\n"
                f"{sport_emojis} **{len(plan)} allenamenti** pronti per Garmin Connect"
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ CARICA TUTTO SU GARMIN", type="primary",
                             use_container_width=True, key="confirm_plan_top"):
                    confirm_action("carica tutto")
                    st.rerun()
            with c2:
                if st.button("🔍 Vedi dettagli step", use_container_width=True,
                             key="details_plan_top"):
                    send_message("dettagli")
                    st.rerun()
            with c3:
                if st.button("❌ Annulla piano", use_container_width=True,
                             key="cancel_plan_top"):
                    confirm_action("annulla")
                    st.rerun()

    st.divider()

    # ── Comandi rapidi ────────────────────────────────────────────────────────
    with st.expander("⚡ Comandi rapidi", expanded=False):
        tab1, tab2, tab3 = st.tabs(["📊 Analisi", "🏋️ Workout", "📅 Piani"])

        with tab1:
            cols = st.columns(2)
            for i, q in enumerate([
                "Analizza la mia ultima corsa",
                "Analizza il mio ultimo nuoto",
                "Dati lap, cadenza e HR ultima corsa",
                "Come stanno le mie performance?",
                "Sono in sovrallenamento?",
                "Confronta le mie ultime corse",
            ]):
                with cols[i % 2]:
                    if st.button(q, use_container_width=True, key=f"qa_{i}"):
                        send_message(q)
                        st.rerun()

        with tab2:
            cols = st.columns(2)
            for i, q in enumerate([
                "Crea ripetute di corsa per domani",
                "Crea sessione nuoto per dopodomani",
                "Crea allenamento bici per giovedì",
                "Crea sessione palestra per oggi",
                "Crea un lungo di corsa per domenica",
                "Crea interval training nuoto",
            ]):
                with cols[i % 2]:
                    if st.button(q, use_container_width=True, key=f"qw_{i}"):
                        send_message(q)
                        st.rerun()

        with tab3:
            cols = st.columns(2)
            for i, q in enumerate([
                "Crea un piano per questa settimana",
                "Pianifica 5 allenamenti per i prossimi 7 giorni",
                "Crea un piano triathlon per le prossime 2 settimane",
                "Piano intenso: nuoto, corsa e palestra questa settimana",
                "Piano di recupero per questa settimana",
                "Piano con focus sul nuoto per 10 giorni",
            ]):
                with cols[i % 2]:
                    if st.button(q, use_container_width=True, key=f"qp_{i}"):
                        send_message(q)
                        st.rerun()

    st.divider()

    # ── Storico chat ──────────────────────────────────────────────────────────
    for idx, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.write(msg["content"])
        else:
            action = msg.get("action", "chat")
            avatar = {"workout_uploaded": "✅", "plan_uploaded": "✅",
                      "analysis": "🔬", "plan_preview": "📅",
                      "workout_preview": "📋"}.get(action, "🏅")

            with st.chat_message("assistant", avatar=avatar):
                st.markdown(msg["content"])

                # ── Bottoni SOLO per l'ULTIMO messaggio di tipo preview ────────
                is_last = (idx == len(st.session_state.chat_history) - 1)

                if is_last and action == "workout_preview" and st.session_state.pending_workout:
                    st.markdown("---")
                    st.markdown("**Cosa vuoi fare?**")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Carica su Garmin", type="primary",
                                     use_container_width=True, key=f"ci_wo_{idx}"):
                            confirm_action("confermo")
                            st.rerun()
                    with c2:
                        if st.button("❌ Annulla", use_container_width=True,
                                     key=f"cx_wo_{idx}"):
                            confirm_action("annulla")
                            st.rerun()

                if is_last and action == "plan_preview" and st.session_state.pending_plan:
                    st.markdown("---")
                    st.markdown("**Cosa vuoi fare?**")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("✅ Carica tutto su Garmin", type="primary",
                                     use_container_width=True, key=f"ci_pl_{idx}"):
                            confirm_action("carica tutto")
                            st.rerun()
                    with c2:
                        if st.button("🔍 Vedi dettagli step", use_container_width=True,
                                     key=f"cd_pl_{idx}"):
                            send_message("dettagli")
                            st.rerun()
                    with c3:
                        if st.button("❌ Annulla piano", use_container_width=True,
                                     key=f"cx_pl_{idx}"):
                            confirm_action("annulla")
                            st.rerun()

    # ── Input chat ────────────────────────────────────────────────────────────
    # Blocca input testuale se c'è un pending — SOLO bottoni
    if st.session_state.pending_workout or st.session_state.pending_plan:
        st.info("👆 Usa i pulsanti sopra per confermare o annullare prima di continuare.")
    else:
        user_input = st.chat_input(
            "Chiedi un'analisi, crea un workout o un piano allenamenti..."
        )
        if user_input:
            send_message(user_input)
            st.rerun()

    if st.session_state.chat_history:
        if st.button("🗑️ Pulisci chat"):
            st.session_state.chat_history = []
            st.session_state.pending_workout = None
            st.session_state.pending_plan = None
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA ATTIVITÀ
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
            f"{emoji} {att['data']} — {att['nome']} | {att['distanza_km']}km | {att['durata_str']}"
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Distanza", f"{att['distanza_km']} km")
            c2.metric("Durata", att["durata_str"])
            c3.metric("FC Media", f"{att['fc_media']} bpm" if att["fc_media"] else "N/A")
            c4.metric("Pace", att["pace"] or "N/A")
            if att.get("calorie"):
                st.write(f"🔥 {att['calorie']} kcal")

            if st.button("🔬 Analizza con Coach", key=f"aa_{att.get('garmin_id')}",
                         type="primary", use_container_width=True):
                q = (f"Analizza nel dettaglio questa attività: "
                     f"{att['sport']} del {att['data']}, nome: {att['nome']}, "
                     f"{att['distanza_km']}km in {att['durata_str']}, "
                     f"FC {att['fc_media']}bpm, pace {att['pace']}. "
                     f"Voglio vedere pace istantaneo km per km, HR, elevazione, cadenza e performance condition.")
                send_message(q)
                st.success("✅ Analisi avviata! Vai su 💬 Chat per vedere i risultati.")


elif page == "📅 Calendario":
    st.subheader("📅 Calendario Allenamenti")

    today = date.today()
    col1, col2 = st.columns(2)
    with col1:
        sel_month = st.selectbox("Mese", range(1, 13), index=today.month - 1,
                                 format_func=lambda m: cal_module.month_name[m])
    with col2:
        sel_year = st.selectbox("Anno", [today.year - 1, today.year, today.year + 1], index=1)

    try:
        r = requests.get(f"{API}/calendar",
                         params={"year": sel_year, "month": sel_month}, timeout=30)
        items = r.json().get("items", [])
    except Exception as e:
        st.error(str(e))
        items = []

    items_by_date = {}
    for item in items:
        d = item.get("data", "")
        items_by_date.setdefault(d, []).append(item)

    st.markdown(f"### {cal_module.month_name[sel_month]} {sel_year}")
    for d in ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]:
        st.columns(7)[["Lun","Mar","Mer","Gio","Ven","Sab","Dom"].index(d)].markdown(f"**{d}**")

    for week in cal_module.monthcalendar(sel_year, sel_month):
        day_cols = st.columns(7)
        for i, day_num in enumerate(week):
            with day_cols[i]:
                if day_num == 0:
                    continue
                date_str = f"{sel_year}-{sel_month:02d}-{day_num:02d}"
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
    planned = [i for i in items if i.get("tipo") == "workout"]
    completed = [i for i in items if i.get("tipo") == "activity"]
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📋 Pianificati")
        for wo in sorted(planned, key=lambda x: x["data"]):
            st.write(f"{SPORT_EMOJI.get(wo.get('sport',''),'⚡')} **{wo['data']}** — {wo['titolo']}")
        if not planned:
            st.info("Nessun workout pianificato")
    with col2:
        st.markdown("#### ✅ Completati")
        for att in sorted(completed, key=lambda x: x["data"]):
            dist = att.get("distanza_m", 0)
            st.write(f"🏅 **{att['data']}** — {att['titolo']}"
                     f"{' | '+str(round(dist/1000,1))+'km' if dist else ''}")
        if not completed:
            st.info("Nessuna attività completata")

    st.divider()
    st.info("💡 Vai nella **💬 Chat** per creare workout singoli o piani interi!")

# ─────────────────────────────────────────────────────────────────────────────
# PAGINA STATISTICHE
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📊 Statistiche":
    st.subheader("📊 Statistiche")
    try:
        r = requests.get(f"{API}/activities", params={"limit": 500}, timeout=30)
        all_activities = r.json().get("activities", [])
    except:
        all_activities = []

    if not all_activities:
        st.info("Nessun dato. Fai prima il login.")
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
