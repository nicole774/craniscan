# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — SERVEUR API (FastAPI)
===============================================================================
Ce fichier est le « chef d'orchestre » : il branche ensemble
  · le moteur de triage  (app/triage.py)      → la médecine
  · la base de données   (app/db.py)          → la mémoire
  · l'assistant Naya     (app/assistant.py)   → la conversation
  · le capteur virtuel   (app/devices.py)     → le matériel simulé
  · le planificateur     (app/scheduler.py)   → les tâches automatiques

DEUX CANAUX DE COMMUNICATION avec l'app mobile :
  1. REST (POST/GET)  : actions explicites du patient (créer un incident,
     répondre à un re-contrôle, discuter avec Naya) — simple et fiable.
  2. WEBSOCKET        : poussée temps réel (trames du capteur pendant
     l'examen, événements du planificateur « re-contrôle à faire ») —
     le serveur parle au téléphone SQUANT le téléphone demande.

Lancement :  python backend/run.py   →  http://127.0.0.1:8000
===============================================================================
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import fields as dc_fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db
from app.assistant import Assistant
from app.devices import VirtualCraniCap, PAIR_NAMES
from app.scheduler import Scheduler, schedule_followup, FAST_SCHED
from app.triage import (
    Consciousness, Incident, NirsExam, Profile, PupilExam, Symptoms, run_triage,
)

# -----------------------------------------------------------------------------
# Démarrage / arrêt (lifespan = la façon moderne FastAPI de gérer le cycle de vie)
# -----------------------------------------------------------------------------

scheduler = Scheduler()
naya = Assistant()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    FAST_SCHED = os.environ.get("CRANISCAN_FAST_SCHED") == "1"
    import app.scheduler as sch
    sch.FAST_SCHED = FAST_SCHED
    scheduler.start(asyncio.get_running_loop())
    yield
    scheduler.stop()


app = FastAPI(title="CrâniScan API", version="1.0.0", lifespan=lifespan)

# CORS : autorise l'app (dev) à appeler l'API depuis n'importe quelle origine.
# En production : restreindre aux domaines de l'app.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# L'app mobile (PWA) est servie par le même serveur → un seul processus pour
# tout démontrer, et pas de problème de CORS en production.
MOBILE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "mobile-app")
if os.path.isdir(MOBILE_DIR):
    app.mount("/", StaticFiles(directory=MOBILE_DIR, html=True), name="mobile")


# -----------------------------------------------------------------------------
# Petits utilitaires (conversions dict ↔ dataclasses)
# -----------------------------------------------------------------------------

def filter_fields(data: dict, cls) -> dict:
    """Ne garde que les clés connues de la dataclass (l'app peut envoyer des
    champs en plus sans casser le moteur)."""
    allowed = {f.name for f in dc_fields(cls)} if is_dataclass(cls) else set()
    return {k: v for k, v in (data or {}).items() if k in allowed}


def parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# Modèles d'entrée (Pydantic = validation automatique des requêtes)
# -----------------------------------------------------------------------------

class IncidentIn(BaseModel):
    profile: Dict[str, Any] = {}
    incident: Dict[str, Any] = {}
    consciousness: Dict[str, Any] = {}
    symptoms: Dict[str, Any] = {}
    pupils: Optional[Dict[str, Any]] = None


class RecheckIn(BaseModel):
    symptoms: Dict[str, Any] = {}
    pupils: Optional[Dict[str, Any]] = None


class ExamIn(BaseModel):
    source: str = "simulateur"          # bandeau | simulateur | sans_capteur
    scenario: str = "normal"            # pour le simulateur
    measurements: Optional[List[Dict[str, Any]]] = None  # du vrai bandeau
    pupils: Optional[Dict[str, Any]] = None


class ChatIn(BaseModel):
    session: str
    message: str
    incident_id: Optional[int] = None


class ContactsIn(BaseModel):
    contacts: List[Dict[str, Any]]


# -----------------------------------------------------------------------------
# WebSockets
# -----------------------------------------------------------------------------

clients: Set[WebSocket] = set()


async def broadcast(event: Dict[str, Any]) -> None:
    """Envoie un événement à toutes les apps connectées (planificateur…)."""
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    """Canal d'événements serveur → app (re-contrôles dus, rappels, alertes)."""
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # garde la connexion vivante (ping)
    except WebSocketDisconnect:
        clients.discard(ws)


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
    """Canal du capteur : l'app envoie {'cmd':'start_exam','scenario':...},
    le serveur répond par le flux de trames NIR/IMU/PPG du bandeau (virtuel
    ou, à terme, relais BLE du vrai CrâniCap)."""
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("cmd") == "start_exam":
                device = VirtualCraniCap(scenario=msg.get("scenario", "normal"))
                async for frame in device.stream_exam():
                    await ws.send_json(frame)
            elif msg.get("cmd") == "battery":
                await ws.send_json({"type": "status", "battery": 88})
    except WebSocketDisconnect:
        pass


# -----------------------------------------------------------------------------
# Endpoints REST
# -----------------------------------------------------------------------------

@app.get("/api/health")
def health():
    import app.scheduler as sch
    return {"status": "ok", "service": "CrâniScan", "version": "1.0.0",
            "fast_scheduler": sch.FAST_SCHED}


@app.post("/api/incidents")
def create_incident(body: IncidentIn):
    """Nouvel accident → questionnaire → verdict + plan de surveillance auto.

    C'est le point d'entrée principal de l'app : il convertit les réponses du
    questionnaire en dataclasses du moteur, calcule le verdict, l'enregistre
    et programme les re-contrôles automatiques (2 h/6 h/24 h…)."""
    profile = Profile(**filter_fields(body.profile, Profile))
    inc_data = filter_fields(body.incident, Incident)
    inc_data["impact_at"] = parse_dt(inc_data.get("impact_at"))
    incident = Incident(**inc_data)
    consciousness = Consciousness(**filter_fields(body.consciousness, Consciousness))
    symptoms = Symptoms(**filter_fields(body.symptoms, Symptoms))
    pupils = PupilExam(**filter_fields(body.pupils, PupilExam)) if body.pupils else PupilExam()

    result = run_triage(profile, incident, consciousness, symptoms, pupils=pupils)

    incident_dict = dict(body.incident) | {"impact_at": inc_data["impact_at"].isoformat(timespec="seconds") if inc_data["impact_at"] else None}
    incident_id = db.create_incident(
        filter_fields(body.profile, Profile) | {"age": profile.age},
        incident_dict, symptoms.__dict__, consciousness.__dict__,
        pupils.__dict__ if body.pupils else None, result.to_dict(),
    )
    plan = schedule_followup(incident_id, result.level)
    return {"id": incident_id, "triage": result.to_dict(), "followup_plan": plan}


@app.get("/api/incidents")
def list_incidents():
    return db.list_incidents()


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: int):
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident introuvable")
    inc["exams"] = db.list_exams(incident_id)
    inc["tasks"] = db.list_tasks(incident_id)
    return inc


@app.post("/api/incidents/{incident_id}/recheck")
async def recheck(incident_id: int, body: RecheckIn):
    """Réponse à un re-contrôle automatique → réévaluation + comparaison.

    LE point clé du suivi 72 h : on repasse le moteur de triage avec les
    symptômes À JOUR et le verdict précédent → la détection d'aggravation
    peut escalader automatiquement (ex : jaune → orange)."""
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident introuvable")

    old_level = (inc.get("triage") or {}).get("level", "green")
    merged = dict(inc.get("symptoms") or {})
    merged.update(filter_fields(body.symptoms, Symptoms))
    symptoms = Symptoms(**merged)
    pupils_data = body.pupils or inc.get("pupils") or {}
    pupils = PupilExam(**filter_fields(pupils_data, PupilExam))
    profile = Profile(**filter_fields(inc.get("profile") or {}, Profile))
    inc_data = filter_fields(inc.get("incident") or {}, Incident)
    inc_data["impact_at"] = parse_dt(inc_data.get("impact_at"))
    incident = Incident(**inc_data)
    consciousness = Consciousness(**filter_fields(inc.get("consciousness") or {}, Consciousness))
    nirs = _latest_nirs(incident_id)

    result = run_triage(profile, incident, consciousness, symptoms,
                        nirs=nirs, pupils=pupils, previous=inc.get("triage"))
    db.update_incident_triage(incident_id, symptoms.__dict__, result.to_dict())

    escalated = result.level != old_level and result.worsening
    if escalated:
        # Alerte immédiate via WebSocket (l'endpoint est async → on peut diffuser
        # directement) + trace persistante en base pour le rapport.
        from app.scheduler import planify_hours
        db.add_task(incident_id, "escalation_alert",
                    (datetime.now(timezone.utc) + timedelta(seconds=planify_hours(0.01))).isoformat(timespec="seconds"),
                    {"level": result.level, "message": f"AGGRAVATION détectée → niveau {result.level}"})
        await broadcast({
            "type": "escalation_alert", "incident_id": incident_id,
            "level": result.level, "message": f"Aggravation détectée : niveau {result.level}"})

    return {"triage": result.to_dict(), "previous_level": old_level, "escalated": escalated}


def _latest_nirs(incident_id: int) -> NirsExam:
    """Reprend les mesures NIRS du dernier examen (un re-contrôle par chat ne
    refait pas la mesure : on réutilise la dernière connue — c'est médicalement
    correct : l'examen objectif reste valable quelques heures)."""
    exams = db.list_exams(incident_id)
    if not exams:
        return NirsExam()
    return NirsExam(measurements=exams[-1]["nirs"].get("measurements", []))


@app.post("/api/incidents/{incident_id}/exam")
async def run_exam(incident_id: int, body: ExamIn):
    """Examen du crâne : soit mesures du vrai bandeau (`measurements`),
    soit scénario du simulateur → analyse NIRS → verdict combiné."""
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident introuvable")

    if body.measurements:
        frames = [{"type": "nir", **m} for m in body.measurements]
        source = body.source
    else:
        device = VirtualCraniCap(scenario=body.scenario)
        frames = [f async for f in device.stream_exam()]
        source = "simulateur"

    measurements = VirtualCraniCap.measurements_from_frames(frames)
    profile = Profile(**filter_fields(inc.get("profile") or {}, Profile))
    inc_data = filter_fields(inc.get("incident") or {}, Incident)
    inc_data["impact_at"] = parse_dt(inc_data.get("impact_at"))
    incident = Incident(**inc_data)
    consciousness = Consciousness(**filter_fields(inc.get("consciousness") or {}, Consciousness))
    symptoms = Symptoms(**filter_fields(inc.get("symptoms") or {}, Symptoms))
    pupils_data = body.pupils or inc.get("pupils") or {}
    pupils = PupilExam(**filter_fields(pupils_data, PupilExam))

    nirs = NirsExam(measurements=measurements)
    # Le verdict précédent n'est PAS passé : un examen NIRS est une évaluation
    # fraîche et objective (l'aggravation se calcule entre analyses NIRS).
    result = run_triage(profile, incident, consciousness, symptoms,
                        nirs=nirs, pupils=pupils, previous=inc.get("triage"))
    analysis = result.nirs_analysis
    db.add_exam(incident_id, source, {"measurements": measurements}, analysis, result.level)
    db.update_incident_triage(incident_id, symptoms.__dict__, result.to_dict())

    imu = VirtualCraniCap.imu_event(frames)
    return {"triage": result.to_dict(), "analysis": analysis, "imu": imu,
            "frames": frames, "source": source}


@app.get("/api/incidents/{incident_id}/exams")
def get_exams(incident_id: int):
    return db.list_exams(incident_id)


@app.post("/api/chat")
def chat(body: ChatIn):
    """Conversation avec Naya. Chaque message et chaque conseil sont journalisés
    (auditabilité médicale : on peut toujours expliquer ce que l'IA a dit)."""
    context: Dict[str, Any] = {"contacts": db.get_contacts()}
    if body.incident_id:
        inc = db.get_incident(body.incident_id)
        if inc:
            context.update({
                "active_incident": True,
                "profile": inc.get("profile"),
                "incident": inc.get("incident"),
                "symptoms": inc.get("symptoms"),
                "consciousness": inc.get("consciousness"),
                "pupils": inc.get("pupils"),
                "previous_triage": inc.get("triage"),
            })
    user_msg_id = db.add_message(body.session, "user", body.message,
                                 incident_id=body.incident_id)
    reply = naya.answer(body.message, context)
    db.add_message(body.session, "assistant", reply["reply"],
                   incident_id=body.incident_id, meta={
                       "action": reply.get("action"), "severity": reply.get("severity"),
                       "quick_replies": reply.get("quick_replies")})
    return {"user_msg_id": user_msg_id, **reply}


@app.get("/api/messages/{session}")
def get_messages(session: str):
    return db.list_messages(session)


@app.get("/api/tasks")
def get_tasks(incident_id: Optional[int] = None):
    return db.list_tasks(incident_id)


@app.get("/api/contacts")
def get_contacts():
    return db.get_contacts()


@app.post("/api/contacts")
def set_contacts(body: ContactsIn):
    db.set_contacts(body.contacts)
    return {"ok": True, "count": len(body.contacts)}


@app.get("/api/incidents/{incident_id}/report", response_class=HTMLResponse)
def report(incident_id: int):
    """Rapport HTML imprimable (Ctrl+P → PDF) à montrer au médecin/infirmier.
    C'est le pont CrâniScan → système de santé : le professionnel reçoit une
    chronologie complète qu'il n'a PAS à reconstruire."""
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident introuvable")
    exams = db.list_exams(incident_id)
    tasks = db.list_tasks(incident_id)
    triage = inc.get("triage") or {}
    profile = inc.get("profile") or {}
    level_colors = {"red": "#d32f2f", "orange": "#ef6c00", "yellow": "#f9a825", "green": "#2e7d32"}
    level_names = {"red": "URGENCE (rouge)", "orange": "CONSULTATION SOUS 24 H (orange)",
                   "yellow": "SURVEILLANCE STRICTE (jaune)", "green": "SURVEILLANCE STANDARD (vert)"}

    exam_rows = "".join(
        f"<tr><td>{e['created_at']}</td><td>{e['source']}</td>"
        f"<td>ΔOD max {e['analysis'].get('max_dod', 0):.2f}</td>"
        f"<td>{e.get('verdict_level') or '—'}</td></tr>"
        for e in exams
    ) or "<tr><td colspan=4>aucun examen d'enregistré</td></tr>"

    reasons_html = "".join(f"<li>{r}</li>" for r in triage.get("reasons", []))
    tasks_html = "".join(
        f"<li>{t['type']} — échéance {t['due_at']} — statut {t['status']}</li>"
        for t in tasks
    ) or "<li>aucune tâche</li>"

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>CrâniScan — Rapport d'incident #{incident_id}</title>
<style>
 body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #222; }}
 h1 {{ color: #0d47a1; border-bottom: 3px solid #0d47a1; padding-bottom: 8px; }}
 .badge {{ display: inline-block; color: #fff; padding: 6px 14px; border-radius: 20px;
          font-weight: bold; background: {level_colors.get(triage.get('level'), '#666')}; }}
 table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
 td, th {{ border: 1px solid #bbb; padding: 6px 10px; text-align: left; font-size: 14px; }}
 th {{ background: #e3f2fd; }}
 .warn {{ background: #fff3e0; border-left: 5px solid #ef6c00; padding: 10px 14px; }}
</style></head><body>
<h1>CrâniScan — Rapport d'incident #{incident_id}</h1>
<p><b>Verdict :</b> <span class="badge">{level_names.get(triage.get('level'), triage.get('level'))}</span></p>
<p><b>Patient :</b> âge {profile.get('age', '?')}
 {('— anticoagulants' if profile.get('anticoagulants') else '')}
 {('— épilepsie' if profile.get('epilepsy') else '')}</p>
<p><b>Choc :</b> {inc.get('incident', {}).get('impact_at') or 'heure inconnue'} —
 mécanismes : {', '.join(inc.get('incident', {}).get('mechanisms') or ['non renseignés'])}</p>
<p><b>Consigne :</b> {triage.get('advice', '')}</p>
<h2>Raisons du verdict</h2><ul>{reasons_html}</ul>
<h2>Examens du crâne (NIRS)</h2>
<table><tr><th>Date</th><th>Source</th><th>Asymétrie max (ΔOD)</th><th>Verdict</th></tr>{exam_rows}</table>
<h2>Suivi automatique</h2><ul>{tasks_html}</ul>
<div class="warn"><b>Avertissement :</b> CrâniScan est un outil d'aide à l'orientation
({triage.get('engine_version', '')}). Il ne remplace ni un médecin, ni un scanner X.
En cas d'aggravation, appeler les secours immédiatement.</div>
</body></html>"""
