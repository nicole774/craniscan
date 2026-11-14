# CrâniScan — Cahier de conception
**Système complet : bandeau capteur « CrâniCap » + app mobile « CrâniScan » + assistant IA « Naya »**
*Version 1.0 — 2026-11-14*

---

## 1. Vision et utilisateurs

> « Après un choc à la tête, toute personne doit pouvoir savoir en 5 minutes
> si elle est en danger et si elle doit aller à l'hôpital — où qu'elle soit, quels que soient ses moyens. »

| Utilisateur | Contexte | Ce que le système lui apporte |
|---|---|---|
| **Le patient / la victime** | Chez lui, dans la rue, après un accident | Examen guidé du crâne + pupilles, verdict clair par couleur, consignes simples |
| **Un proche / témoin** | Examine quelqu'un d'autre (enfant, personne âgée, victime confuse) | Mode « j'examine quelqu'un », questions posées à l'observateur, GCS simplifiée |
| **L'infirmier / agent de santé** | Dispensaire, clinique sans scanner | Mode Pro : NIRS + ONSD échographique optionnel, rapport PDF pour transfert |
| **La famille** | Veille 72 h sur le patient resté à la maison | Tâches automatiques : re-contrôles programmés, alerte si aggravation, notification d'urgence |

### Le parcours utilisateur en 6 étapes
1. **« J'ai eu un accident »** → l'app enregistre l'heure du choc (critique : les règles cliniques dépendent du délai).
2. **Questionnaire guidé** (3 min) : mécanisme du choc, symptômes actuels, état de conscience — les questions suivent exactement les règles cliniques validées.
3. **Examen du crâne** (optionnel mais recommandé) : appairage du bandeau CrâniCap en 1 clic, ou **mode sans capteur** (caméra pour les pupilles + questionnaire renforcé).
4. **Verdict** : 🟢 🟡 🟠 🔴 + liste des raisons + consignes écrites et vocales.
5. **Assistant IA « Naya »** : conversation en français simple, répond « dois-je dormir ? », « qu'est-ce que je surveille ? », « appelle mes contacts »...
6. **Surveillance automatique 72 h** : re-contrôles programmés (2 h, 6 h, 24 h, 48 h, 72 h), escalade automatique si aggravation, alerte aux contacts d'urgence.

---

## 2. Architecture système

```
┌─────────────────────┐        BLE (GATT)         ┌──────────────────────────────────┐
│  CrâniCap (bandeau) │◄────────────────────────►│  APP MOBILE CrâniScan (PWA)      │
│  · 8 pts NIRS       │   trames JSON temps réel  │  · assistant d'accueil           │
│  · IMU (impacts)    │                           │  · examen guidé + graphiques     │
│  · PPG (pouls)      │                           │  · verdict feux tricolores       │
│  · ESP32-C3, USB-C  │                           │  · chat IA « Naya »              │
└─────────────────────┘                           │  · suivi auto + notifications    │
                                                  └───────────────┬──────────────────┘
   ┌────────────────────┐         HTTPS / WS                      │
   │ Sonde échographique│◄────────────────────────┐               ▼
   │ pro (optionnel)    │                         │   ┌──────────────────────────────┐
   └────────────────────┘                         └───┤  BACKEND FastAPI (Python)    │
                                                      │  · moteur de triage clinique │
      ┌───────────────────────┐                       │    (GCS, CCHR, NOLA, PECARN) │
      │ Contacts d'urgence ◄──┤  SMS/appel/app push   │  · analyse NIRS (ΔOD)        │
      │ (proches, dispensaire)│  (Twilio en prod)     │  · assistant IA « Naya »     │
      └───────────────────────┘                       │  · planificateur de tâches   │
                                                      │  · historique + rapport PDF  │
                                                      │  · SQLite chiffrable         │
                                                      └──────────────────────────────┘
```

**Décisions d'architecture clés**
- **L'intelligence côté app/backend, la simplicité côté matériel** : le bandeau ne fait que mesurer
  et transmettre → moins cher, moins de pannes, mise à jour des algorithmes sans toucher au matériel.
- **PWA (Progressive Web App)** : installable sur Android/iOS depuis le navigateur, fonctionne
  hors ligne (cache du questionnaire), pas de store à contourner — critique dans les pays où
  les stores/appareils sont un obstacle. Migration native (Capacitor/Flutter) prévue en V2 pour
  Bluetooth natif iOS et notifications push système.
- **Mode dégradé complet** : sans bandeau, l'app fonctionne (questionnaire + pupilles caméra) ;
  sans internet, le moteur de triage embarqué (JS) prend le relais ; sans smartphone du tout,
  un agent de santé peut faire la même chose depuis son propre téléphone.
- **Séparation stricte** entre : données mesurées (NIRS/IMU/PPG), données déclarées (questionnaire),
  et règles (moteur de triage versionné, testé unitairement) → auditabilité médicale.

---

## 3. Matériel : le bandeau « CrâniCap »

### 3.1 Spécification fonctionnelle
| Exigence | Cible |
|---|---|
| Confort / ergonomie | Bandeau textile élastiqué, mousse respirante, taille unique ajustable, < 150 g, portable 3 min sans douleur |
| Positionnement | Repères cousus + guide animé dans l'app (les LED s'allument sur le schéma de la tête quand chaque paire est active) |
| Mesure | 4 paires symétriques (temporal, frontal, pariétal, occipital) × 2 longueurs d'onde (760/850 nm), ΔOD par paire |
| Durée d'un examen | < 3 min (mesure séquentielle automatisée, ~10 s par point) |
| Autonomie | ≥ 8 h, charge USB-C |
| Hygiène multi-usagers | Coiffe jetable amovible + désinfection des émetteurs |

### 3.2 Nomenclature (BOM) grand public
| Composant | Qté | Prix ≈ |
|---|---|---|
| LED NIR 760 nm + 850 nm (8 émetteurs × 2) | 16 | 12 $ |
| Photodiode + amplification (8 canaux multiplexés) | 8 | 10 $ |
| ESP32-C3 (Wi-Fi/BLE, MCU) | 1 | 8 $ |
| IMU 6 axes (MPU-6050/BMI270) | 1 | 3 $ |
| PPG (MAX30102 ou équivalent) | 1 | 4 $ |
| Batterie LiPo 1 500 mAh + charge USB-C | 1 | 12 $ |
| Textile/mousse/coiffe jetable + câblage | 1 lot | 20 $ |
| **Total composants (production)** | | **≈ 55–70 $** |

Cohérent avec FlexNIRS (≈ 50 $/unité en volume, Wu et al. 2022). **Version « fablab/DIY »** :
même BOM en modules Arduino, firmware ouvert sous licence libre, même protocole BLE.

### 3.3 Protocole BLE GATT (interface app ↔ bandeau)
```
Service principal :  6e40c0a1-... (« CraniScan Service »)
  CARACT   UUID            Format (JSON)
  NIR      ...c0a2         {"t":ms,"led":760,"pair":1,"side":"L","od":0.412}
                           {"t":ms,"led":850,"pair":1,"side":"R","od":0.317}
  IMU      ...c0a3         {"t":ms,"g_force":3.8,"rot":112,"event":"impact"}
  PPG      ...c0a4         {"t":ms,"bpm":78,"quality":0.9}
  CMD      ...c0a5         {"cmd":"start_exam"} | {"cmd":"stop"} | {"cmd":"battery"}
  STATUS   ...c0a6         {"batt":84,"skin_t":35.2,"paired":true}
```
La mesure NIR est **automatisée par le bandeau** (séquence séquentielle pilotée par `CMD`) :
la seule action humaine est de **bien placer le bandeau** — guidée par l'app, avec vérification
de contact (si une photodiode ne reçoit pas de signal → « repositionnez ce point »).

### 3.4 Mode « sans capteur » (accessibilité maximale)
1. **Pupillométrie caméra** : l'app demande 2 vidéos de 3 s (œil gauche, œil droit) avec flash →
   mesure du diamètre pupillaire et de la réactivité (approche validée par PupilScreen/PUPIL-POINT).
   Alerte si anisocorie > 1 mm ou réactivité altérée.
2. **Palpation guidée** : point douloureux localisé, déformation palpable, écoulement nez/oreilles,
   yeux de panda, signe de Battle — checklist illustrée (signes de fracture basilaire).
3. **Questionnaire clinique renforcé** : le triage reste conservateur (tout doute → orange).

---

## 4. Le moteur de triage clinique (cœur de l'app)

### 4.1 Entrées
- **Profil** : âge, anticoagulants/trouble de la coagulation, épilepsie, grossesse.
- **Incident** : heure du choc (IMU si bandeau, sinon déclarée), mécanisme (piéton renversé,
  éjection, chute > 1 m / > 5 marches, accident de la route, coup direct...), force d'impact si IMU.
- **Symptômes actuels** : perte de connaissance, amnésie (> 30 min ?), confusion, vomissements,
  céphalée (0–10), somnolence, convulsion, faiblesse/engourdissement, vision double,
  écoulement nez/oreilles, yeux de panda, hématotympan, signe de Battle, plaie/fracture visible,
  sensibilité à la lumière.
- **État de conscience (GCS simplifiée pour le proche)** : 9 questions binaires/choix multiples.
- **Mesures** : ΔOD par paire NIRS (2 longueurs d'onde), anisocorie pupillaire, pouls.

### 4.2 Règles (implémentées à l'identique des guidelines)
1. **Drapeaux rouges absolus** → 🔴 immédiat : GCS < 13, convulsion, signes de fracture basilaire,
   fracture ouverte/déprimée suspectée, pupilles inégales (hors cause connue), déficit moteur,
   inconscience, confusion qui s'aggrave, impossibilité d'être réveillé.
2. **Règle canadienne du TCC** (GCS 13–15, ≥ 16 ans) : haut risque → 🔴/🟠, risque intermédiaire → 🟠.
3. **New Orleans Criteria** (GCS = 15) → renforce 🟠.
4. **PECARN** (enfant < 18 ans) → questionnaire enfant + seuils spécifiques.
5. **Analyse NIRS** : ΔOD ≥ seuil (0,30 par défaut, configurable ; le constructeur signale dès
   ~0,05) sur **2 mesures consécutives** et **2 longueurs d'onde concordantes** →
   « suspicion d'hématome côté X » → 🔴. ΔOD 0,10–0,30 → 🟠 contrôle renforcé.
   Hématome du cuir chevelu déclaré → confiance réduite du point concerné (faux positif connu).
6. **Trajectoire temporelle** (le super-pouvoir de l'app) : chaque re-contrôle est **comparé au
   précédent** ; toute aggravation (céphalée +2 points, nouveau vomissement, somnolence accrue,
   asymétrie NIRS qui augmente) → escalade automatique d'un niveau + alerte.
7. **Contexte à risque** : anticoagulants → jamais 🟢 après un choc (recommandations cliniques).

### 4.3 Sortie du moteur
```
{
  "level": "orange",                       // red | orange | yellow | green
  "reasons": [                             // raisons explicites, traçables
    "Vomissements >= 2 (critère haut risque règle canadienne)",
    "NIRS: asymétrie paire temporale droite ΔOD=0.34 (760nm)"
  ],
  "advice": "Consultez un médecin sous 24 h...",
  "destination": "dispensaire|hopital|urgence_immediate",
  "confidence": 0.72,
  "followup_plan": [ {"h":2,"type":"recheck"}, {"h":6,"type":"recheck"} ],
  "disclaimer": "Outil d'aide à l'orientation, ne remplace pas un médecin."
}
```
**Grille de verdict**
| Niveau | Signification | Action |
|---|---|---|
| 🔴 rouge | Urgence possible (hématome suspecté, drapeau rouge clinique) | Urgences **maintenant**, appel contacts auto, rapport prêt |
| 🟠 orange | Risque intermédiaire | Consultation **< 24 h** + surveillance renforcée 2 h/6 h/24 h |
| 🟡 jaune | Symptomatique sans critère fort | Surveillance à la maison 72 h (2 h/6 h/24 h/48 h/72 h) |
| 🟢 vert | Aucun critère, NIRS symétrique | Repos 24 h + re-contrôles auto, éducation « signes d'alerte » |

---

## 5. L'assistant IA « Naya »

**Rôle** : conseiller médical virtuel du patient — jamais un substitut de diagnostic.
**Implémentation MVP** : moteur conversationnel déterministe en français (intentions +
dialogues guidés) adossé au moteur de triage → **100 % traçable et sûr**, fonctionne hors ligne.
**Interface `LLMProvider`** prévue : brancher un LLM (cloud ou local type Ollama) en V2 pour
la fluidité, **mais les réponses à risque passent toujours par les règles** (le LLM ne peut
jamais déclasser un verdict rouge).

Compétences de Naya :
- expliquer le fonctionnement de l'examen, étape par étape, vocabulaire simple ;
- collecter les symptômes en conversation libre (« j'ai mal derrière la tête depuis 1 h » →
  intensité/localisation/évolution extraites puis injectées dans le triage) ;
- interpréter les résultats (« pourquoi orange ? » → raisons re-listées en langage clair) ;
- répondre aux questions courantes : puis-je dormir ? alcool ? quand re-contrôler ? quels signes d'alerte ?
- **déclencher l'escalade** : tout message contenant un drapeau rouge (vomissements répétés,
  convulsion, aggravation, somnolence inhabituelle...) → verdict rouge + appel + notification contacts ;
- générer/envoyer le rapport au dispensaire.

**Garde-fous** : avertissement permanent ; bouton urgence accessible partout ;
tout doute → escalade ; journalisation de chaque conseil ; pas de conseils médicamenteux.

---

## 6. Les tâches automatiques (planificateur)

| Tâche | Déclencheur | Effet |
|---|---|---|
| **Plan de surveillance** | Après chaque verdict | Re-contrôles (questionnaire + NIRS optionnel) à 2 h / 6 h / 24 h / 48 h / 72 h selon niveau |
| **Re-contrôle à l'heure** | Boucle backend (30 s) | Notification + questionnaire rapide ; comparaison au bilan précédent |
| **Escalade automatique** | Aggravation au re-contrôle | Promote niveau + alerte contacts + « allez aux urgences » |
| **Non-réponse au re-contrôle** | 15 min sans réponse (≥ jaune) | Relance ; ≥ orange → alerte contact d'urgence |
| **Rappel signes d'alerte** | H+1, H+24 | Éducation : « si l'un de ces signes → urgence » |
| **Rapport d'incident** | Demande / escalade | Résumé imprimable : timeline, mesures NIRS, verdicts, raisons |
| **Bilan 72 h** | Fin de surveillance | « Surveillance terminée — que faire si ça revient ? » |

---

## 7. Confidentialité, sécurité, éthique

- Chiffrement au repos (SQLCipher en prod) et en transit (HTTPS/WSS) ; hébergement **local au
  dispensaire** possible (backend sur Raspberry Pi — aucun cloud obligatoire).
- Consentement explicite ; suppression totale en 1 bouton (RGPD-like).
- Contacts d'urgence alertés **uniquement** avec consentement (sauf incapacité).
- **Avertissement légal permanent** : outil d'aide à l'orientation — en cas de signes d'urgence,
  appeler les secours sans attendre.
- **Traçabilité** : chaque verdict = version du moteur + données d'entrée → reproductible/auditable.

## 8. Conformité et plan de validation (production)

| Étape | Contenu |
|---|---|
| 1. Recherche | Ce prototype : moteur de triage validé par tests unitaires sur les guidelines |
| 2. Études techniques | Banc d'essai NIRS (fantômes optiques), précision ΔOD, dérive LED, IMU calibré |
| 3. Essais cliniques | Cohorte « choc à la tête + scanner X de référence » ; validation questionnaire par urgentistes |
| 4. Réglementation | Classe IIa/IIb ; ISO 13485 (QM), IEC 62304 (logiciel), IEC 60601 (sécurité électrique), EN 62471 (sécurité photobiologique LED NIR) |
| 5. Homologation | FDA 510(k) / CE MDR / autorisations nationales ; dossiers d'équivalence (principe Infrascanner) |

**Positionnement réglementaire du MVP** : démonstrateur technique + outil d'éducation,
**pas** un dispositif médical certifié. Chaque écran le rappelle.

---

## 9. Modèle économique pour l'accessibilité

| Offre | Prix cible | Cible |
|---|---|---|
| App + assistant IA + mode sans capteur | **Gratuit** | Tout le monde, immédiatement |
| Bandeau CrâniCap (assemblé local) | **< 100 $** | Ménages, écoles, clubs sportifs, motos-taxis |
| Pack dispensaire (3 bandeaux + mode Pro + formation) | < 500 $ | Cliniques rurales, ONG |
| Firmware + schéma DIY | **Libre (open source)** | Fablabs, universités — fabrication locale, réparabilité |

> **Le principe directeur : le logiciel sauve des vies gratuitement dès aujourd'hui ;
> le matériel ajoute la mesure objective à moins de 100 $.**
