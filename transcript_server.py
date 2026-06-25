#!/usr/bin/env python3
"""
Shadow the Scene – Transcript Server
=====================================
Fetches YouTube subtitles server-side and serves the app at http://localhost:5000

SETUP (one-time):
    pip install flask youtube-transcript-api

RUN:
    python3 transcript_server.py
"""

import os
import sys
import webbrowser
import threading
import time
from pathlib import Path

# ── dependency check ──────────────────────────────────────────────────────────
try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("\n❌  Falta Flask. Instálalo con:\n")
    print("       pip3 install flask youtube-transcript-api\n")
    sys.exit(1)

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("\n❌  Falta youtube-transcript-api. Instálalo con:\n")
    print("       pip3 install flask youtube-transcript-api\n")
    sys.exit(1)

# ── app ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def index():
    folder = Path(__file__).parent
    html_file = folder / "shadow-the-scene.html"
    if not html_file.exists():
        return f"<h2>No se encontró shadow-the-scene.html en {folder}</h2>", 404
    return send_from_directory(str(folder), "shadow-the-scene.html")


@app.route("/transcript")
def transcript():
    vid = request.args.get("v", "").strip()
    if not vid:
        return jsonify({"error": "Falta el ID del video"}), 400

    langs = ["en", "en-US", "en-GB", "en-CA", "en-AU"]
    api = YouTubeTranscriptApi()

    # ── Intento 1: fetch directo con preferencia de idioma ────────────────
    try:
        raw = api.fetch(vid, languages=langs)
        caps = _format(raw)
        if caps:
            print(f"✅ Subtítulos obtenidos para {vid} ({len(caps)} segmentos)")
            return jsonify({"captions": caps})
    except Exception as e:
        print(f"⚠️  Intento 1 falló: {e}")

    # ── Intento 2: listar y elegir la mejor transcripción disponible ──────
    try:
        tlist = api.list(vid)
        chosen = None

        for t in tlist:
            if t.language_code.startswith("en") and not t.is_generated:
                chosen = t
                break
        if not chosen:
            for t in tlist:
                if t.language_code.startswith("en"):
                    chosen = t
                    break
        if not chosen:
            for t in tlist:
                chosen = t
                break

        if chosen:
            raw = chosen.fetch()
            caps = _format(raw)
            if caps:
                print(f"✅ Subtítulos obtenidos para {vid} via lista ({len(caps)} segmentos)")
                return jsonify({"captions": caps})

    except Exception as e:
        print(f"⚠️  Intento 2 falló: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "no_transcript_found"}), 404


def _format(raw):
    """Convierte la respuesta de youtube-transcript-api al formato que usa la app.
    Compatible con versiones 0.x (dicts) y 1.x (objetos)."""
    captions = []
    for item in raw:
        try:
            # Versión 1.x — objetos con atributos
            if hasattr(item, "text"):
                text  = str(item.text).replace("\n", " ").strip()
                start = float(item.start)
                dur   = float(getattr(item, "duration", 2.0))
            # Versión 0.x — diccionarios
            elif isinstance(item, dict):
                text  = str(item.get("text", "")).replace("\n", " ").strip()
                start = float(item.get("start", 0))
                dur   = float(item.get("duration", 2))
            else:
                continue

            if not text:
                continue

            captions.append({
                "start": round(start, 3),
                "end":   round(start + dur, 3),
                "dur":   round(dur, 3),
                "text":  text,
            })
        except Exception:
            continue
    return captions


# ── startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    url  = f"http://localhost:{port}"

    print("\n" + "═" * 52)
    print("  🎧  Shadow the Scene — Listening Lab Server")
    print("═" * 52)
    print(f"\n  ✅  Servidor corriendo en  {url}")
    print(f"  📂  Archivos en  {Path(__file__).parent}")
    print(f"\n  Abre tu navegador en:")
    print(f"  → {url}\n")
    print("  Presiona Ctrl+C para detener.\n")
    print("═" * 52 + "\n")

    def _open():
        time.sleep(1.2)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False)
