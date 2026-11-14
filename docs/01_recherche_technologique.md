# CrâniScan — Recherche technologique
**Projet : CrâniScan — dépistage accessible des lésions cérébrales après un choc à la tête**
*Date : 2026-11-14 — Document de recherche pré-conception*

---

## 1. Le problème clinique

Après un traumatisme crânien (accident de la route, chute, choc sportif, agression), les lésions
les plus dangereuses sont **invisibles à l'œil nu** :

| Lésion | Mécanisme | Danger |
|---|---|---|
| **Hématome épidural** | Saignement entre le crâne et la dure-mère (artère méningée moyenne) | Peut être **silencieux des heures** (« intervalle lucide »), puis compression brutale → mort en 1–2 h sans intervention |
| **Hématome sous-dural** | Saignement sous la dure-mère, souvent à évolution lente | Aggravation progressive sur 24–72 h, chez la personne âgée parfois sur plusieurs jours |
| **Contusion / œdème cérébral** | Gonflement du tissu cérébral | Hausse de la pression intracrânienne (PIC) |
| **Fracture du crâne avec déplacement** | Impact fort | Risque de lésion sous-jacente |

**Le vrai problème n'est pas le diagnostic (le scanner X existe) — c'est l'ACCÈS :**
1. La personne hésite à consulter : « ça va passer », peur des frais, pas de transport.
2. Le scanner X (CT) coûte cher, n'existe pas partout, expose aux radiations.
3. Les blessures visibles (plaies, fractures de membres) monopolisent l'attention des services d'urgence, alors qu'un crâne « intact en apparence » peut cacher une hémorragie mortelle.
4. Il n'existe quasiment aucun outil de dépistage grand public utilisable **à la maison, dans la rue, dans un bus**.

> **Objectif du projet** : un appareil + une app qui répondent en 5 minutes à la question
> « **Suis-je en danger ? Dois-je aller à l'hôpital maintenant ?** » — sans médecin, sans scanner, sans déplacement.

---

## 2. Critères de sélection des technologies

Une solution « accessible à toute personne » doit respecter **6 critères** :

| # | Critère | Seuil cible |
|---|---|---|
| C1 | **Coût total** | < 100 €/$ pour l'appareil grand public (composants) |
| C2 | **Non-invasif & sans radiation** | Aucune exposition dangereuse, utilisable répétitivement |
| C3 | **Utilisable par un non-médical** | Placement guidé pas à pas par l'app, aucun réglage technique |
| C4 | **Résultat en < 5 min** | Temps d'attention d'une personne stressée/blessée |
| C5 | **Connectable** | Bluetooth → smartphone (l'app fait l'intelligence, l'appareil reste simple et bon marché) |
| C6 | **Fonctionne sans l'appareil** | Mode « sans capteur » par questionnaire + caméra du téléphone (tout le monde n'a pas le bandeau) |

---

## 3. Panorama des technologies existantes

### 3.1 Spectroscopie proche infrarouge (NIRS) — ⭐ TECHNOLOGIE CENTRALE RETENUE

**Principe physique** : le sang extravasé (hors vaisseaux) absorbe beaucoup plus la lumière proche
infrarouge (~760–850 nm) que le sang circulant. On éclaire **deux points symétriques du crâne**
(gauche/droite) et on compare l'absorption optique (**ΔOD**, différence de densité optique).
Une asymétrie significative = suspicion d'hématome du côté qui absorbe le plus.

**Preuves (dispositif de référence : Infrascanner 2000/2500, InfraScan Inc., FDA-cleared)** :
- Détecte les hématomes **> 3 mm sous la surface**, ~3 cm de diamètre — les plus dangereux en urgence.
- 98 % des patients avec hématome intracrânien présentaient ΔOD > 0,05 (livre blanc constructeur).
- Validation pédiatrique (Kirschen et al. 2021) : **sensibilité ≈ 88 %, spécificité ≈ 90 %** vs scanner X.
- Résultat **temps réel, sans radiation**, utilisable en triage pré-hospitalier (développé avec l'armée américaine).
- **Limites assumées** : hématomes profonds loin de la surface (crâne épais), bilatéraux (asymétrie nulle → faux négatif), région médiane/fosse postérieure, hématome du cuir chevelu (faux positif) → l'app croise donc TOUJOURS le NIRS avec les règles cliniques et le questionnaire.

**Coût** : l'Infrascanner institutionnel vaut ~20 000–30 000 $. **Mais les composants sont triviaux** :
des LED NIR à 2 longueurs d'onde + photodiodes. Projets scientifiques ouverts :
- **FlexNIRS** (Wu et al., 2022, *NeuroImage*) : dispositif fNIRS sans fil **≈ 50 $/unité** à 1 000 exemplaires.
- **DIY fNIRS** (Tsow et al., 2021, *Sensors*) : système portable DIY à LED bas coût + photodiodes silicium.
- **OpenNIRScap** (2025, arXiv) : casque NIRS ouvert à 24 cartes capteurs émetteur dual-longueur d'onde + photodiode.
- Dispositif ouvert 2024 à LED **740/850 nm** pensé pour l'industrialisation à bas coût.

➜ **Conclusion : la mesure qui sauve des vies est faisable à moins de 100 $ de composants.**
Le prix actuel vient du statut « dispositif médical institutionnel », pas de la physique.

### 3.2 Échographie portable (niveau « professionnel de santé », extension du système)

- **Butterfly iQ+** : sonde unique « ultrasound-on-chip » branchée sur smartphone, **≈ 2 699 $** (occasion ≈ 1 888 $), FDA-cleared, ~2 000 $/an d'abonnement selon formule.
- Mesure clé accessible : **diamètre de la gaine du nerf optique (ONSD)** par échographie oculaire —
  une **ONSD ≥ 5–5,7 mm** (mesurée à 3 mm derrière l'œil) signe une **PIC > 20 mmHg**
  (VPP ≈ 93 %, VPN ≈ 45 %, Kshirsagar 2024). Idéal pour les infirmiers/cliniques.
- ➜ **Rôle dans CrâniScan** : mode « Pro » optionnel (l'infirmier de quartier branche sa sonde, l'app guide la mesure ONSD et l'intègre au rapport).

### 3.3 Pupillométrie par caméra de smartphone — ⭐ MODE « SANS CAPTEUR »

- L'**anisocorie** (pupilles inégales) et la **réactivité pupillaire altérée** sont des marqueurs établis
  d'hypertension intracrânienne. Le pupillomètre de référence (NeurOptics NPi-200) coûte ~10 000 $.
- Des apps de recherche smartphone existent déjà et sont validées :
  **PupilScreen** (Univ. of Washington, vidéo du réflexe photomoteur pour le TCC),
  **PUPIL-POINT** (2025 : hors-ligne, téléphones bas de gamme, pensé pour les pays à ressources limitées),
  **SmartPLR** (2025, IA), **MindMirror** (2024, validé sur 25 volontaires).
- ➜ **Conclusion : la caméra du téléphone du patient suffit pour un premier filtre pupillaire.**
  Zéro matériel supplémentaire → accessibilité maximale.

### 3.4 Capteurs d'impact (IMU / accéléromètre)

- Bandeaux et casques avec accéléromètres tri-axes existent depuis longtemps (GForceTracker,
  HIT Recognition, Team Wendy Smart Headband à 8 accéléromètres tri-axes).
- La littérature (revue systématique PMC5384819) rappelle qu'ils mesurent l'**exposition** aux impacts,
  pas un diagnostic — mais la **force du choc (g + rotation)** est un facteur de risque direct
  intégré à notre moteur de triage (« mécanisme dangereux » de la règle canadienne).
- Un prototype **open-source bas coût 2025** (ScienceDirect) mesure accélération linéaire + vitesse
  angulaire en temps réel.
- ➜ **Rôle** : IMU dans le bandeau → l'app sait SI le choc était violent (chute > 1 m, > 5 marches,
  accident de la route) et ENREGISTRE l'heure précise du choc (indispensable aux règles cliniques « à 2 h »).

### 3.5 Autres pistes évaluées (non retenues pour le MVP)

| Technologie | Verdict | Raison |
|---|---|---|
| EEG portable (BrainScope) | ❌ MVP | Validé FDA mais coûteux, nécessite un environnement calme + expertise |
| EEG grand public (Muse, OpenBCI) | ⏳ V2 | Intéressant en surveillance, pas en dépistage aigu |
| Imagerie micro-ondes cérébrale (type EMBLA/Micrima) | ⏳ Recherche | Prometteur mais pas encore miniaturisable à < 100 $ |
| Scanner X / IRM | ✅ Référence | Le gold standard auquel nous renvoyons — pas portable |

---

## 4. Les règles cliniques validées (l'intelligence de l'app)

L'app n'invente rien en médecine : elle **implémente les règles de décision validées**
utilisées par les urgentistes du monde entier :

| Règle | Contenu | Performance |
|---|---|---|
| **Échelle de Glasgow (GCS)** | Ouverture des yeux + réponse verbale + réponse motrice | Standard mondial du TCC |
| **Règle canadienne du TCC (CCHR, Stiell 2001)** | À appliquer si GCS 13–15, âge ≥ 16 ans : **haut risque** = GCS < 15 à 2 h, fracture ouverte/déprimée suspectée, signes de fracture basilaire (hématotympan, « yeux de panda », otorrhée/rhinorrhée de LCR, signe de Battle), vomissements ≥ 2, âge ≥ 65 ans ; **risque intermédiaire** = amnésie > 30 min avant l'impact, mécanisme dangereux (piéton renversé, éjection, chute > 1 m / 5 marches) | **100 % de sensibilité** pour le besoin de neurochirurgie ; 98,4 % pour lésion cliniquement importante |
| **New Orleans Criteria** (GCS = 15) | Céphalée, vomissement, âge > 60, intoxication, traumatisme visible au-dessus des clavicules, convulsion, amnésie | Sensibilité ~100 % pour lésions CT |
| **PECARN** (enfant < 18 ans) | GCS ≤ 14, palpation de fracture, signes basilarité, hématome du scalp (sauf frontal chez < 2 ans, sauf occipital/pariétal/temporal pour ≥ 2 ans...), comportement anormal, vomissements, mécanisme sévère | Standard pédiatrique |

➜ **Conception** : le questionnaire de l'app pose les questions DANS l'ordre de ces règles.
Le résultat est une **couleur + une liste de raisons explicites** (traçabilité, confiance, apprentissage).

---

## 5. Architecture matérielle retenue — « CrâniCap »

Un **bandeau souple ergonomique** (comme une visière/bande de sport), taille unique ajustable :

```
┌──────────────────────────────────────────────────────────┐
│  BANDEAU CrâniCap                                        │
│  ┌────────────┐                              ┌────────┐ │
│  │ Paire 1    │   Paire 2 (front)            │ Paire 3│ │
│  │ temporale  │   F-LG ──────── F-DR         │ pariétale│
│  │ T-LG ─DR   │                              │ P-LG─DR│ │
│  └────────────┘                              └────────┘ │
│   Paire 4 (occipitale)          [IMU]  [BLE ESP32-C3]   │
│   O-LG ──────── O-DR            [PPG]  [batterie USB-C] │
└──────────────────────────────────────────────────────────┘
   Chaque « capteur » = LED NIR 760 nm + LED 850 nm + photodiode
```

- **8 points de mesure NIR** (4 paires symétriques : temporal, frontal, pariétal, occipital)
  + 1 point de référence. Mesure séquentielle automatisée en ~2 min.
- **IMU** (MPU-6050 ou équivalent) : détecte/enregistre les impacts (g, rotation, horodatage).
- **PPG** (le capteur du pouls, comme les montres) : fréquence cardiaque + signal exploitable
  pour la surveillance.
- **ESP32-C3** : le cerveau du bandeau, transmet en **Bluetooth LE** une trame JSON simple.
- **BOM grand public** : LED NIR + photodiodes ≈ 15 $, ESP32-C3 ≈ 8 $, IMU ≈ 3 $, PPG ≈ 4 $,
  textile + mousse + batterie ≈ 20 $, câblage/assemblage ≈ 15 $ → **≈ 55–70 $ de composants**
  (cohérent avec FlexNIRS à ~50 $/unité en volume).
- **Voie DIY** : schéma ouvert (type Arduino/ESP32) pour les fablabs/makers locaux —
  même protocole BLE, donc même app.

**Protocole BLE (GATT)** — service `0000CRAN-...`, caractéristiques :
`NIR_FRAME` (JSON : `{led:760|850, pair:1..4, side:L|R, od:0.42, ref:0.31}`), `IMU_EVENT`,
`PPG_STREAM`, `CMD` (démarrage/arrêt de l'examen), `STATUS` (batterie, température peau).

---

## 6. Synthèse de la décision

| Élément | Choix | Coût | Justification |
|---|---|---|---|
| Détection hématome | **NIRS asymétrique 760/850 nm, 4 paires symétriques** | ~30 $ | Principe validé FDA (Infrascanner) ; composants bon marché ; sans radiation |
| Niveau pro (clinique) | **Échographie portable — mesure ONSD guidée** | 2 700 $ (optionnel) | VPP 93 % pour PIC élevée ; pour infirmiers, pas pour le grand public |
| Mode sans capteur | **Pupillométrie caméra + questionnaire clinique** | 0 $ | Tout le monde a un téléphone ; apps de recherche déjà validées |
| Mécanisme du choc | **IMU dans le bandeau + questions guidées** | ~3 $ | Alimente « mécanisme dangereux » + horodatage précis |
| Intelligence | **Règles cliniques validées (CCHR, NOLA, PECARN, GCS) + assistant IA** | — | Traçable, explicable, conforme aux pratiques d'urgence |
| Liaison | **BLE → app PWA mobile** | — | L'app porte l'intelligence → matériel simple → matériel bon marché |

> **Positionnement honnête** : CrâniScan est un **outil de triage/orientation**, pas un scanner X.
> Il dit : « vert — surveillance à la maison » / « orange — consultez sous 24 h » /
> « rouge — urgence, allez à l'hôpital MAINTENANT ». Il peut faire des erreurs des deux côtés
> (faux négatifs : hématome profond/bilatéral ; faux positifs : hématome du scalp) —
> c'est pourquoi il **croise 4 sources de données** (NIRS + pupilles + questionnaire clinique + IMU)
> et renvoie **toujours** vers un médecin en cas de doute.

---

## 7. Sources principales

- Infrascanner 2000/2500 (NIRS, hématome intracrânien, ΔOD, sensibilité/spécificité) — InfraScan Inc. ;
  validation pédiatrique : Kirschen et al. 2021 (PMC8203002) ; Yuksen et al. 2020 ;
  Cardona-Collazos 2025 ; Trillo Ordonez 2025. Politique Anthem MED.00116 (statut remboursement).
- Règle canadienne du TCC : [MDCalc](https://www.mdcalc.com/calc/608/canadian-ct-head-injury-trauma-rule),
  [Medscape](https://reference.medscape.com/calculator/33/canadian-ct-head-rule), Stiell et al., *Lancet* 2001.
- ONSD / PIC : [StatPearls NCBI](https://www.ncbi.nlm.nih.gov/books/NBK554479) ; Wang 2019 ;
  Kshirsagar 2024 (POCUS au lit du patient) ; Radiopaedia (cutoffs 4,8–6,2 mm).
- Échographie portable : Butterfly Network (iQ+/iQ3, 2 699 $, « Ultrasound-on-Chip »).
- Capteurs d'impact : revue systématique [PMC5384819](https://pmc.ncbi.nlm.nih.gov/articles/PMC5384819) ;
  prototype open-source bas coût [ScienceDirect 2025](https://www.sciencedirect.com/science/article/pii/S2665917425000571) ;
  HIT Recognition, GForceTracker, Team Wendy Smart Headband.
- Pupillométrie smartphone : SmartPLR 2025 (PMC12613743) ; MindMirror 2024 ;
  PUPIL-POINT 2025 (hors-ligne, téléphones bas de gamme) ; PupilScreen (Univ. of Washington) ;
  comparaison IA pupillométrie Jaworski 2025 / J Neurotrauma 2023.
- NIRS open-source bas coût : FlexNIRS (Wu et al. 2022, *NeuroImage*, ~50 $/unité) ;
  DIY fNIRS (Tsow et al. 2021, *Sensors*) ; dispositif ouvert 740/850 nm (*Spectroscopy Online*, 2024) ;
  OpenNIRScap (arXiv 2025) ; revue Lahade et al. 2026 (PMC).
