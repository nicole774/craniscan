# -*- coding: utf-8 -*-
"""
===============================================================================
Tests d'INTÉGRATION de l'API CrâniScan — on teste le comportement RÉEL de
l'app : requêtes HTTP complètes contre le serveur FastAPI (TestClient).

Différence avec les tests unitaires :
  - test_triage.py teste le CERVEAU isolé (le moteur de triage) ;
  - test_api.py teste le corps ENTIER : API + base + assistant + planificateur.
C'est ce qu'on appelle la pyramide de tests : beaucoup de tests unitaires
rapides en base, quelques tests d'intégration réalistes au sommet.

Astuce utilisée : TestClient de FastAPI simule un client HTTP complet sans
ouvrir de port réseau — les tests restent rapides et ne peuvent pas entrer
en collision avec un serveur déjà lancé sur votre machine.
===============================================================================
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GREEN_BODY = {
    "profile": {"age": 30},
    "incident": {"impact_at": None, "mechanisms": ["sport_impact"]},
    "consciousness": {"awake_normal": True},
    "symptoms": {},
}


def client():
    # `with` déclenche le cycle de vie (init base + démarrage planificateur)
    return TestClient(app)


def test_health():
    with client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json()["service"] == "CrâniScan"


def test_incident_vert_avec_plan_de_suivi():
    """Incident sain → verdict vert + tâches de re-contrôle programmées."""
    with client() as c:
        r = c.post("/api/incidents", json=GREEN_BODY)
        assert r.status_code == 200
        data = r.json()
        assert data["triage"]["level"] == "green"
        assert data["followup_plan"], "le plan de surveillance doit être créé"
        # La base contient bien les tâches automatiques
        tasks = c.get(f"/api/tasks?incident_id={data['id']}").json()
        types = {t["type"] for t in tasks}
        assert "recheck" in types and "summary" in types


def test_incident_rouge_convulsion():
    body = dict(GREEN_BODY, symptoms={"seizure": True})
    with client() as c:
        r = c.post("/api/incidents", json=body)
        assert r.json()["triage"]["level"] == "red"


def test_recheck_aggravation_escalade():
    """Le cœur du suivi 72 h : un patient jaune qui vomit au re-contrôle
    est escaladé automatiquement jaune → orange."""
    yellow_body = dict(GREEN_BODY, symptoms={"headache": 2})
    with client() as c:
        inc_id = c.post("/api/incidents", json=yellow_body).json()["id"]
        r = c.post(f"/api/incidents/{inc_id}/recheck",
                   json={"symptoms": {"vomiting_count": 1}})
        data = r.json()
        assert data["escalated"] is True
        assert data["previous_level"] == "yellow"
        assert data["triage"]["level"] == "orange"
        assert data["triage"]["worsening"] is True


def test_exam_nirs_hematoma():
    """Examen du crâne en scénario hématome (simulateur) → verdict rouge."""
    with client() as c:
        inc_id = c.post("/api/incidents", json=GREEN_BODY).json()["id"]
        r = c.post(f"/api/incidents/{inc_id}/exam", json={"scenario": "hematoma"})
        data = r.json()
        assert data["triage"]["level"] == "red"
        assert data["analysis"]["max_dod"] >= 0.30
        assert len(data["frames"]) > 10, "les trames du capteur doivent être renvoyées"
        assert any(f["type"] == "nir" for f in data["frames"])


def test_exam_nirs_normal_reste_vert():
    with client() as c:
        inc_id = c.post("/api/incidents", json=GREEN_BODY).json()["id"]
        r = c.post(f"/api/incidents/{inc_id}/exam", json={"scenario": "normal"})
        assert r.json()["triage"]["level"] == "green"


def test_naya_drapeau_rouge_langage_naturel():
    """Naya détecte « convulsion » dans une phrase naturelle → escalade rouge."""
    with client() as c:
        r = c.post("/api/chat", json={
            "session": "s1", "message": "il a une convulsion depuis 2 minutes"})
        data = r.json()
        assert data["severity"] == "red"
        assert data["action"]["type"] == "call_emergency"


def test_naya_symptomes_reevalue():
    """Naya extrait « j'ai mal à la tête 8/10 » et réévalue avec le moteur."""
    with client() as c:
        inc_id = c.post("/api/incidents", json=GREEN_BODY).json()["id"]
        r = c.post("/api/chat", json={
            "session": "s2", "message": "j'ai mal à la tête 8/10", "incident_id": inc_id})
        data = r.json()
        assert data["severity"] in ("orange", "red")
        assert data["triage"]["level"] == data["severity"]


def test_naya_questions_courantes():
    with client() as c:
        r = c.post("/api/chat", json={"session": "s3", "message": "puis-je dormir ?"})
        assert "réveiller" in r.json()["reply"].lower()


def test_rapport_medical_html():
    """Le rapport pour le médecin doit exister et contenir les infos clés."""
    with client() as c:
        inc_id = c.post("/api/incidents", json=GREEN_BODY).json()["id"]
        r = c.get(f"/api/incidents/{inc_id}/report")
        assert r.status_code == 200
        assert "Rapport d'incident" in r.text
        assert "Avertissement" in r.text


def test_contacts():
    with client() as c:
        r = c.post("/api/contacts", json={"contacts": [
            {"name": "Marie", "phone": "+50912345678", "relation": "sœur"}]})
        assert r.json()["count"] == 1
        got = c.get("/api/contacts").json()
        assert got[0]["name"] == "Marie"
