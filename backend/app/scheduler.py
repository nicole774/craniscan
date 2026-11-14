# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — PLANIFICATEUR DE TÂCHES AUTOMATIQUES
===============================================================================
C'est le module qui rend CrâniScan « vivant » : après un verdict, il programme
les re-contrôles à 2 h / 6 h / 24 h / 48 h / 72 h, et exécute les tâches quand
leur heure arrive — même si le téléphone du patient est en veille.

COMMENT ÇA MARCHE (architecture) :
  - un thread d'arrière-plan (daemon) se réveille toutes les 20 secondes ;
  - il demande à la base : « quelles tâches pending sont dues ? » ;
  - pour chaque tâche, il produit un ÉVÉNEMENT (dict) et le pousse dans le
    canal de diffusion (WebSocket) que main.py lui a fourni ;
  - l'app reçoit l'événement et affiche la notification / le questionnaire.

Pourquoi un thread et pas APScheduler/celery ?
  - une dépendance de moins = moins de risques d'installation sur un
    Raspberry Pi de dispensaire ;
  - la logique tient en ~60 lignes lisibles et testables ;
  - l'état durable vit dans SQLite (les tâches survivent au redémarrage) —
    c'est le point faible des planificateurs en mémoire.

ÉVÉNEMENTS ÉMIS (reçus par l'app via WebSocket /ws/events) :
  {"type":"recheck_due",  ...}   → affiche le questionnaire de re-contrôle
  {"type":"reminder",     ...}   → rappel des signes d'alerte
  {"type":"missed_check", ...}   → pas de réponse au re-contrôle → alerte
  {"type":"summary",      ...}   → bilan de fin de surveillance
===============================================================================
"""

import asyncio
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app import db

LOOP_PERIOD_S = 20
"""Le planificateur se réveille toutes les 20 s. Pour la DÉMONSTRATION, la
variable d'environnement CRANISCAN_FAST_SCHED=1 réduit les échéances
(multiplie les heures de suivi par des secondes) — voir planify()."""

FAST_SCHED = False  # réglé par main.py au démarrage


def planify_hours(hours: float) -> float:
    """En mode démo : 1 heure de suivi → 30 secondes réelles. Permet de
    démontrer TOUT le cycle 72 h en quelques minutes devant un jury. En
    production, retourne les heures telles quelles."""
    if FAST_SCHED:
        return hours * 30 / 3600  # 1 h → 30 s
    return hours


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def schedule_followup(incident_id: int, level: str, base: Optional[datetime] = None) -> list:
    """Crée les tâches de surveillance d'un incident selon son niveau.
    Retourne la liste des échéances créées (utile pour l'app/les tests)."""
    from app.triage import FOLLOWUP_PLANS
    base = base or _now()
    created = []
    for h in FOLLOWUP_PLANS.get(level, []):
        due = base + timedelta(hours=planify_hours(h))
        task_id = db.add_task(incident_id, "recheck", _iso(due), {
            "hours": h,
            "level": level,
            "message": f"Re-contrôle H+{h} : comment vous sentez-vous ?",
        })
        created.append({"task_id": task_id, "hours": h, "due_at": _iso(due)})
    # Rappel éducation H+1 (signes d'alerte) et bilan de fin de surveillance.
    db.add_task(incident_id, "reminder", _iso(base + timedelta(hours=planify_hours(1))), {
        "message": "Petit rappel : gardez les signes d'alerte en tête pendant 72 h."})
    summary_hours = 72 if level in ("yellow", "green") else 24
    db.add_task(incident_id, "summary", _iso(base + timedelta(hours=planify_hours(summary_hours))), {
        "message": "Bilan de fin de surveillance (72 h) — que faire si les symptômes reviennent ?"})
    return created


class Scheduler:
    """Boucle d'arrière-plan qui exécute les tâches automatiques."""

    def __init__(self, broadcast: Optional[Callable] = None):
        self.broadcast = broadcast      # coroutine async (émet vers WebSocket)
        self.loop: Optional[asyncio.AbstractEventLoop] = None  # boucle de main.py
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._thread = threading.Thread(target=self._run, name="craniscan-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------------------- moteur
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                traceback.print_exc()  # le planificateur ne doit JAMAIS mourir
            self._stop.wait(LOOP_PERIOD_S)

    def _tick(self) -> None:
        now_iso = _iso(_now())
        for task in db.due_tasks(now_iso):
            self._execute(task)

    def _execute(self, task: dict) -> None:
        payload = task.get("payload") or {}
        event = {"task_id": task["id"], "incident_id": task["incident_id"]}

        if task["type"] == "recheck":
            db.set_task_status(task["id"], "done")
            event.update({"type": "recheck_due", **payload})
            # Alerte « pas de réponse » programmée à H+15 min du re-contrôle —
            # uniquement pour les niveaux à risque (≥ jaune) : on n'embête pas
            # un patient vert avec des alertes de contacts d'urgence.
            if payload.get("level") in ("yellow", "orange", "red"):
                due = _now() + timedelta(seconds=planify_hours(0.25))
                db.add_task(task["incident_id"], "missed_check", _iso(due), {
                    "recheck_task_id": task["id"], **payload})

        elif task["type"] == "missed_check":
            # Le re-contrôle correspondant a-t-il été répondu ?
            answered = self._recheck_answered(task)
            db.set_task_status(task["id"], "done")
            if not answered:
                event.update({"type": "missed_check", **payload,
                              "message": "Re-contrôle sans réponse — alerte des contacts d'urgence."})

        elif task["type"] == "reminder":
            db.set_task_status(task["id"], "done")
            event.update({"type": "reminder", **payload})

        elif task["type"] == "escalation_alert":
            db.set_task_status(task["id"], "done")
            event.update({"type": "escalation_alert", **payload})

        elif task["type"] == "summary":
            db.set_task_status(task["id"], "done")
            db.set_incident_status(task["incident_id"], "cloture")
            event.update({"type": "summary", **payload})

        else:
            return  # type inconnu : on ne bloque pas la boucle

        self._emit(event)

    def _recheck_answered(self, missed_task: dict) -> bool:
        """Un re-contrôle est « répondu » si un examen/questionnaire postérieur
        a été enregistré pour l'incident après l'émission du re-contrôle.
        Implémentation simple : l'API met status='hospitalise'|'cloture' ou
        ajoute un examen ; on vérifie la date du dernier examen."""
        inc = db.get_incident(missed_task["incident_id"])
        if not inc:
            return True  # incident disparu → rien à alerter
        exams = db.list_exams(missed_task["incident_id"])
        if not exams:
            return False
        last = max(e["created_at"] for e in exams)
        return last >= inc["created_at"]

    def _emit(self, event: dict) -> None:
        """Pousse l'événement vers les clients WebSocket (app mobile).
        Pont thread → asyncio : run_coroutine_threadsafe est LA façon sûre
        de parler à une boucle asyncio depuis un thread classique."""
        if self.broadcast and self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(event), self.loop)
