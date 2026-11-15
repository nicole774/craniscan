# -*- coding: utf-8 -*-
"""
===============================================================================
CrâniScan — PROTOCOLE BLE « CrâniCap » + CAPTEUR VIRTUEL
===============================================================================
Ce fichier joue DEUX rôles :

1. DÉFINIR LE PROTOCOLE réel qui sera parlé par le vrai bandeau (ESP32-C3) :
   mêmes UUIDs GATT, mêmes trames JSON. Le jour où le matériel physique
   existe, l'app n'a RIEN à changer — c'est le principe « contract first » :
   on fixe le contrat d'interface AVANT que le matériel existe.

2. SIMULER le bandeau (VirtualCraniCap) pour :
   - développer/tester l'app sans matériel ;
   - former les utilisateurs (mode « démonstration ») ;
   - tester les 4 scénarios cliniques de façon REPRODUCTIBLE (un vrai
     capteur n'est jamais deux fois identique) ;
   - servir de référence d'implémentation pour les fablabs qui construiront
     le firmware réel.

Structure d'une mesure réelle (cf. docs/02_cahier_de_conception.md §3.3) :
   {"t": ms, "led": 760, "pair": 1, "side": "L", "od": 0.412}
   pair : 1=temporal, 2=frontal, 3=pariétal, 4=occipital
===============================================================================
"""

import asyncio
import random
import time
from typing import AsyncGenerator, Dict, List

# ----------------------------------------------------------------------------- 
# Contrat BLE (à copier tel quel dans le firmware ESP32-C3)
# -----------------------------------------------------------------------------

BLE_SERVICE_UUID = "6e40c0a1-b5a3-f393-e0a9-e50e24dcca9e"
UUID = {
    "NIR":    "6e40c0a2-b5a3-f393-e0a9-e50e24dcca9e",  # mesures ΔOD
    "IMU":    "6e40c0a3-b5a3-f393-e0a9-e50e24dcca9e",  # événements d'impact
    "PPG":    "6e40c0a4-b5a3-f393-e0a9-e50e24dcca9e",  # pouls
    "CMD":    "6e40c0a5-b5a3-f393-e0a9-e50e24dcca9e",  # commandes app → bandeau
    "STATUS": "6e40c0a6-b5a3-f393-e0a9-e50e24dcca9e",  # batterie, contact peau
}

PAIR_NAMES = {1: "temporale", 2: "frontale", 3: "pariétale", 4: "occipitale"}

# Niveaux de densité optique réalistes (absorption NIR du tissu crânien sain)
BASE_OD = {760: 0.40, 850: 0.55}

SCENARIOS: Dict[str, Dict[str, float]] = {
    # ΔOD (asymétrie) par paire pour chaque scénario de démonstration
    "normal":     {1: 0.01, 2: 0.02, 3: 0.01, 4: 0.02},
    "borderline": {1: 0.19, 2: 0.06, 3: 0.04, 4: 0.02},   # zone à surveiller
    "hematoma":   {1: 0.38, 2: 0.05, 3: 0.04, 4: 0.03},   # temporale droite
    "diffuse":    {1: 0.12, 2: 0.14, 3: 0.11, 4: 0.10},   # bilatéral/diffus (limite connue du NIRS)
}


def _noise(scale: float = 0.008) -> float:
    """Bruit de mesure réaliste : un capteur optique n'est jamais stable au
    millième près. Sans bruit, l'app semblerait fonctionner avec un capteur
    parfait et échouerait sur du vrai matériel."""
    return random.gauss(0, scale)


class VirtualCraniCap:
    """Bandeau virtuel : produit le même flux de trames que le vrai matériel.

    Le vrai bandeau mesure SEQUENTIELLEMENT : allume LED 760 sur la paire 1
    côté gauche → photodiode → trame → côté droit → trame → LED 850 → etc.
    On reproduit ce rythme (~120 ms par trame) pour que l'app et ses timers
    soient testés dans les conditions réelles.
    """

    def __init__(self, scenario: str = "normal"):
        self.scenario = scenario if scenario in SCENARIOS else "normal"
        self.battery = random.randint(60, 98)
        self.bpm = random.randint(66, 92)

    async def stream_exam(self) -> AsyncGenerator[Dict, None]:
        """Génère toutes les trames d'un examen complet (~3 min en réel,
        accéléré ici à ~25 s pour la démonstration)."""
        deltas = SCENARIOS[self.scenario]
        # Le côté « chargé » du ΔOD : l'hématome est localisé d'un seul côté.
        heavy_side = "R" if self.scenario in ("hematoma", "borderline") else None

        for pair in (1, 2, 3, 4):
            # Vérification de contact (comme le vrai bandeau : la photodiode
            # doit voir de la lumière réfléchie, sinon « repositionnez »).
            yield {"type": "status", "pair": pair, "message":
                   f"Paire {pair} ({PAIR_NAMES[pair]}) — contact OK, mesure en cours…"}
            for led in (760, 850):
                for side in ("L", "R"):
                    od = BASE_OD[led] + _noise()
                    if heavy_side == side:
                        od += deltas[pair] / 2
                    else:
                        od -= deltas[pair] / 2
                    await asyncio.sleep(0.18)  # rythme réel d'acquisition
                    yield {"type": "nir", "t": int(time.time() * 1000),
                           "led": led, "pair": pair, "side": side,
                           "od": round(od, 3)}
            await asyncio.sleep(0.3)

        # Événement IMU (le choc initial enregistré par le bandeau) + pouls.
        yield {"type": "imu", "t": int(time.time() * 1000),
               "g_force": round(random.uniform(2.2, 5.5), 1),
               "rot": round(random.uniform(80, 160), 0)}
        self.bpm += random.randint(-3, 3)
        yield {"type": "ppg", "t": int(time.time() * 1000),
               "bpm": self.bpm, "quality": round(random.uniform(0.85, 0.98), 2)}
        yield {"type": "status", "message": "Examen terminé ✔",
               "battery": self.battery}

    @staticmethod
    def measurements_from_frames(frames: List[Dict]) -> List[Dict]:
        """Extrait les mesures NIR utilisables par le moteur de triage."""
        return [{"pair": f["pair"], "led": f["led"], "side": f["side"], "od": f["od"]}
                for f in frames if f.get("type") == "nir"]

    @staticmethod
    def imu_event(frames: List[Dict]) -> Dict:
        for f in frames:
            if f.get("type") == "imu":
                return f
        return {}
