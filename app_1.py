import streamlit as st
import requests

API = "http://localhost:8000"

st.title("🏊 AI Triathlon Coach")

if st.button("🔄 Login Garmin"):
    r = requests.post(f"{API}/login")
    st.json(r.json())

if st.button("📊 Status"):
    r = requests.get(f"{API}/status")
    st.json(r.json())

question = st.text_area(
    "Chiedi qualcosa al coach"
)

if st.button("Invia"):
    r = requests.post(
        f"{API}/chat",
        json={"message": question}
    )

    st.write(r.json()["message"])