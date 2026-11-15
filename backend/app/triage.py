# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — MOTEUR DE TRIAGE CLINIQUE
===============================================================================
C'est le CŒUR MÉDICAL du projet. Ce module est volontairement écrit en Python
pur (aucune dépendance) pour 3 raisons d'ingénierie :

  1. TESTABILITÉ  → chaque règle clinique est vérifiable par des tests unitaires
                    (pytest). Un moteur médical qui n'est pas testé est un
                    moteur dangereux.
  2. PORTABILITÉ  → le même code tourne sur le serveur FastAPI, sur un
                    Raspberry Pi dans un dispensaire, ou pourrait être porté
                    côté navigateur. Aucun framework ne nous enchaîne.
  3. AUDITABILITÉ → un médecin peut lire ce fichier ligne par ligne et vérifier
                    que les règles correspondent aux guidelines publiées.

RÈGLES IMPLÉMENTÉES (guidelines validées, pas d'invention médicale) :
  - Échelle de Glasgow (GCS)                          : état de conscience 3–15
  - Règle canadienne du TCC (Stiell et al., Lancet 2001) : sensibilité 100 %
    pour le besoin de neurochirurgie (critères haut risque).
  - New Orleans Criteria (GCS = 15)                   : sensibilité ~100 % CT.
  - PECARN (enfants < 18 ans) — ADAPTATION SIMPLIFIÉE  : standard pédiatrique.
  - Analyse NIRS (principe Infrascanner) : ΔOD asymétrique → suspicion hématome.
  - Pupillométrie : anisocorie → hypertension intracrânienne possible.
  - Détection d'aggravation (trajectoire) : comparaison avec l'évaluation
    précédente → escalade automatique.

NIVEAUX DE VERDICT (du moins au plus grave) :
  green < yellow < orange < red
===============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# -----------------------------------------------------------------------------
# Constantes
# -----------------------------------------------------------------------------

LEVEL_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
"""Les 4 niveaux de verdict, ordonnés du moins grave au plus grave.
Comparer deux niveaux = comparer leurs entiers."""

DISCLAIMER = (
    "CrâniScan est un outil d'AIDE À L'ORIENTATION. Il ne remplace ni un médecin, "
    "ni un scanner X. En cas de signes graves (inconscience, convulsion, vomissements "
    "répétés, aggravation), appelez les secours IMMÉDIATEMENT."
)

ENGINE_VERSION = "1.0.0"
"""Version du moteur. Chaque verdict la stocke → reproductibilité/audit."""


def promote(level: str, steps: int = 1) -> str:
    """Fait monter un niveau de gravité de `steps` crans (yellow → orange, etc.).

    Utilisé par la détection d'aggravation : si le patient va MIEUX ≠ verdict
    antérieur mais qu'un symptôme s'est aggravé, on escalade d'un cran.
    """
    ordered = ["green", "yellow", "orange", "red"]
    idx = ordered.index(level)
    return ordered[min(idx + steps, 3)]


# -----------------------------------------------------------------------------
# Structure des données d'entrée
# -----------------------------------------------------------------------------

@dataclass
class Profile:
    """Profil du patient. Rempli une fois, réutilisé à chaque évaluation."""
    age: int = 30
    anticoagulants: bool = False       # anticoagulants / trouble de coagulation
    epilepsy: bool = False             # épilepsie connue (contexte des convulsions)
    pregnancy: bool = False


@dataclass
class Incident:
    """L'accident lui-même. L'HEURE du choc est critique : plusieurs critères
    cliniques (« GCS < 15 à 2 h », « surveillance 24 h ») dépendent du délai."""
    impact_at: Optional[datetime] = None   # heure du choc (IMU si bandeau)
    mechanisms: List[str] = field(default_factory=list)
    # Mécanismes reconnus (alimentent « mécanisme dangereux » de la règle canadienne) :
    #   pedestrian_struck  : piéton renversé par un véhicule
    #   ejection           : éjection d'un véhicule
    #   road_accident      : accident de la route (véhicule occupé)
    #   fall_over_1m       : chute de plus de 1 mètre (~3 pieds)
    #   fall_stairs_5      : chute de plus de 5 marches d'escalier
    #   sport_impact       : impact sportif
    #   blunt_object       : coup d'objet contondant
    #   other              : autre choc
    g_force: Optional[float] = None        # force d'impact mesurée par l'IMU (g)

    def minutes_since_impact(self, now: Optional[datetime] = None) -> int:
        """Minutes écoulées depuis le choc. Retourne 0 si l'heure est inconnue
        (défaut conservateur : on considère que l'examen est fait « tout de suite »)."""
        if self.impact_at is None:
            return 0
        now = now or datetime.now(timezone.utc)
        ref = self.impact_at if self.impact_at.tzinfo else self.impact_at.replace(tzinfo=timezone.utc)
        return max(0, int((now - ref).total_seconds() // 60))


DANGEROUS_MECHANISMS = {
    "pedestrian_struck", "ejection", "road_accident", "fall_over_1m", "fall_stairs_5"
}
"""Mécanismes « dangereux » au sens de la règle canadienne du TCC (risque
intermédiaire → scanner recommandé)."""


@dataclass
class Symptoms:
    """Symptômes ACTUELS déclarés (par le patient ou l'observateur).

    Convention : les booléens True = « oui / présent ». Les entiers sont des
    échelles déclarées (douleur 0–10, somnolence 0–3).
    """
    # --- état de conscience -------------------------------------------------
    loc: bool = False                  # perte de connaissance pendant/après le choc
    loc_minutes: int = 0               # durée de cette perte de connaissance
    amnesia_minutes: int = 0           # amnésie (trou de mémoire) autour de l'impact
    confusion: bool = False            # désorientation, propos incohérents
    drowsiness: int = 0                # 0=normal, 1=somnolent mais réveillable,
                                       # 2=très difficile à réveiller, 3=irréveillable
    seizure: bool = False              # convulsion depuis le choc
    unconscious_now: bool = False      # inconscient EN CE MOMENT

    # --- symptômes classiques ------------------------------------------------
    vomiting_count: int = 0            # nombre de vomissements depuis le choc
    headache: int = 0                  # céphalée 0–10
    motor_deficit: bool = False        # faiblesse/engourdissement d'un membre
    double_vision: bool = False
    light_sensitivity: bool = False
    neck_pain: bool = False            # douleur cervicale (prudence immobilisation)

    # --- signes de fracture basilaire (critères HAUT RISQUE règle canadienne) --
    csf_leak: bool = False             # liquide clair (LCR) du nez/oreilles
    raccoon_eyes: bool = False         # ecchymoses péri-orbitaires « yeux de panda »
    battle_sign: bool = False          # ecchymose rétro-auriculaire (signe de Battle)
    hemotympanum: bool = False         # sang derrière le tympan

    # --- examen visuel ---------------------------------------------------------
    open_fracture_suspected: bool = False   # plaie crânienne profonde / os visible/deprimé
    visible_wound: bool = False             # plaie superficielle du cuir chevelu
    scalp_hematoma: bool = False            # "bosse" du cuir chevelu (perturbe le NIRS !)
    behavior_change: bool = False           # comportement anormal rapporté (PECARN)


@dataclass
class Consciousness:
    """Échelle de Glasgow (GCS) — calculée à partir de 3 sous-scores.

    GCS = OUVERTURE DES YEUX (1-4) + RÉPONSE VERBALE (1-5) + RÉPONSE MOTRICE (1-6).
    Total 3 (comateux) à 15 (normal). C'est la première question de tout urgentiste.

    Pour un usage par un NON-MÉDECIN, l'app propose des questions en langage
    simple qui se ramènent à ces sous-scores. Si l'évaluateur ne peut pas les
    remplir (patient seul et conscient), on accepte un raccourci :
    awake_normal=True → GCS=15.
    """
    eyes: int = 4          # 4=spontanée 3=à la voix 2=à la douleur 1=jamais
    verbal: int = 5        # 5=orienté 4=confus 3=mots inappropriés 2=sons 1=rien
    motor: int = 6         # 6=obéit 5=localise 4=retrait 3=flexion anormale 2=extension 1=rien
    awake_normal: bool = False

    @property
    def gcs(self) -> int:
        if self.awake_normal:
            return 15
        return max(3, min(15, self.eyes + self.verbal + self.motor))


@dataclass
class NirsExam:
    """Résultat d'un examen du bandeau CrâniCap.

    Chaque mesure est un point : paire symétrique (1=temporal, 2=frontal,
    3=pariétal, 4=occipital), longueur d'onde (760/850 nm), côté (L/R),
    et `od` = densité optique mesurée (absorption de la lumière).
    On compare ensuite OD(gauche) − OD(droite) par paire et par longueur d'onde.
    """
    measurements: List[Dict[str, Any]] = field(default_factory=list)
    # ex : {"pair": 1, "led": 760, "side": "L", "od": 0.412}

    dod_threshold: float = 0.30
    """Seuil de suspicion d'hématome. Littérature : le constructeur signale dès
    ΔOD ≈ 0,05 ; les études cliniques utilisent couramment 0,3. On paramètre
    0,30 par défaut pour limiter les faux positifs, + zone intermédiaire 0,10–0,30
    qui déclenche une consultation de contrôle (conservateur)."""

    def pairwise_dod(self) -> Dict[str, float]:
        """Retourne {« paire|longueur d'onde »: ΔOD} en valeur absolue.

        Exemple : {"1|760": 0.34, "1|850": 0.29, "3|760": 0.05 ...}
        """
        table: Dict[str, Dict[str, float]] = {}
        for m in self.measurements:
            key = f"{m['pair']}|{m['led']}"
            table.setdefault(key, {})[m["side"]] = float(m.get("od", 0.0))
        out: Dict[str, float] = {}
        for key, sides in table.items():
            if "L" in sides and "R" in sides:
                out[key] = abs(sides["L"] - sides["R"])
        return out

    def is_valid(self) -> bool:
        """Un examen NIRS n'est valide que si au moins 2 PAIRES ANATOMIQUES
        complètes sont présentes (chaque paire = LED 760 + 850 × côté L + R).

        Pourquoi 2 paires minimum ? Une seule paire n'explore qu'UNE région du
        crâne : un hématome frontal passerait inaperçu si on n'a mesuré que les
        tempes. Avec ≥ 2 paires bien placées, l'examen a une valeur d'écran réel.
        """
        paires_ok = set()
        for pair in {m["pair"] for m in self.measurements}:
            needed = {(led, side) for led in (760, 850) for side in ("L", "R")}
            present = {(m["led"], m["side"]) for m in self.measurements if m["pair"] == pair}
            if needed <= present:
                paires_ok.add(pair)
        return len(paires_ok) >= 2


@dataclass
class PupilExam:
    """Pupillométrie (caméra du téléphone ou capteur). L'ANISOCORIE (écart de
    diamètre entre les deux pupilles) > 1 mm, ou une réactivité altérée, sont
    des marqueurs reconnus d'hypertension intracrânienne."""
    left_mm: Optional[float] = None
    right_mm: Optional[float] = None
    reactivity: Optional[float] = None   # 0.0 (inerte) → 1.0 (réaction normale au flash)
    known_anisocoria: bool = False       # l'utilisateur a déjà des pupilles inégales

    @property
    def anisocoria_mm(self) -> Optional[float]:
        if self.left_mm is None or self.right_mm is None:
            return None
        return abs(self.left_mm - self.right_mm)


@dataclass
class TriageResult:
    """Le verdict complet rendu par le moteur."""
    level: str                       # green | yellow | orange | red
    reasons: List[str]               # pourquoi ce niveau (traçabilité !)
    advice: str                      # consigne principale en langage simple
    destination: str                 # urgence_immediate | hopital_aujourdhui |
                                     # consultation_24h | maison_surveillance
    confidence: float                # confiance 0–1 (heuristique)
    rules_hit: List[str]             # quelles règles cliniques se sont déclenchées
    nirs_analysis: Dict[str, Any]
    pupil_analysis: Dict[str, Any]
    worsening: bool = False          # aggravation vs évaluation précédente ?
    escalated_from: Optional[str] = None
    followup_hours: List[int] = field(default_factory=list)  # re-contrôles à programmer
    engine_version: str = ENGINE_VERSION
    disclaimer: str = DISCLAIMER
    assessed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


LEVEL_INFO = {
    "red": {
        "advice": "URGENCE. Allez à l'hôpital MAINTENANT, ne restez pas seul(e). "
                  "Faites-vous accompagner et n'attendez pas que ça passe.",
        "destination": "urgence_immediate",
    },
    "orange": {
        "advice": "Consultez un médecin AUJOURD'HUI (dans les 24 h). Une imagerie "
                  "(scanner X) est probablement nécessaire. Restez accompagné(e) et "
                  "répondez aux re-contrôles automatiques.",
        "destination": "consultation_24h",
    },
    "yellow": {
        "advice": "Symptômes présents sans critère grave. Restez à la maison sous "
                  "SURVEILLANCE STRICTE pendant 72 h : quelqu'un doit pouvoir vous "
                  "réveiller et observer votre comportement. Répondez aux re-contrôles.",
        "destination": "maison_surveillance",
    },
    "green": {
        "advice": "Aucun critère de gravité détecté pour le moment. Reposez-vous 24 h, "
                  "évitez sport, alcool et écrans intensifs. Continuez la surveillance "
                  "72 h : si un symptôme apparaît ou s'aggrave, relancez l'examen.",
        "destination": "maison_surveillance",
    },
}

FOLLOWUP_PLANS = {
    "red": [24],               # après l'envoi aux urgences : point à 24 h si pas d'hospitalisation confirmée
    "orange": [2, 6, 24],      # surveillance renforcée en attendant la consultation
    "yellow": [2, 6, 24, 48, 72],
    "green": [6, 24, 72],
}

# -----------------------------------------------------------------------------
# Règles cliniques — implémentations
# -----------------------------------------------------------------------------

BASILAR_SIGNS_LABELS = [
    ("csf_leak", "écoulement de liquide clair par le nez/oreille (suspicion de fracture basilaire)"),
    ("raccoon_eyes", "« yeux de panda » (suspicion de fracture basilaire)"),
    ("battle_sign", "ecchymose derrière l'oreille — signe de Battle (suspicion de fracture basilaire)"),
    ("hemotympanum", "sang derrière le tympan (suspicion de fracture basilaire)"),
]


def canadian_ct_head_rule(
    age: int,
    gcs: int,
    s: Symptoms,
    minutes_since: int,
    mechanisms: List[str],
    anticoagulants: bool,
) -> Dict[str, Any]:
    """RÈGLE CANADIENNE DU TCC (Stiell et al., Lancet 2001).

    Applicable si : âge ≥ 16 ans ET GCS 13–15 (traumatisme crânien léger).
    Performance publiée : 100 % de sensibilité pour le besoin de neurochirurgie
    (critères haut risque), 98,4 % pour lésion cliniquement importante.

    ⚠ Exclusion importante : les patients sous ANTI-COAGULANTS sont exclus de la
    règle originale — ils doivent être imagés de toute façon. On le gère comme
    une consultation systématique indépendante du résultat de la règle.
    """
    res: Dict[str, Any] = {
        "applicable": 16 <= age and 13 <= gcs <= 15,
        "excluded_reason": None,
        "high_risk": [],     # → imagerie obligatoire (risque neurochirurgical)
        "medium_risk": [],   # → imagerie recommandée (lésion cliniquement importante)
    }
    if age < 16:
        res["excluded_reason"] = "âge < 16 ans → règles pédiatriques (PECARN)"
        return res
    if gcs <= 12:
        res["excluded_reason"] = "GCS ≤ 12 → traumatisme modéré/sévère : urgence directe"
        return res

    # ---- CRITÈRES HAUT RISQUE -------------------------------------------------
    if gcs < 15 and minutes_since >= 120:
        res["high_risk"].append(
            f"GCS < 15 à plus de 2 h du choc (GCS={gcs} à h+{minutes_since // 60})"
        )
    if s.open_fracture_suspected:
        res["high_risk"].append("fracture ouverte ou déprimée suspectée")
    for attr, label in BASILAR_SIGNS_LABELS:
        if getattr(s, attr):
            res["high_risk"].append(label)
    if s.vomiting_count >= 2:
        res["high_risk"].append(f"vomissements ≥ 2 ({s.vomiting_count})")
    if age >= 65:
        res["high_risk"].append("âge ≥ 65 ans")

    # ---- CRITÈRES RISQUE INTERMÉDIAIRE ---------------------------------------
    if s.amnesia_minutes > 30:
        res["medium_risk"].append(f"amnésie > 30 min ({s.amnesia_minutes} min)")
    if DANGEROUS_MECHANISMS & set(mechanisms):
        res["medium_risk"].append("mécanisme dangereux (" + ", ".join(
            sorted(DANGEROUS_MECHANISMS & set(mechanisms))) + ")")

    if anticoagulants:
        res["medium_risk"].append("anticoagulants / trouble de la coagulation → consultation systématique")
    return res


def new_orleans_criteria(age: int, s: Symptoms) -> List[str]:
    """NEW ORLEANS CRITERIA — pour les patients avec GCS = 15 (tout paraît normal).
    Un seul critère présent → scanner recommandé (sensibilité ~100 %)."""
    hits = []
    if s.headache >= 3:
        hits.append(f"céphalée (intensité {s.headache}/10)")
    if s.vomiting_count >= 1:
        hits.append("vomissement")
    if age > 60:
        hits.append("âge > 60 ans")
    if s.seizure:
        hits.append("convulsion")
    if s.amnesia_minutes > 0:
        hits.append("amnésie")
    if s.visible_wound:
        hits.append("plaie visible du crâne (traumatisme visible — critère New Orleans)")
    # NOTE de conception : une simple BOSSE isolée (scalp_hematoma) n'est PAS un
    # critère New Orleans ici. Envoyer toute personne bossée à l'hôpital serait
    # cliniquement défendable (sensibilité maximale) mais détruirait la crédibilité
    # de l'outil (sur-tri massif). Compromis : bosse isolée → surveillance renforcée
    # JAUNE avec re-contrôles automatiques 72 h. Cf. tests unitaires.
    return hits


def pecarn_child(age: int, gcs: int, s: Symptoms, mechanisms: List[str]) -> Dict[str, Any]:
    """PECARN — règles pédiatriques (< 18 ans), ADAPTATION SIMPLIFIÉE.

    Le protocole PECARN original est plus fin (seuils différents selon < 2 ans
    et ≥ 2 ans). Pour un usage grand public, on garde une version conservatrice :
    tout doute → consultation. Une validation pédiatrique formelle est requise
    avant toute utilisation réelle sur enfants.
    """
    high, medium = [], []
    if gcs <= 14 or s.confusion or s.drowsiness >= 2 or s.unconscious_now:
        high.append("altération de l'état de conscience (GCS ≤ 14 / confusion / somnolence)")
    if s.open_fracture_suspected:
        high.append("fracture du crâne suspectée (palpation ou plaie)")
    for attr, label in BASILAR_SIGNS_LABELS:
        if getattr(s, attr):
            high.append(label)
    if {"pedestrian_struck", "ejection", "road_accident"} & set(mechanisms):
        high.append("mécanisme à très haute énergie (véhicule)")

    if s.loc and s.loc_minutes >= 5:
        medium.append(f"perte de connaissance ≥ 5 s ({s.loc_minutes} min)")
    if s.vomiting_count >= 1:
        medium.append(f"vomissement ({s.vomiting_count})")
    if s.headache >= 3:
        medium.append(f"céphalée (intensité {s.headache}/10)")
    if s.scalp_hematoma:
        medium.append("hématome du cuir chevelu")
    if s.seizure:
        medium.append("convulsion")
    if s.behavior_change:
        medium.append("comportement anormal rapporté")
    return {"high_risk": high, "medium_risk": medium}


def analyze_nirs(exam: NirsExam) -> Dict[str, Any]:
    """ANALYSE NIRS — détection d'asymétrie d'absorption (principe Infrascanner).

    Logique anti-faux-positifs (précisée dans la recherche) :
      - on exige une CONCORDANCE entre les 2 longueurs d'onde (760 ET 850 nm)
        sur la même paire : un vrai hématome absorbe sur les deux canaux ;
      - on demande au moins 2 paires complètes pour accepter l'examen ;
      - si un hématome du CUIR CHEVELU est déclaré (bosse), le point qui y
        correspond est suspect de FAUX POSITIF → on le signale mais on baisse
        la confiance.
    """
    out: Dict[str, Any] = {
        "valid": exam.is_valid(),
        "max_dod": 0.0,
        "suspected_pairs": [],
        "borderline_pairs": [],
        "reasons": [],
    }
    if not exam.is_valid():
        out["reasons"].append("Données NIRS insuffisantes (paires incomplètes)")
        return out

    dod = exam.pairwise_dod()
    pairs_led = {}
    for key, value in dod.items():
        pair, led = key.split("|")
        pairs_led.setdefault(pair, {})[led] = value

    for pair, wavelengths in sorted(pairs_led.items()):
        values = [v for v in wavelengths.values() if v is not None]
        if not values:
            continue
        max_v = max(values)
        concordant = len([v for v in values if v >= exam.dod_threshold]) >= 2
        borderline = any(exam.dod_threshold * 0.33 <= v < exam.dod_threshold for v in values)
        out["max_dod"] = max(out["max_dod"], max_v)
        if concordant:
            out["suspected_pairs"].append({"pair": int(pair), "dod_by_led": wavelengths})
            out["reasons"].append(
                f"NIRS : asymétrie majeure à la paire {pair} "
                f"(ΔOD max {max_v:.2f} sur 2 longueurs d'onde concordantes)"
            )
        elif borderline:
            out["borderline_pairs"].append({"pair": int(pair), "dod_by_led": wavelengths})
            out["reasons"].append(
                f"NIRS : asymétrie modérée à la paire {pair} (ΔOD max {max_v:.2f}) — contrôle recommandé"
            )
    return out


def analyze_pupils(p: PupilExam) -> Dict[str, Any]:
    """Pupillométrie : anisocorie > 1 mm ou réactivité < 0.4 → alerte.
    (L'anisocorie et la mauvaise réactivité pupillaire sont des marqueurs
    établis d'hypertension intracrânienne — cf. pupillomètres cliniques NPi.)"""
    out: Dict[str, Any] = {"anisocoria_mm": p.anisocoria_mm, "alert": False, "reasons": []}
    if p.known_anisocoria:
        out["reasons"].append("anisocorie connue de la personne — non comptabilisée")
        return out
    if p.anisocoria_mm is not None and p.anisocoria_mm > 1.0:
        out["alert"] = True
        out["reasons"].append(f"pupilles inégales (écart {p.anisocoria_mm:.1f} mm)")
    if p.reactivity is not None and p.reactivity < 0.4:
        out["alert"] = True
        out["reasons"].append(f"réactivité pupillaire altérée ({p.reactivity:.1f}/1.0)")
    return out


def detect_worsening(
    previous: Dict[str, Any],
    symptoms: Symptoms,
    nirs: NirsExam,
    pupils: PupilExam,
) -> Dict[str, Any]:
    """DÉTECTION D'AGGRAVATION — le « super-pouvoir » de l'app.

    Un traumatisme crânien peut évoluer pendant 24–72 h (hématome sous-dural
    lent). Comparer chaque re-contrôle au précédent est PLUS informatif qu'une
    évaluation isolée : c'est exactement ce qu'un proche attentif fait, mais
    ici c'est systématique et mesuré.

    Seuils de comparaison (choisis pour être cliniquement significatifs) :
      - céphalée +2 points ou plus
      - nouveau vomissement
      - somnolence +1 cran
      - apparition de : confusion, déficit moteur, convulsion, drapeaux basilarité
      - asymétrie NIRS qui augmente de ≥ 0.10
      - anisocorie qui augmente
    """
    res = {"worsening": False, "reasons": [], "escalate_from": None}
    if not previous:
        return res
    prev_s = previous.get("symptoms") or {}
    prev_nirs = (previous.get("nirs_analysis") or {}).get("max_dod", 0.0)

    if symptoms.headache - int(prev_s.get("headache", 0)) >= 2:
        res["worsening"] = True
        res["reasons"].append(f"céphalée en hausse ({prev_s.get('headache', 0)} → {symptoms.headache}/10)")
    if symptoms.vomiting_count > int(prev_s.get("vomiting_count", 0)):
        res["worsening"] = True
        res["reasons"].append("nouveau(x) vomissement(s)")
    if symptoms.drowsiness > int(prev_s.get("drowsiness", 0)):
        res["worsening"] = True
        res["reasons"].append("somnolence accrue")
    if symptoms.confusion and not prev_s.get("confusion"):
        res["worsening"] = True
        res["reasons"].append("confusion NOUVELLE")
    if symptoms.motor_deficit and not prev_s.get("motor_deficit"):
        res["worsening"] = True
        res["reasons"].append("déficit moteur NOUVEAU")
    if symptoms.seizure and not prev_s.get("seizure"):
        res["worsening"] = True
        res["reasons"].append("convulsion NOUVELLE")
    if not prev_s.get("csf_leak") and symptoms.csf_leak:
        res["worsening"] = True
        res["reasons"].append("écoulement de liquide NOUVEAU")

    nirs_now = analyze_nirs(nirs).get("max_dod", 0.0)
    if nirs_now - prev_nirs >= 0.10:
        res["worsening"] = True
        res["reasons"].append(f"asymétrie NIRS en hausse (ΔOD {prev_nirs:.2f} → {nirs_now:.2f})")

    prev_aniso = (previous.get("pupil_analysis") or {}).get("anisocoria_mm") or 0.0
    if (pupils.anisocoria_mm or 0.0) - prev_aniso >= 0.5:
        res["worsening"] = True
        res["reasons"].append("écart pupillaire en hausse")

    if res["worsening"] and previous.get("level"):
        res["escalate_from"] = previous["level"]
    return res


# -----------------------------------------------------------------------------
# Fonction principale : run_triage
# -----------------------------------------------------------------------------

def run_triage(
    profile: Profile,
    incident: Incident,
    consciousness: Consciousness,
    symptoms: Symptoms,
    nirs: Optional[NirsExam] = None,
    pupils: Optional[PupilExam] = None,
    previous: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> TriageResult:
    """Évaluation complète du patient → verdict (TriageResult).

    Ordre de raisonnement (du plus grave au moins grave) — c'est la logique
    standard de triage : on cherche d'abord ce qui exige les urgences, puis on
    « descend » d'un cran tant qu'on ne trouve rien.
    """
    nirs = nirs or NirsExam()
    pupils = pupils or PupilExam()
    reasons: List[str] = []
    rules_hit: List[str] = []

    gcs = consciousness.gcs
    minutes = incident.minutes_since_impact(now)

    # ------------------------------------------------------------------ 🔴 1
    # DRAPEAUX ROUGES ABSOLUS : situations où chaque minute compte.
    # (Ce sont les signes d'hypertension intracrânienne / compression cérébrale.)
    red_flags: List[str] = []
    if gcs <= 12:
        red_flags.append(f"état de conscience altéré (GCS {gcs} ≤ 12)")
    if symptoms.unconscious_now:
        red_flags.append("personne inconsciente en ce moment")
    if symptoms.seizure:
        red_flags.append("convulsion depuis le choc")
    if symptoms.motor_deficit:
        red_flags.append("faiblesse/engourdissement d'un membre (déficit moteur)")
    if symptoms.drowsiness >= 3:
        red_flags.append("impossible de réveiller la personne")
    for attr, label in BASILAR_SIGNS_LABELS:
        if getattr(symptoms, attr):
            red_flags.append(label)
    if symptoms.open_fracture_suspected:
        red_flags.append("fracture ouverte/déprimée suspectée")

    # Pupilles inégales (si non connues) — signe de compression cérébrale.
    pupil_analysis = analyze_pupils(pupils)
    if pupil_analysis["alert"]:
        red_flags.extend(pupil_analysis["reasons"])

    # ------------------------------------------------------------------ 🧲 2
    # ANALYSE NIRS — suspicion d'hématome intracrânien (principe Infrascanner).
    nirs_analysis = analyze_nirs(nirs)
    nirs_positive = bool(nirs_analysis["suspected_pairs"])
    if nirs_positive:
        red_flags.append(
            "suspicion d'hématome intracrânien par mesure optique (NIRS) — voir examen du crâne"
        )

    if red_flags:
        reasons.extend(red_flags)
        rules_hit.append("drapeaux_rouges")
        if nirs_positive:
            rules_hit.append("NIRS_asymétrie")
        return _finish("red", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)

    # ------------------------------------------------------------------ 3
    # RÈGLE CANADIENNE (adultes, TCC léger GCS 13–15)
    cchr = canadian_ct_head_rule(profile.age, gcs, symptoms, minutes, incident.mechanisms,
                                 profile.anticoagulants)
    if cchr["applicable"]:
        rules_hit.append("règle_canadienne_TCC")
        if cchr["high_risk"]:
            reasons.extend(f"Règle canadienne — haut risque : {r}" for r in cchr["high_risk"])
        if cchr["medium_risk"]:
            reasons.extend(f"Règle canadienne — risque intermédiaire : {r}" for r in cchr["medium_risk"])
        if cchr["high_risk"]:
            # Haut risque → imagerie nécessaire. Sans drapeau rouge, ce n'est pas
            # « minute par minute », mais c'est « aujourd'hui, sans attendre ».
            return _finish("orange", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None,
                           destination="hopital_aujourdhui")
        if cchr["medium_risk"]:
            # Risque intermédiaire → consultation < 24 h. On retourne TOUT DE SUITE :
            # sinon les règles suivantes (moins graves) « mangeraient » cette raison.
            return _finish("orange", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)

    # ------------------------------------------------------------------ 4
    # ENFANTS — PECARN (adaptation simplifiée)
    if profile.age < 18:
        pec = pecarn_child(profile.age, gcs, symptoms, incident.mechanisms)
        rules_hit.append("PECARN_(adaptation_pédiatrique)")
        if pec["high_risk"]:
            reasons.extend(f"Pédiatrie — haut risque : {r}" for r in pec["high_risk"])
            return _finish("orange", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None,
                           destination="hopital_aujourdhui")
        if pec["medium_risk"]:
            reasons.extend(f"Pédiatrie — à surveiller : {r}" for r in pec["medium_risk"])
            return _finish("yellow", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)

    # ------------------------------------------------------------------ 5+6
    # NEW ORLEANS (GCS = 15) + AGRAVATION (trajectoire) — combinés car les deux
    # peuvent coexister. PRINCIPE D'OR du triage : quand plusieurs règles
    # contribuent chacune un niveau de gravité, le verdict FINAL est le MAXIMUM
    # de toutes les contributions (le plus grave gagne). Jamais « la première
    # règle qui matche » — sinon une escalade modérée masquerait un critère fort
    # (bug détecté par le test : céphalée 8/10 downgradée en jaune).
    nola_hits: List[str] = []
    if gcs == 15:
        nola = new_orleans_criteria(profile.age, symptoms)
        if nola:
            rules_hit.append("New_Orleans_Criteria")
            nola_hits = [f"New Orleans : {r}" for r in nola]

    worsening = detect_worsening(previous, symptoms, nirs, pupils)
    if worsening["worsening"]:
        rules_hit.append("détection_d'aggravation")

    if worsening["worsening"] or nola_hits:
        reasons.extend(worsening["reasons"])
        reasons.extend(nola_hits)
        base_prev = worsening.get("escalate_from") or (previous or {}).get("level") or "green"
        trajectory_level = promote(base_prev, 1) if worsening["worsening"] else None
        nola_level = "orange" if nola_hits else None
        candidates = [l for l in (trajectory_level, nola_level) if l]
        final_level = max(candidates, key=lambda l: LEVEL_ORDER[l])
        return _finish(final_level, reasons, rules_hit, nirs_analysis, pupil_analysis,
                       worsening["worsening"], worsening.get("escalate_from"))

    # Symptomatique sans critère fort → surveillance stricte à la maison.
    other_symptoms = (
        symptoms.light_sensitivity or symptoms.neck_pain or symptoms.visible_wound
        or symptoms.scalp_hematoma or symptoms.loc or bool(nirs_analysis["borderline_pairs"])
    )
    if symptoms.headache >= 1 or other_symptoms:
        if symptoms.loc:
            reasons.append(f"perte de connaissance signalée ({symptoms.loc_minutes} min)")
        if symptoms.headache >= 1:
            reasons.append(f"céphalée ({symptoms.headache}/10)")
        if symptoms.scalp_hematoma:
            reasons.append("hématome du cuir chevelu (bosse) — surveillance nécessaire")
        if symptoms.visible_wound:
            reasons.append("plaie du cuir chevelu")
        if symptoms.light_sensitivity:
            reasons.append("sensibilité à la lumière")
        if symptoms.neck_pain:
            reasons.append("douleur du cou — éviter les mouvements du cou")
        for b in nirs_analysis["borderline_pairs"]:
            reasons.append(f"NIRS : asymétrie modérée à la paire {b['pair']} — contrôle recommandé")
        rules_hit.append("surveillance_symptomatique")
        return _finish("yellow", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)

    # ------------------------------------------------------------------ 🟢 7
    # Rien trouvé : repos + éducation + re-contrôles.
    rules_hit.append("aucun_critère")
    if profile.anticoagulants:
        reasons.append("anticoagulants : contrôle médical conseillé malgré l'absence de symptôme")
        return _finish("yellow", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)
    reasons.append(
        f"aucun critère de gravité (GCS {gcs}, aucun symptôme d'alerte, "
        + ("examen NIRS symétrique" if nirs_analysis["valid"] else "sans examen du crâne") + ")"
    )
    return _finish("green", reasons, rules_hit, nirs_analysis, pupil_analysis, False, None)


def _finish(
    level: str,
    reasons: List[str],
    rules_hit: List[str],
    nirs_analysis: Dict[str, Any],
    pupil_analysis: Dict[str, Any],
    worsening: bool,
    escalated_from: Optional[str],
    destination: Optional[str] = None,
) -> TriageResult:
    """Fabrique le TriageResult final : consigne, destination, plan de suivi,
    confiance. Centralisé ici pour que TOUT verdict ait la même structure."""
    info = LEVEL_INFO[level]
    confidence = 0.55
    if nirs_analysis.get("valid"):
        confidence += 0.20        # l'examen objectif augmente la confiance
    if pupil_analysis.get("anisocoria_mm") is not None:
        confidence += 0.10
    if nirs_analysis.get("suspected_pairs"):
        confidence = min(0.95, confidence + 0.15)
    return TriageResult(
        level=level,
        reasons=reasons or ["aucun critère détecté"],
        advice=info["advice"],
        destination=destination or info["destination"],
        confidence=round(confidence, 2),
        rules_hit=rules_hit,
        nirs_analysis=nirs_analysis,
        pupil_analysis=pupil_analysis,
        worsening=worsening,
        escalated_from=escalated_from,
        followup_hours=FOLLOWUP_PLANS[level],
        assessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
