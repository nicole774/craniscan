# -*- coding: utf-8 -*-
"""
===============================================================================
Tests unitaires du MOTEUR DE TRIAGE — la ceinture de sécurité médicale.
===============================================================================
Chaque test = un SCÉNARIO CLINIQUE. Si un jour on modifie une règle et qu'un
test casse, on sait immédiatement quel type de patient est affecté.

Lancement :   cd backend && python -m pytest tests/ -v
===============================================================================
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.triage import (  # noqa: E402
    Consciousness,
    Incident,
    NirsExam,
    Profile,
    PupilExam,
    Symptoms,
    promote,
    run_triage,
)


# -----------------------------------------------------------------------------
# Petits outils de fabrication des scénarios
# -----------------------------------------------------------------------------

def nirs_measurements(asym_by_pair: dict) -> list:
    """Fabrique des mesures NIRS à partir de {paire: ΔOD}.

    Pour chaque paire : LED 760 nm et 850 nm avec la même asymétrie (cas
    réaliste d'un hématome : les deux longueurs d'onde concordent).
    """
    out = []
    for pair, dod in asym_by_pair.items():
        for led in (760, 850):
            out += [
                {"pair": pair, "led": led, "side": "L", "od": 0.40 + dod / 2},
                {"pair": pair, "led": led, "side": "R", "od": 0.40 - dod / 2},
            ]
    return out


def triage(symptoms: Symptoms = None, profile: Profile = None,
           consciousness: Consciousness = None, incident: Incident = None,
           nirs: NirsExam = None, pupils: PupilExam = None, previous=None):
    """Lance run_triage avec des valeurs par défaut « personne saine de 30 ans »."""
    return run_triage(
        profile or Profile(age=30),
        incident or Incident(mechanisms=["other"]),
        consciousness or Consciousness(awake_normal=True),
        symptoms or Symptoms(),
        nirs=nirs, pupils=pupils, previous=previous,
    )


# -----------------------------------------------------------------------------
# 1. Cas vert : rien de grave
# -----------------------------------------------------------------------------

def test_personne_saine_est_verte():
    """Adulte 30 ans, GCS 15, aucun symptôme → surveillance verte."""
    r = triage()
    assert r.level == "green"
    assert r.destination == "maison_surveillance"


def test_gcs_calcul_depuis_composants():
    """GCS = yeux(3) + verbal(4) + moteur(6) = 13 → TCC léger, pas de drapeau rouge."""
    c = Consciousness(eyes=3, verbal=4, motor=6)
    assert c.gcs == 13


def test_gcs_raccourci_patient_conscient():
    """Patient seul, conscient et normal : le questionnaire utilise le raccourci GCS=15."""
    c = Consciousness(awake_normal=True)
    assert c.gcs == 15


# -----------------------------------------------------------------------------
# 2. Drapeaux rouges → 🔴 urgence immédiate
# -----------------------------------------------------------------------------

def test_gcs_12_est_rouge():
    """GCS ≤ 12 = traumatisme modéré/sévère → urgences."""
    r = triage(consciousness=Consciousness(eyes=2, verbal=3, motor=5))  # GCS 10
    assert r.level == "red"
    assert any("GCS" in x for x in r.reasons)


def test_convulsion_est_rouge():
    r = triage(symptoms=Symptoms(seizure=True))
    assert r.level == "red"


def test_signe_basilaire_est_rouge():
    """Écoulement de liquide clair (LCR) = fracture basilaire suspectée → rouge."""
    r = triage(symptoms=Symptoms(csf_leak=True))
    assert r.level == "red"
    assert any("fracture basilaire" in x for x in r.reasons)


def test_pupilles_inegales_sont_rouges():
    """Anisocorie 2 mm (non connue) = compression cérébrale possible → rouge."""
    r = triage(pupils=PupilExam(left_mm=4.0, right_mm=2.0))
    assert r.level == "red"
    assert any("pupilles" in x for x in r.reasons)


def test_anisocorie_connue_ne_declenche_pas_rouge():
    """Personne qui a TOUJOURS eu des pupilles inégales : pas de fausse alerte."""
    r = triage(pupils=PupilExam(left_mm=4.0, right_mm=2.0, known_anisocoria=True))
    assert r.level == "green"


def test_deficit_moteur_est_rouge():
    r = triage(symptoms=Symptoms(motor_deficit=True))
    assert r.level == "red"


# -----------------------------------------------------------------------------
# 3. NIRS : détection d'hématome par asymétrie optique
# -----------------------------------------------------------------------------

def test_nirs_asymetrie_majeure_est_rouge():
    """ΔOD = 0.35 sur la paire temporale, concordant sur 760 ET 850 nm → rouge."""
    exam = NirsExam(measurements=nirs_measurements({1: 0.35, 3: 0.02}))
    r = triage(nirs=exam)
    assert r.level == "red"
    assert "NIRS_asymétrie" in r.rules_hit
    assert r.nirs_analysis["max_dod"] >= 0.30


def test_nirs_asymetrie_moderee_est_jaune():
    """ΔOD = 0.20 : zone intermédiaire (0.10–0.30) → surveillance + contrôle."""
    exam = NirsExam(measurements=nirs_measurements({2: 0.20, 4: 0.05}))
    r = triage(nirs=exam)
    assert r.level == "yellow"
    assert any("asymétrie modérée" in x for x in r.reasons)


def test_nirs_symetrique_ne_change_pas_verdict():
    """Examen parfaitement symétrique (ΔOD ≈ 0) sur personne saine → toujours vert."""
    exam = NirsExam(measurements=nirs_measurements({1: 0.01, 2: 0.02, 3: 0.01, 4: 0.02}))
    r = triage(nirs=exam)
    assert r.level == "green"
    assert r.nirs_analysis["valid"] is True


def test_nirs_incomplet_est_signale():
    """Une seule paire mesurée = examen invalide → on ne se prononce PAS sur le NIRS."""
    exam = NirsExam(measurements=nirs_measurements({1: 0.0}))
    r = triage(nirs=exam)
    assert r.nirs_analysis["valid"] is False


# -----------------------------------------------------------------------------
# 4. Règle canadienne du TCC (adultes GCS 13–15)
# -----------------------------------------------------------------------------

def test_cchr_vomissements_2_fois_orange():
    """Critère HAUT RISQUE : vomissements ≥ 2 → scanner nécessaire aujourd'hui."""
    r = triage(symptoms=Symptoms(vomiting_count=2))
    assert r.level == "orange"
    assert r.destination == "hopital_aujourdhui"
    assert any("vomissements" in x for x in r.reasons)


def test_cchr_age_65_orange():
    """Critère haut risque : âge ≥ 65 ans, même sans symptôme."""
    r = triage(profile=Profile(age=70))
    assert r.level == "orange"
    assert any("65" in x for x in r.reasons)


def test_cchr_mecanisme_dangereux_orange():
    """Piéton renversé = mécanisme dangereux → risque intermédiaire → consultation."""
    r = triage(incident=Incident(mechanisms=["pedestrian_struck"]))
    assert r.level == "orange"
    assert any("mécanisme dangereux" in x for x in r.reasons)


def test_cchr_gcs_14_a_2h_orange():
    """GCS < 15 à plus de 2 h du choc = critère haut risque de la règle."""
    incident = Incident(
        impact_at=datetime.now(timezone.utc) - timedelta(hours=3),
        mechanisms=["other"],
    )
    r = triage(incident=incident, consciousness=Consciousness(eyes=4, verbal=4, motor=6))
    assert r.level == "orange"


def test_amnesie_30min_orange():
    r = triage(symptoms=Symptoms(amnesia_minutes=45))
    assert r.level == "orange"


def test_anticoagulants_meme_sans_symptome_consultation():
    """Patient sous anticoagulants, GCS 15, zéro symptôme : JAMAIS vert après un
    choc (risque hémorragique) → consultation systématique."""
    r = triage(profile=Profile(age=30, anticoagulants=True))
    assert r.level in ("orange", "yellow")
    assert r.level != "green"


# -----------------------------------------------------------------------------
# 5. New Orleans (GCS = 15) et symptômes isolés
# -----------------------------------------------------------------------------

def test_nola_cephalee_orange():
    r = triage(symptoms=Symptoms(headache=5))
    assert r.level == "orange"
    assert any("New Orleans" in x for x in r.reasons)


def test_cephalee_legere_jaune():
    """Simple céphalée légère (2/10) sans autre critère → surveillance jaune."""
    r = triage(symptoms=Symptoms(headache=2))
    assert r.level == "yellow"


def test_bosse_cuir_chevelu_jaune():
    r = triage(symptoms=Symptoms(scalp_hematoma=True))
    assert r.level == "yellow"


# -----------------------------------------------------------------------------
# 6. Enfants — PECARN (adaptation simplifiée)
# -----------------------------------------------------------------------------

def test_enfant_mecanisme_severe_orange():
    """Enfant renversé en vélo par une voiture → PECARN haut risque."""
    r = triage(
        profile=Profile(age=8),
        incident=Incident(mechanisms=["pedestrian_struck"]),
    )
    assert r.level == "orange"
    assert r.destination == "hopital_aujourdhui"
    assert "PECARN_(adaptation_pédiatrique)" in r.rules_hit


def test_enfant_vomissement_unique_jaune():
    """Enfant qui vomit une fois, conscience normale → observation (jaune)."""
    r = triage(
        profile=Profile(age=6),
        symptoms=Symptoms(vomiting_count=1),
        incident=Incident(mechanisms=["sport_impact"]),
    )
    assert r.level == "yellow"


# -----------------------------------------------------------------------------
# 7. Détection d'aggravation (trajectoire entre deux évaluations)
# -----------------------------------------------------------------------------

def previous_eval(symptoms: Symptoms, level="yellow"):
    """Fabrique une « évaluation précédente » stockée (format de la base)."""
    prev = triage(symptoms=symptoms)
    prev.level = level  # on simule le verdict précédent
    return {
        "level": level,
        "symptoms": symptoms.__dict__.copy(),
        "nirs_analysis": {"max_dod": 0.0},
        "pupil_analysis": {"anisocoria_mm": None},
    }


def test_nouveau_vomissement_escalade():
    """H+2 : patient jaune (céphalée légère). Au re-contrôle il vomit →
    aggravation → escalade d'un cran (orange) + marquage worsening."""
    prev = previous_eval(Symptoms(headache=3), level="yellow")
    r = triage(symptoms=Symptoms(headache=3, vomiting_count=1), previous=prev)
    assert r.worsening is True
    assert r.escalated_from == "yellow"
    assert r.level == "orange"
    assert any("vomissement" in x for x in r.reasons)


def test_cephalee_en_hausse_escalade():
    prev = previous_eval(Symptoms(headache=2), level="green")
    r = triage(symptoms=Symptoms(headache=7), previous=prev)
    assert r.worsening is True
    assert r.level != "green"


def test_amelioration_pas_escalade():
    """Symptômes identiques ou en baisse → pas de fausse escalade."""
    prev = previous_eval(Symptoms(headache=5), level="yellow")
    r = triage(symptoms=Symptoms(headache=1), previous=prev)
    assert r.worsening is False


def test_asymetrie_nirs_en_hausse_escalade():
    prev = previous_eval(Symptoms(headache=2), level="yellow")
    prev["nirs_analysis"]["max_dod"] = 0.10
    exam = NirsExam(measurements=nirs_measurements({1: 0.25, 3: 0.04}))
    r = triage(symptoms=Symptoms(headache=2), nirs=exam, previous=prev)
    assert r.worsening is True
    assert any("NIRS" in x for x in r.reasons)


# -----------------------------------------------------------------------------
# 8. Structure et invariants du résultat
# -----------------------------------------------------------------------------

def test_structure_completes_du_resultat():
    """Tout verdict doit être traçable : raisons, règles, plan de suivi, version."""
    r = triage(symptoms=Symptoms(vomiting_count=3))
    d = r.to_dict()
    for key in ("level", "reasons", "advice", "destination", "confidence",
                "rules_hit", "nirs_analysis", "pupil_analysis", "followup_hours",
                "engine_version", "disclaimer"):
        assert key in d, f"champ manquant : {key}"
    assert r.followup_hours == [2, 6, 24]  # plan orange


def test_niveau_toujours_defini():
    """Invariant : le niveau appartient TOUJOURS aux 4 niveaux autorisés."""
    for s in (Symptoms(), Symptoms(headache=9), Symptoms(seizure=True)):
        assert triage(symptoms=s).level in ("green", "yellow", "orange", "red")


def test_promote_ne_depasse_pas_rouge():
    """promote('red') reste 'red' (pas de niveau au-delà)."""
    assert promote("yellow") == "orange"
    assert promote("red") == "red"
    assert promote("green", 3) == "red"
