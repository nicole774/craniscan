# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — COUCHE DONNÉES (SQLite)
===============================================================================
Pourquoi SQLite et pas PostgreSQL/MySQL ?
  - une base SQLite = UN FICHIER sur disque : aucune installation, aucune
    administration. On peut le copier sur une clé USB, le poser sur un
    Raspberry Pi dans un dispensaire sans internet.
  - en production, si des milliers de dispensaires se connectent en même
    temps, on migrera vers PostgreSQL — le reste du code ne changera pas
    car tout passe par CE module (principe d'encapsulation : une seule
    couche connaît la base).

Pourquoi stocker les objets complexes en JSON (TEXT) ?
  - les entrées du triage (symptômes, mesures NIRS) évoluent vite pendant la
    conception. Le JSON garde la flexibilité sans migration de schéma à
    chaque ajout de champ. Les champs utilisés pour les RECHERCHES
    (niveau, échéance des tâches) restent en colonnes indexables.

Leçon importante : `with conn:` en sqlite3 COMMITE mais ne FERME PAS la
connexion. D'où le contextmanager ci-dessous qui fait les deux — sinon on
laisse fuir des connexions à chaque requête.
===============================================================================
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get(
    "CRANISCAN_DB",
    os.path.join(os.path.dirname(__file__), "..", "data", "craniscan.db"),
)

_lock = threading.Lock()
"""SQLite accepte plusieurs lecteurs mais UN SEUL écrivain à la fois. FastAPI
exécute les requêtes dans un pool de threads → un verrou Python sérialise les
écritures (simple et suffisant à l'échelle d'un dispensaire)."""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # écritures sans bloquer les lectures
    return conn


@contextmanager
def _db():
    """Ouvre une connexion, commite si tout va bien, referme TOUJOURS."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    """Crée les tables si elles n'existent pas (idempotent : peut être appelé
    plusieurs fois sans effet de bord)."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _lock, _db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                impact_at   TEXT,
                level       TEXT,            -- dernier verdict : green/yellow/orange/red
                status      TEXT DEFAULT 'surveillance', -- surveillance|hospitalise|cloture
                profile     TEXT NOT NULL,   -- JSON Profile
                incident    TEXT NOT NULL,   -- JSON Incident (mécanisme, heure du choc)
                symptoms    TEXT NOT NULL,   -- JSON Symptoms (dernier questionnaire)
                consciousness TEXT NOT NULL, -- JSON Consciousness (GCS)
                pupils      TEXT,            -- JSON PupilExam
                triage      TEXT NOT NULL    -- JSON TriageResult complet
            );

            CREATE TABLE IF NOT EXISTS exams (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id   INTEGER NOT NULL REFERENCES incidents(id),
                created_at    TEXT NOT NULL,
                source        TEXT NOT NULL, -- bandeau | simulateur | sans_capteur
                nirs          TEXT NOT NULL, -- JSON mesures brutes
                analysis      TEXT NOT NULL, -- JSON analyse (ΔOD, paires suspectes)
                verdict_level TEXT           -- niveau combiné après cet examen
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER REFERENCES incidents(id),
                type        TEXT NOT NULL,   -- recheck | alert | reminder | summary | escalation
                due_at      TEXT NOT NULL,   -- ISO datetime : quand la tâche doit s'exécuter
                status      TEXT DEFAULT 'pending', -- pending|done|missed|cancelled
                payload     TEXT,            -- JSON libre (questionnaire, message…)
                done_at     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at);

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER REFERENCES incidents(id),
                session     TEXT NOT NULL,   -- identifiant de conversation
                role        TEXT NOT NULL,   -- user | assistant
                text        TEXT NOT NULL,
                meta        TEXT,            -- JSON (action déclenchée, sévérité…)
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                phone    TEXT NOT NULL,
                relation TEXT
            );
            """
        )


# -----------------------------------------------------------------------------
# Incidents (une « affaire » de traumatisme crânien = un suivi complet)
# -----------------------------------------------------------------------------

def create_incident(profile: dict, incident: dict, symptoms: dict,
                    consciousness: dict, pupils: Optional[dict], triage: dict) -> int:
    with _lock, _db() as c:
        cur = c.execute(
            """INSERT INTO incidents
               (created_at, impact_at, level, profile, incident, symptoms,
                consciousness, pupils, triage)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_now(), incident.get("impact_at"), triage["level"],
             json.dumps(profile, ensure_ascii=False),
             json.dumps(incident, ensure_ascii=False),
             json.dumps(symptoms, ensure_ascii=False),
             json.dumps(consciousness, ensure_ascii=False),
             json.dumps(pupils, ensure_ascii=False) if pupils else None,
             json.dumps(triage, ensure_ascii=False)),
        )
        return cur.lastrowid


def update_incident_triage(incident_id: int, symptoms: dict, triage: dict) -> None:
    """Après un re-contrôle : met à jour le dernier état connu de l'incident."""
    with _lock, _db() as c:
        c.execute(
            "UPDATE incidents SET symptoms=?, triage=?, level=? WHERE id=?",
            (json.dumps(symptoms, ensure_ascii=False),
             json.dumps(triage, ensure_ascii=False),
             triage["level"], incident_id),
        )


def set_incident_status(incident_id: int, status: str) -> None:
    with _lock, _db() as c:
        c.execute("UPDATE incidents SET status=? WHERE id=?", (status, incident_id))


def _incident_from_row(row) -> dict:
    d = dict(row)
    for key in ("profile", "incident", "symptoms", "consciousness", "pupils", "triage"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def get_incident(incident_id: int) -> Optional[dict]:
    with _db() as c:
        row = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return _incident_from_row(row) if row else None


def list_incidents(limit: int = 50) -> list:
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_incident_from_row(r) for r in rows]


# -----------------------------------------------------------------------------
# Examens (NIRS / pupilles) — l'historique objectif des mesures
# -----------------------------------------------------------------------------

def add_exam(incident_id: int, source: str, nirs: dict, analysis: dict,
             verdict_level: Optional[str]) -> int:
    with _lock, _db() as c:
        cur = c.execute(
            """INSERT INTO exams (incident_id, created_at, source, nirs, analysis, verdict_level)
               VALUES (?,?,?,?,?,?)""",
            (incident_id, _now(), source,
             json.dumps(nirs, ensure_ascii=False),
             json.dumps(analysis, ensure_ascii=False), verdict_level),
        )
        return cur.lastrowid


def list_exams(incident_id: int) -> list:
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM exams WHERE incident_id=? ORDER BY id", (incident_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["nirs"] = json.loads(d["nirs"])
            d["analysis"] = json.loads(d["analysis"])
            out.append(d)
        return out


# -----------------------------------------------------------------------------
# Tâches automatiques (re-contrôles, alertes, rappels) — alimentées par le
# planificateur, consultées par l'app pour afficher la timeline de suivi.
# -----------------------------------------------------------------------------

def add_task(incident_id: Optional[int], type_: str, due_at_iso: str,
             payload: Optional[dict] = None) -> int:
    with _lock, _db() as c:
        cur = c.execute(
            "INSERT INTO tasks (incident_id, type, due_at, payload) VALUES (?,?,?,?)",
            (incident_id, type_, due_at_iso,
             json.dumps(payload, ensure_ascii=False) if payload else None),
        )
        return cur.lastrowid


def due_tasks(now_iso: str) -> list:
    """Tâches pending dont l'heure est venue — la requête centrale du
    planificateur : index (status, due_at) → recherche instantanée."""
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM tasks WHERE status='pending' AND due_at<=? ORDER BY due_at",
            (now_iso,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out


def set_task_status(task_id: int, status: str) -> None:
    assert status in ("pending", "done", "missed", "cancelled")
    with _lock, _db() as c:
        if status == "done":
            c.execute("UPDATE tasks SET status=?, done_at=? WHERE id=?",
                      (status, _now(), task_id))
        else:
            c.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))


def list_tasks(incident_id: Optional[int] = None) -> list:
    with _db() as c:
        if incident_id:
            rows = c.execute("SELECT * FROM tasks WHERE incident_id=? ORDER BY due_at",
                             (incident_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM tasks ORDER BY due_at LIMIT 200").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out


# -----------------------------------------------------------------------------
# Messages de l'assistant — chaque conseil est journalisé (auditabilité)
# -----------------------------------------------------------------------------

def add_message(session: str, role: str, text: str,
                incident_id: Optional[int] = None, meta: Optional[dict] = None) -> int:
    with _lock, _db() as c:
        cur = c.execute(
            "INSERT INTO messages (incident_id, session, role, text, meta, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (incident_id, session, role, text,
             json.dumps(meta, ensure_ascii=False) if meta else None, _now()),
        )
        return cur.lastrowid


def list_messages(session: str, limit: int = 100) -> list:
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
            (session, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# -----------------------------------------------------------------------------
# Contacts d'urgence — prévenus en cas de verdict rouge / non-réponse
# -----------------------------------------------------------------------------

def set_contacts(contacts: list) -> None:
    with _lock, _db() as c:
        c.execute("DELETE FROM contacts")
        for ct in contacts:
            c.execute("INSERT INTO contacts (name, phone, relation) VALUES (?,?,?)",
                      (ct.get("name", ""), ct.get("phone", ""), ct.get("relation", "")))


def get_contacts() -> list:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM contacts").fetchall()]
