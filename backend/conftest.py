# -*- coding: utf-8 -*-
"""Configuration pytest : ajoute le dossier backend/ au chemin Python.

Pourquoi ? pytest doit pouvoir faire `import app.triage`. Sans cette ligne,
il chercherait le paquet `app` depuis le dossier de test et échouerait.
C'est le mécanisme standard quand le code source n'est pas installé comme
paquet pip mais vit dans un sous-dossier du projet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
