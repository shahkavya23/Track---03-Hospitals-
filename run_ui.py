# Purpose: Root launcher script for the RAKSHA React + TypeScript Frontend & API Server.
"""Launch RAKSHA React + TypeScript Frontend and Backend API Server."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure RAKSHA_SECRET is set
if "RAKSHA_SECRET" not in os.environ or not os.environ["RAKSHA_SECRET"].strip():
    os.environ["RAKSHA_SECRET"] = "RAKSHA-HACKATHON-DEAN-KEY-2026-STABLE"

from backend_server import HOST, PORT, run_server


def open_browser(url: str) -> None:
    time.sleep(1.2)
    print(f"\n[+] Opening RAKSHA Dashboard in your browser: {url}")
    webbrowser.open(url)


def main() -> None:
    print("=" * 72)
    print("  RAKSHA — Multilingual Healthcare Privacy Firewall")
    print("  Yugaantar DevForge Track 3: Secret Wards | Hackathon Final")
    print("=" * 72)
    print(f"[*] Environment Secret: {os.environ['RAKSHA_SECRET'][:4]}...{os.environ['RAKSHA_SECRET'][-4:]}")
    print(f"[*] Backend Server:     http://{HOST}:{PORT}")
    print(f"[*] React UI:           http://{HOST}:{PORT}/ (Production Build)")
    print(f"[*] React Dev Server:   cd frontend && npm run dev (http://localhost:5173)")
    print("=" * 72)

    url = f"http://{HOST}:{PORT}/"
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    run_server()


if __name__ == "__main__":
    main()
