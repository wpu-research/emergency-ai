"""EmergencyAI kiosk sunucusu (Faz 0 prototip).

Çalıştırma:  cd kiosk && python3 server.py   →  http://localhost:8787
Kamera ve mikrofon tarayıcıda yalnız güvenli bağlamda (localhost / https) açılır.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env(HERE.parent / ".env")

import speech   # noqa: E402  (env önce yüklenmeli)
import triage   # noqa: E402

ATLAS_DIR = Path(os.path.expanduser(os.environ.get("ATLAS_DIR", "~/tsync_exp/atlas")))
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="EmergencyAI Kiosk")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

def _atlas_asset(sub: str, name: str):
    """Atlas varlıklarını sunar; indirilmemiş Git LFS işaretçilerini 404 sayar."""
    path = (ATLAS_DIR / sub / name).resolve()
    if not str(path).startswith(str((ATLAS_DIR / sub).resolve())) or not path.is_file():
        raise HTTPException(404)
    if path.stat().st_size < 1024 and path.read_bytes().startswith(b"version https://git-lfs"):
        raise HTTPException(404, "LFS dosyası indirilmemiş")
    return FileResponse(path)


@app.get("/models/{name}")
def atlas_models(name: str):
    return _atlas_asset("models", name)


@app.get("/public/{name}")
def atlas_public(name: str):
    return _atlas_asset("public", name)


CL = triage.client()
SESSIONS: dict[str, dict] = {}


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/atlas/avatar_renderer.js")
def atlas_renderer():
    return FileResponse(ATLAS_DIR / "web" / "avatar_renderer.js", media_type="text/javascript")


class Vitals(BaseModel):
    hr: float | None = None
    spo2: float | None = None
    sbp: float | None = None
    dbp: float | None = None
    temp: float | None = None


class TurnIn(BaseModel):
    session_id: str
    text: str | None = None
    audio_b64: str | None = None
    audio_mime: str | None = None
    vitals: Vitals | None = None


def _vitals_dict(v: Vitals | None) -> dict:
    return {k: val for k, val in (v.model_dump() if v else {}).items() if val is not None}


def _vitals_text(v: dict) -> str:
    names = {"hr": "nabız", "spo2": "SpO2 %", "sbp": "sistolik TA", "dbp": "diyastolik TA", "temp": "ateş °C"}
    return ", ".join(f"{names[k]} {val:g}" for k, val in v.items()) if v else ""


def _log(sid: str, event: dict) -> None:
    with open(DATA_DIR / f"{sid}.jsonl", "a") as f:
        f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"), **event}, ensure_ascii=False) + "\n")


@app.post("/api/session")
def new_session():
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"history": [], "findings": {}, "consent": "unknown", "started": time.time()}
    _log(sid, {"event": "session_start"})
    return {"session_id": sid, "say": triage.GREETING, "buttons": triage.GREETING_BUTTONS,
            **speech.speak_payload(triage.GREETING)}


@app.post("/api/turn")
def turn(body: TurnIn):
    s = SESSIONS.get(body.session_id)
    if s is None:
        raise HTTPException(404, "Oturum bulunamadı")
    timing = {}
    text = (body.text or "").strip()
    audio = None
    if body.audio_b64:
        audio = base64.b64decode(body.audio_b64)
        ext = ".webm" if "webm" in (body.audio_mime or "webm") else ".ogg" if "ogg" in (body.audio_mime or "") else ".wav"
        text, timing["stt_ms"] = speech.transcribe(audio, ext)
        timing["stt_ms"] = round(timing["stt_ms"])
    if not text:
        say = "Sizi duyamadım. Tekrar söyler misiniz?"
        return {"heard": "", "say": say, "buttons": s.get("last_buttons", []), "findings": s["findings"],
                "engine": triage.decide(s["findings"], _vitals_dict(body.vitals)) if s["findings"] else None,
                "timing": timing, **speech.speak_payload(say)}

    vitals = _vitals_dict(body.vitals)
    s["history"].append({"role": "user", "content": text})
    data, ms = triage.ask_claude(CL, s["history"], _vitals_text(vitals))
    timing["claude_ms"] = round(ms)
    s["history"].append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})

    # sözlü onay: onayın verildiği turun sesi ve metni kanıt olarak saklanır
    if data["consent"] == "given" and s["consent"] != "given":
        s["consent"] = "given"
        if audio:
            (DATA_DIR / f"{body.session_id}-onay.webm").write_bytes(audio)
        _log(body.session_id, {"event": "consent", "utterance": text, "notice": triage.GREETING})
    elif data["consent"] == "refused":
        s["consent"] = "refused"

    s["findings"] = data
    s["last_buttons"] = data["buttons"]
    engine = triage.decide(data, vitals)
    _log(body.session_id, {"event": "turn", "heard": text, "findings": data, "engine": engine, "vitals": vitals})
    payload = speech.speak_payload(data["say"])
    timing.update(tts_ms=payload.pop("tts_ms"), lipsync_ms=payload.pop("lipsync_ms"))
    return {"heard": text, "say": data["say"], "buttons": data["buttons"], "findings": data,
            "engine": engine, "consent": s["consent"], "timing": timing, **payload}


@app.post("/api/end/{sid}")
def end(sid: str):
    s = SESSIONS.pop(sid, None)
    if s:
        _log(sid, {"event": "session_end", "findings": s["findings"]})
    return {"ok": True}


if __name__ == "__main__":
    print("Whisper modeli yükleniyor…")
    speech.load_whisper()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("KIOSK_PORT", 8787)))
