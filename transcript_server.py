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


@app.route("/vimeo-captions")
def vimeo_captions():
    vid   = request.args.get("v", "").strip()
    hash_ = request.args.get("h", "").strip()
    if not vid:
        return jsonify({"error": "Falta el ID del video"}), 400

    import urllib.request, json as _json, re as _re

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://vimeo.com/",
        "Origin": "https://vimeo.com",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Intento 1: página del player de Vimeo (extrae JSON incrustado)
    try:
        player_url = f"https://player.vimeo.com/video/{vid}"
        if hash_:
            player_url += f"?h={hash_}"
        req = urllib.request.Request(player_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Buscar text_tracks en el JSON de configuración incrustado
        m = _re.search(r'"text_tracks"\s*:\s*(\[.*?\])', html, _re.DOTALL)
        if m:
            tracks = _json.loads(m.group(1))
            if tracks:
                en = next((t for t in tracks if (t.get("lang") or t.get("language") or "").startswith("en")), tracks[0])
                vtt_url = en.get("url") or en.get("src") or ""
                if vtt_url.startswith("/"):
                    vtt_url = "https://player.vimeo.com" + vtt_url
                if vtt_url:
                    vtt_req = urllib.request.Request(vtt_url, headers={"User-Agent": headers["User-Agent"]})
                    with urllib.request.urlopen(vtt_req, timeout=10) as r2:
                        vtt_text = r2.read().decode("utf-8", errors="replace")
                    caps = _parse_vtt(vtt_text)
                    if caps:
                        print(f"✅ Vimeo subtítulos (player): {vid} ({len(caps)} segmentos)")
                        return jsonify({"captions": caps})

        # Buscar URL de VTT directamente
        m2 = _re.search(r'"(https://[^"]+\.vtt[^"]*)"', html)
        if m2:
            vtt_url = m2.group(1).replace("\\u0026", "&")
            vtt_req = urllib.request.Request(vtt_url, headers={"User-Agent": headers["User-Agent"]})
            with urllib.request.urlopen(vtt_req, timeout=10) as r2:
                vtt_text = r2.read().decode("utf-8", errors="replace")
            caps = _parse_vtt(vtt_text)
            if caps:
                print(f"✅ Vimeo subtítulos (vtt directo): {vid} ({len(caps)} segmentos)")
                return jsonify({"captions": caps})

        print(f"⚠️  Vimeo: no se encontraron text_tracks en el player para {vid}")
        return jsonify({"error": "no_captions"}), 404

    except Exception as e:
        print(f"⚠️  Vimeo error: {e}")
        return jsonify({"error": str(e)}), 500


def _format_json3(data):
    caps = []
    for ev in data.get("events", []):
        if not ev.get("segs"):
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue
        start = (ev.get("tStartMs", 0)) / 1000
        dur   = (ev.get("dDurationMs", 2000)) / 1000
        caps.append({"start": round(start,3), "end": round(start+dur,3),
                     "dur": round(dur,3), "text": text})
    return caps


def _parse_vtt(vtt):
    import re
    caps = []
    blocks = re.split(r'\n{2,}', vtt.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        m = None
        for line in lines:
            m = re.match(r'(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})', line)
            if m:
                break
        if not m:
            continue
        def t2s(ts):
            ts = ts.replace(',', '.')
            h, mn, s = ts.split(':')
            return int(h)*3600 + int(mn)*60 + float(s)
        start, end = t2s(m.group(1)), t2s(m.group(2))
        text_lines = [l for l in lines if '-->' not in l and not l.strip().isdigit() and l.strip()]
        text = ' '.join(text_lines).strip()
        if text:
            caps.append({"start": round(start,3), "end": round(end,3),
                         "dur": round(end-start,3), "text": text})
    return caps


@app.route("/transcript")
def transcript():
    vid = request.args.get("v", "").strip()
    if not vid:
        return jsonify({"error": "Falta el ID del video"}), 400

    # ── Intento 0a: Invidious (proxy de YouTube, evita bloqueos de IP) ───
    import urllib.request as _ur, json as _json, re as _re
    _INVIDIOUS = [
        "https://inv.nadeko.net",
        "https://invidious.privacydev.net",
        "https://invidious.slipfox.xyz",
        "https://yt.artemislena.eu",
    ]
    for _inst in _INVIDIOUS:
        try:
            _req = _ur.Request(f"{_inst}/api/v1/captions/{vid}",
                               headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(_req, timeout=8) as _r:
                _data = _json.loads(_r.read())
            _captions = _data.get("captions", [])
            if not _captions:
                continue
            _en = next((c for c in _captions if c.get("languageCode","").startswith("en")), _captions[0])
            _vtt_url = f"{_inst}{_en['url']}"
            _req2 = _ur.Request(_vtt_url, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(_req2, timeout=8) as _r2:
                _vtt = _r2.read().decode("utf-8", errors="replace")
            caps = _parse_vtt(_vtt)
            if caps:
                print(f"✅ Subtítulos (Invidious/{_inst}) para {vid} ({len(caps)} segmentos)")
                return jsonify({"captions": caps})
        except Exception as _e:
            print(f"⚠️  Invidious {_inst} falló: {_e}")
            continue

    # ── Intento 0b: scraping directo de la página de YouTube ─────────────
    try:
        _hdrs = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req0 = _ur.Request(f"https://www.youtube.com/watch?v={vid}", headers=_hdrs)
        with _ur.urlopen(req0, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = _re.search(r'"captionTracks":(\[.*?\])', html)
        if m:
            tracks = _json.loads(m.group(1))
            en = next(
                (t for t in tracks if t.get("languageCode","").startswith("en") and t.get("kind")!="asr"),
                next((t for t in tracks if t.get("languageCode","").startswith("en")), None)
            ) or (tracks[0] if tracks else None)
            if en and en.get("baseUrl"):
                cap_url = en["baseUrl"] + "&fmt=json3"
                req1 = _ur.Request(cap_url, headers={"User-Agent": _hdrs["User-Agent"]})
                with _ur.urlopen(req1, timeout=10) as r2:
                    data = _json.loads(r2.read())
                caps = _format_json3(data)
                if caps:
                    print(f"✅ Subtítulos (scraping) para {vid} ({len(caps)} segmentos)")
                    return jsonify({"captions": caps})
    except Exception as e:
        print(f"⚠️  Intento 0b (scraping) falló: {e}")

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
