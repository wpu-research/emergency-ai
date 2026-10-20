"""Konuşma tanıma (faster-whisper), Türkçe TTS ve TranscriptionSync dudak senkronu."""
from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

try:
    from transcription_sync import VisemeStream
except ImportError:  # yerel klon: ~/src/transcription-sync
    sys.path.insert(0, os.path.expanduser(os.environ.get("TSYNC_SRC", "~/src/transcription-sync/src")))
    from transcription_sync import VisemeStream

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge")          # edge | piper
EDGE_VOICE = os.environ.get("EDGE_VOICE", "tr-TR-EmelNeural")
PIPER_MODEL = os.path.expanduser(os.environ.get("PIPER_MODEL", "~/.local/share/piper/voices/tr_TR-dfki-medium.onnx"))
FPS = 60

_whisper = None


def load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        try:
            _whisper = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
        except Exception:
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> tuple[str, float]:
    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(audio_bytes)
        f.flush()
        segs, _ = load_whisper().transcribe(
            f.name, language="tr", vad_filter=True, beam_size=1,
            initial_prompt="Acil servis triaj görüşmesi. Onaylıyorum. Göğüs ağrısı, nefes darlığı, ateş.",
        )
        text = " ".join(s.text.strip() for s in segs).strip()
    return text, (time.perf_counter() - t0) * 1000


def _to_wav(src: str, dst: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "24000", dst], check=True)


def synthesize(text: str) -> tuple[bytes, str, float]:
    """Returns (wav bytes, engine used, ms). edge-tts başarısız olursa yerel Piper'a düşer."""
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "out.wav")
        engine = TTS_ENGINE
        if engine == "edge":
            try:
                import edge_tts
                mp3 = os.path.join(d, "out.mp3")
                asyncio.run(edge_tts.Communicate(text, EDGE_VOICE, rate="+4%").save(mp3))
                _to_wav(mp3, wav)
            except Exception:
                engine = "piper"
        if engine == "piper":
            raw = os.path.join(d, "raw.wav")
            subprocess.run(["piper", "-m", PIPER_MODEL, "-f", raw], input=text.encode(), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _to_wav(raw, wav)
        data = Path(wav).read_bytes()
    return data, engine, (time.perf_counter() - t0) * 1000


_TR = str.maketrans({"ı": "i", "İ": "i", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
                     "ç": "c", "Ç": "c", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "â": "a", "î": "i", "û": "u"})


def lipsync(text: str, wav_bytes: bytes) -> dict:
    """TSYNC metin→viseme karelerini ses süresine yayar, ses zarfıyla susmaları kapatır.
    Çıktı Atlas renderer'ın playSpeech biçimidir: {channel: [değerler]} @ 60 fps."""
    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav_bytes)
        f.flush()
        audio, sr = sf.read(f.name, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    n = max(1, int(len(audio) / sr * FPS))
    frames = VisemeStream(fps=FPS).render_text(text.translate(_TR), amplitude=0.34)

    hop = max(1, sr // FPS)
    rms = np.array([np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n)])
    ref = np.percentile(rms, 90) or 1e-6
    gate = np.clip(rms / ref * 1.25, 0, 1)
    for i in range(1, n):                                   # yumuşak açılma/kapanma
        k = 0.55 if gate[i] > gate[i - 1] else 0.25
        gate[i] = gate[i - 1] + k * (gate[i] - gate[i - 1])

    channels = list(frames[0].keys()) if frames else []
    out = {c[0].lower() + c[1:]: [0.0] * n for c in channels}
    if frames:
        m = len(frames)
        for i in range(n):
            fr = frames[min(m - 1, int(i * m / n))]
            g = float(gate[i])
            for c, v in fr.items():
                out[c[0].lower() + c[1:]][i] = round(v * g, 3)
    return {"blendshapes": out, "n_frames": n, "fps": FPS, "ms": (time.perf_counter() - t0) * 1000}


def speak_payload(text: str) -> dict:
    wav, engine, tts_ms = synthesize(text)
    ls = lipsync(text, wav)
    return {"audio_b64": base64.b64encode(wav).decode(), "blendshapes": ls["blendshapes"],
            "n_frames": ls["n_frames"], "fps": ls["fps"], "tts_engine": engine,
            "tts_ms": round(tts_ms), "lipsync_ms": round(ls["ms"])}
