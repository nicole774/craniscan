# -*- coding: utf-8 -*-
"""Point d'entrée du serveur CrâniScan.

Usage :
    python backend/run.py
    CRANISCAN_FAST_SCHED=1 python backend/run.py     # mode démo (suivi 72 h accéléré)
"""
import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("CRANISCAN_HOST", "127.0.0.1")
    port = int(os.environ.get("CRANISCAN_PORT", "8000"))
    print("=" * 68)
    print("  🧠  CrâniScan — serveur démarré")
    print(f"      App mobile (PWA) :  http://{host}:{port}")
    print(f"      Documentation API :  http://{host}:{port}/docs")
    print("      Mode démo (suivi accéléré) :", bool(os.environ.get("CRANISCAN_FAST_SCHED")))
    print("=" * 68)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
