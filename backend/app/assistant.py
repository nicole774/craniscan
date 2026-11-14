# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — ASSISTANT IA « NAYA » (conseillère médicale virtuelle)
===============================================================================
Rôle de Naya : guider le patient en français simple, répondre aux questions
courantes, collecter les symptômes en conversation naturelle, et surtout
DÉCLENCHER L'ESCALADE dès qu'un symptôme grave apparaît.

ARCHITECTURE (choix d'ingénierie important) :
  Le MVP utilise un moteur DÉTERMINISTE (détection d'intentions par motifs)
  plutôt qu'un LLM. Pourquoi ?
    1. SÛRETÉ : une réponse médicale est déterministe et testable. Un LLM
       peut « improviser » — inacceptable sur un cas d'hémorragie.
    2. TRAÇABILITÉ : on sait exactement pourquoi Naya a répondu ça.
    3. HORS LIGNE : ça marche sans internet dans un dispensaire rural.
  L'interface `LLMProvider` ci-dessous prépare la V2 : on pourra brancher un
  LLM (cloud ou Ollama en local) pour la fluidité conversationnelle, MAIS les
  réponses à risque (drapeaux rouges) passeront TOUJOURS par les règles.

Chaque réponse = {reply, quick_replies, action, severity}
  action    : instruction machine pour l'app (appeler les urgences, ouvrir
              l'examen, générer le rapport…)
  severity  : red/orange/yellow/green si Naya a réévalué la situation
===============================================================================
"""

import re
from typing import Any, Dict, List, Optional

from app.triage import (
    Consciousness, Incident, NirsExam, Profile, PupilExam, Symptoms, run_triage,
)

LLM_SYSTEM_PROMPT = """Tu es Naya, l'assistante médicale virtuelle de CrâniScan.
Tu accompagnes une personne après un choc à la tête. Règles absolues :
1. Tu n'es PAS médecin et tu ne pose JAMAIS de diagnostic définitif.
2. Tout symptôme grave (convulsion, inconscience, vomissements répétés,
   écoulement de liquide clair, pupilles inégales, déficit moteur) → tu
   ordonnes IMMÉDIATEMENT d'appeler les secours, sans nuance.
3. Tu réponds en français simple, avec empathie, en phrases courtes.
4. Tu orientes vers le questionnaire ou l'examen du bandeau CrâniCap.
Ce prompt est réservé à la V2 (interface LLMProvider ci-dessous)."""


class LLMProvider:
    """Interface pour brancher un LLM en V2 (OpenAI-compatible / Ollama).
    Volontairement non implémentée dans le MVP : la sûreté médicale passe
    par les règles, pas par un modèle génératif."""

    def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError("LLMProvider sera implémenté en V2 (Ollama local / API)")


# -----------------------------------------------------------------------------
# Moteur d'intentions
# -----------------------------------------------------------------------------

# Drapeaux rouges en langage naturel — déclenchent l'escalade IMMÉDIATE.
RED_FLAG_PATTERNS = [
    (r"convulsion|crise d'épilepsie|il (a|fait) une crise|tremble de partout", "convulsion"),
    (r"(ne se réveille pas|pas réveiller|inconscient|inconscience|comateux)", "inconscience"),
    (r"(liquide clair|liquide qui coule|un liquide du (nez|oreille)|sang du nez)", "écoulement (fracture basilaire possible)"),
    (r"(yeux de panda|autour des yeux)", "yeux de panda"),
    (r"(derrière l'oreille|derrière les oreilles)", "signe de Battle possible"),
    (r"(paralys|ne peut pas bouger|mal à bouger (mon|ma|le|la)|engourdi|fourmil)", "déficit moteur / engourdissement"),
    (r"(je (vois|voyais) double|vision double|double vision)", "vision double"),
    (r"(ne respire pas|respire plus)", "détresse respiratoire"),
]

# Extraction des symptômes mesurables dans le texte libre.
PAIN_PATTERN = re.compile(r"(\d{1,2})\s*(?:/|sur)\s*(?:10)", re.IGNORECASE)
COUNT_PATTERN = re.compile(r"(\d+)\s*(?:fois|vomissements|épisodes)", re.IGNORECASE)


def extract_symptoms(text: str) -> (Dict[str, Any], List[str], List[str]):
    """Analyse le texte libre du patient → (modifications de Symptoms,
    symptômes reconnus [prose], drapeaux rouges détectés [prose])."""
    t = text.lower()
    updates: Dict[str, Any] = {}
    found: List[str] = []
    red_flags: List[str] = []

    # --- drapeaux rouges d'abord (priorité absolue) --------------------------
    for pattern, label in RED_FLAG_PATTERNS:
        if re.search(pattern, t):
            red_flags.append(label)
            if label == "convulsion":
                updates["seizure"] = True
            elif label == "inconscience":
                updates["unconscious_now"] = True
                updates["drowsiness"] = 3
            elif label == "écoulement (fracture basilaire possible)":
                updates["csf_leak"] = True
            elif label == "yeux de panda":
                updates["raccoon_eyes"] = True
            elif label == "signe de Battle possible":
                updates["battle_sign"] = True
            elif label == "déficit moteur / engourdissement":
                updates["motor_deficit"] = True
            elif label == "vision double":
                updates["double_vision"] = True

    # --- céphalée --------------------------------------------------------------
    if re.search(r"(j'ai mal|douleur|mal de tête|mal à la tête|la tête me fait)", t):
        m = PAIN_PATTERN.search(t)
        if m:
            updates["headache"] = min(10, int(m.group(1)))
            found.append(f"céphalée {updates['headache']}/10")
        elif re.search(r"(insupportable|très fort|atroc|violent)", t):
            updates["headache"] = 9
            found.append("céphalée très intense (≈9/10)")
        elif re.search(r"(beaucoup|fort|c'est fort)", t):
            updates["headache"] = 6
            found.append("céphalée forte (≈6/10)")
        elif "headache" not in updates and re.search(r"j'ai mal|douleur|mal de tête", t):
            updates["headache"] = max(updates.get("headache", 0), 4)
            found.append("céphalée modérée (≈4/10)")
        if re.search(r"(derrière la tête|occiput|arrière de la tête)", t):
            found.append("douleur localisée à l'arrière de la tête")
        if re.search(r"(devant|front)", t) and "douleur localisée" not in str(found):
            found.append("douleur localisée au front")

    # --- vomissements ------------------------------------------------------------
    if re.search(r"(vomi|nausée|nausées|je rends|rendu)", t):
        m = COUNT_PATTERN.search(t)
        if m:
            updates["vomiting_count"] = max(updates.get("vomiting_count", 0), int(m.group(1)))
            found.append(f"{updates['vomiting_count']} vomissement(s)")
        else:
            updates["vomiting_count"] = max(updates.get("vomiting_count", 0), 1)
            found.append("vomissement")

    # --- somnolence ---------------------------------------------------------------
    if re.search(r"(difficile à réveiller|je n'arrive pas à rester|somnol|envie de dormir)", t):
        updates["drowsiness"] = 2 if "difficile à réveiller" not in t else 3
        found.append("somnolence")
    if re.search(r"(confus|je ne sais pas où|perdu la notion|désorient|propos incohérents)", t):
        updates["confusion"] = True
        found.append("confusion")

    # --- mécanisme rétrospectif (rarement retappé, mais possible) -----------------
    if re.search(r"(je suis tombé|il est tombé|tombé de|chute de)", t):
        found.append("chute signalée")

    return updates, found, red_flags


QUICK_MAIN = ["Commencer l'examen", "Mes symptômes maintenant", "Quels signes surveiller ?", "Appeler mes contacts"]

SIGNS_TO_WATCH = (
    "Voici les SIGNES D'ALERTE pendant les 72 h à venir — si l'un apparaît, "
    "relancez l'examen ou allez directement aux urgences :\n"
    "• mal de tête qui AUGMENTE malgré le repos\n"
    "• vomissements (surtout répétés)\n"
    "• somnolence inhabituelle, difficile à réveiller\n"
    "• confusion, propos incohérents\n"
    "• convulsion\n"
    "• faiblesse ou fourmillements d'un bras/une jambe\n"
    "• vision double\n"
    "• liquide clair qui coule du nez ou des oreilles\n"
    "• pupilles de tailles différentes"
)

SLEEP_ADVICE = (
    "Question classique ! Oui, vous pouvez dormir — MAIS avec un protocole de "
    "sécurité : quelqu'un doit pouvoir vous réveiller une première fois après "
    "1–2 h de sommeil pour vérifier que vous marchez normalement et parlez "
    "normalement. Dormez surtout à côté de quelqu'un informé de votre choc. "
    "Si impossible d'être réveillé → urgences IMMÉDIATEMENT."
)

HABITS_ADVICE = (
    "Pendant 72 h après un choc à la tête :\n"
    "• ❌ PAS d'alcool (masque les symptômes et augmente le risque)\n"
    "• ❌ Pas de sport ni d'effort intense\n"
    "• ❌ Pas de conduite au début (réflexes et vigilance altérés)\n"
    "• ✅ Repos, hydratation, paracétamol si nécessaire (pas d'aspirine ni "
    "d'ibuprofène sans avis médical : risque de saignement)\n"
    "• ✅ Écrans modérés si la lumière vous gêne"
)


class Assistant:
    """Naya — moteur conversationnel déterministe adossé au moteur de triage."""

    def __init__(self, llm: Optional[LLMProvider] = None):
        self.llm = llm  # V2 : si fourni, sert à reformuler, jamais à décider

    # ------------------------------------------------------------------ API
    def answer(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Traite un message utilisateur et retourne la réponse structurée.

        context (fourni par l'API) :
          profile/incident/symptoms/consciousness/pupils  → état actuel
          previous_triage                                 → dernier verdict
          has_nirs_exam                                   → examen réalisé ?
        """
        context = context or {}
        text = (message or "").strip()
        t = text.lower()

        # 1) DRAPEAUX ROUGES dans le langage naturel → escalade instantanée.
        updates, found, red_flags = extract_symptoms(text)
        if red_flags:
            return self._red_escalation(red_flags, found, context)

        # 2) Symptômes reconnus → on RÉÉVALUE avec le moteur de triage.
        if updates or (found and "chute signalée" not in found):
            return self._reassess(updates, found, context)

        # 3) Questions fréquentes.
        if re.search(r"(^| )(bonjour|bonsoir|salut|hello|coucou)($| )", t):
            return self._hello(context)
        if re.search(r"(qui es[- ]tu|tu es qui|c'est quoi naya|comment tu t'appelles)", t):
            return self._who_am_i()
        if re.search(r"(comment (ça|ca|tu) (marche|fonctionne)|comment faire|comment utiliser|comment tu fonctionnes)", t):
            return self._how_it_works()
        if re.search(r"(dormir|coucher|sommeil)", t):
            return self._generic(SLEEP_ADVICE, ["Mes symptômes maintenant", "Quels signes surveiller ?"])
        if re.search(r"(alcool|boire un|bière|vin)|(\bsport\b)|conduire", t):
            return self._generic(HABITS_ADVICE, ["Quels signes surveiller ?", "Mes symptômes maintenant"])
        if re.search(r"(signes|surveiller|symptômes à)", t):
            return self._generic(SIGNS_TO_WATCH, ["Commencer l'examen", "Mes symptômes maintenant"])
        if re.search(r"(pourquoi|explique|c'est quoi ce verdict|ce niveau)", t):
            return self._explain_verdict(context)
        if re.search(r"(dois[- ]je aller|aller à l'hôpital|au dispensaire|combien de temps)", t):
            return self._explain_verdict(context)
        if re.search(r"(appelle|appeler|prévenir|contacter|secours|urgences)", t):
            return self._call_contacts(context)
        if re.search(r"(rapport|document|pdf|synthèse|historique)", t):
            return self._generic(
                "Je peux générer un rapport complet de votre suivi (chronologie, mesures, "
                "verdicts et raisons) à montrer au médecin ou à l'infirmier. "
                "Utilisez le bouton « Rapport » sur l'écran de suivi.",
                ["Rapport", "Quels signes surveiller ?"])
        if re.search(r"(merci)", t):
            return self._generic(
                "Avec plaisir ! Je reste disponible 24 h/24 pendant toute votre surveillance. "
                "Pensez à répondre aux re-contrôles automatiques. 💙",
                QUICK_MAIN)

        # 4) Défaut : empathie + réorientation.
        return self._generic(
            "Je vous écoute. Décrivez-moi comment vous vous sentez (par exemple : "
            "« j'ai mal à la tête 6/10 », « j'ai vomi 2 fois », « j'ai sommeil ») — "
            "ou choisissez une option ci-dessous.",
            QUICK_MAIN)

    # ------------------------------------------------------------- réponses
    def _hello(self, context):
        if context.get("active_incident"):
            triage = context.get("previous_triage") or {}
            level = triage.get("level")
            if level:
                return self._generic(
                    f"Bonjour ! Toujours en surveillance ({level}). Comment vous "
                    "sentez-vous depuis le dernier contrôle ?",
                    ["Mes symptômes maintenant", "Quels signes surveiller ?", "Rapport"])
        return self._generic(
            "Bonjour, je suis Naya, votre conseillère médicale CrâniScan. 🧠💙\n"
            "Si vous venez d'avoir un choc à la tête, je vous propose de faire le "
            "point en 5 minutes. Comment puis-je vous aider ?",
            ["J'ai eu un accident", "Commencer l'examen", "Comment ça marche ?"])

    def _who_am_i(self):
        return self._generic(
            "Je suis Naya, l'assistante IA de CrâniScan. Mon travail : vous aider à "
            "évaluer un choc à la tête (questionnaire guidé + examen du crâne par le "
            "bandeau CrâniCap si vous en avez un), surveiller votre évolution pendant "
            "72 h, et vous diriger vers un vrai médecin dès que nécessaire.\n"
            "⚠️ Important : je suis une aide à l'orientation — je ne remplace ni un "
            "médecin, ni un scanner.",
            QUICK_MAIN)

    def _how_it_works(self):
        return self._generic(
            "Voici comment nous allons procéder :\n"
            "1️⃣ Vous répondez à un questionnaire guidé (3 min) : mécanisme du choc, "
            "symptômes, état de conscience — je l'analyse selon les règles utilisées "
            "par les urgentistes (règle canadienne, New Orleans, PECARN).\n"
            "2️⃣ Si vous avez le bandeau CrâniCap : examen du crâne en 2 min — il "
            "compare l'absorption de lumière infrarouge de chaque côté du crâne pour "
            "repérer un éventuel hématome.\n"
            "3️⃣ Vous recevez un verdict clair : 🟢 surveiller à la maison, 🟡 surveillance "
            "stricte, 🟠 consulter sous 24 h, 🔴 urgences immédiates.\n"
            "4️⃣ Je reste avec vous : re-contrôles automatiques pendant 72 h et alerte "
            "de vos contacts si quelque chose s'aggrave.",
            ["J'ai eu un accident", "Commencer l'examen"])

    def _reassess(self, updates: Dict[str, Any], found: List[str], context) -> Dict[str, Any]:
        """Le patient décrit des symptômes → réévaluation complète par le moteur."""
        base_symptoms = (context.get("symptoms") or {}).copy()
        base_symptoms.update(updates)
        profile = Profile(**(context.get("profile") or {"age": 30}))
        inc_data = dict(context.get("incident") or {"mechanisms": ["other"]})
        if isinstance(inc_data.get("impact_at"), str) and inc_data["impact_at"]:
            from datetime import datetime as _dt
            inc_data["impact_at"] = _dt.fromisoformat(inc_data["impact_at"])
        incident = Incident(**inc_data)
        consciousness = Consciousness(**(context.get("consciousness") or {"awake_normal": True}))
        pupils = PupilExam(**(context["pupils"])) if context.get("pupils") else PupilExam()
        nirs = NirsExam()  # la réévaluation par chat ne refait pas la mesure NIRS
        result = run_triage(profile, incident, consciousness, Symptoms(**base_symptoms),
                            nirs=nirs, pupils=pupils,
                            previous=context.get("previous_triage"))
        lines = []
        if found:
            lines.append("J'ai bien noté : " + ", ".join(found) + ".")
        lines.append(f"Résultat de la réévaluation : verdict {result.level.upper()}.")
        lines.append("• " + "\n• ".join(result.reasons[:6]))
        lines.append(result.advice)
        if result.level == "red":
            action = {"type": "call_emergency"}
            lines.append("📞 Voulez-vous que j'alerte vos contacts d'urgence ?")
        else:
            action = {"type": "update_incident"}
        quick = ["Appeler mes contacts", "Commencer l'examen", "Quels signes surveiller ?"]
        return {"reply": "\n".join(lines), "quick_replies": quick,
                "action": action, "severity": result.level,
                "triage": result.to_dict()}

    def _red_escalation(self, red_flags: List[str], found: List[str], context) -> Dict[str, Any]:
        """Naya n'hésite JAMAIS sur un drapeau rouge : urgence, tout de suite."""
        reply = (
            "🚨 STOP — ce que vous décrivez est GRAVE :\n• " + "\n• ".join(red_flags) +
            "\n\n👉 Appelez les secours MAINTENANT (bouton ci-dessous) et faites-vous "
            "accompagner à l'hôpital. Ne restez pas seul(e). Je prépare vos contacts "
            "d'urgence et votre rapport médical."
        )
        return {"reply": reply,
                "quick_replies": ["Appeler mes contacts", "Rapport"],
                "action": {"type": "call_emergency", "reasons": red_flags},
                "severity": "red"}

    def _explain_verdict(self, context) -> Dict[str, Any]:
        triage = context.get("previous_triage")
        if not triage:
            return self._generic(
                "Pas encore de verdict : commençons par le questionnaire, puis je "
                "pourrai tout vous expliquer en détail.",
                ["J'ai eu un accident", "Commencer l'examen"])
        level = triage.get("level", "?")
        reasons = triage.get("reasons", [])
        reply = (f"Votre verdict actuel est {level.upper()}. Voici pourquoi, en langage simple :\n"
                 + "\n".join(f"• {r}" for r in reasons[:8])
                 + f"\n\n{triage.get('advice', '')}")
        quick = ["Quels signes surveiller ?", "Rapport", "Mes symptômes maintenant"]
        return {"reply": reply, "quick_replies": quick, "action": None, "severity": None}

    def _call_contacts(self, context) -> Dict[str, Any]:
        contacts = context.get("contacts") or []
        names = ", ".join(f"{c.get('name', '?')} ({c.get('phone', '?')})" for c in contacts) or \
            "aucun contact enregistré — ajoutez-en dans votre profil"
        return {"reply": f"J'alerte vos contacts d'urgence : {names}. Appelez aussi les "
                         f"secours directement si vous êtes seul(e) — le bouton « 📞 Urgence » "
                         f"compose le numéro en un geste.",
                "quick_replies": ["Rapport"], "action": {"type": "notify_contacts"},
                "severity": None}

    def _generic(self, reply: str, quick: List[str]) -> Dict[str, Any]:
        return {"reply": reply, "quick_replies": quick, "action": None, "severity": None}
