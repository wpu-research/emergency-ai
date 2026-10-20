# EmergencyAI

Acil serviste yetişkin hastalar için AI hemşire avatarlı triaj kiosku. Hasta koridorda termal ve RGB kamerayla taranır, kioskta sensörlerle vital bulguları ölçülür ve ekrandaki avatarla Türkçe konuşur. CTAS kural motoru seviye önerir; AI seviyeyi yalnızca yükseltebilir; kararı triaj hemşiresi onaylar.

- `docs/ARCHITECTURE.md` — mimari (metin)
- `docs/architecture.html` — görsel mimari, canlı sistem şeması ve 3D simülasyon
- `docs/simulation.html` — tek başına 3D simülasyon

Konuşma hattı: faster-whisper → Claude Haiku 5.5 → Türkçe TTS → TranscriptionSync → Atlas avatarı.

Yerel çalıştırma: `docker build -t emergency-ai . && docker run -p 8080:8080 emergency-ai`

Gizli bilgiler `.env` dosyasında tutulur ve repoya girmez (`ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`).

## Kiosk prototipi (Faz 0)

Kamera kişiyi algılar, Atlas avatarı Türkçe konuşur, hasta sesle cevap verir.

```bash
pip install -r kiosk/requirements.txt   # bu makinede hepsi kurulu
cd kiosk && python3 server.py            # → http://localhost:8787
```

- Akış: kamera (MediaPipe yüz algılama) → mikrofon + ses etkinliği algılama → faster-whisper → Claude Haiku 5.5 (yapılandırılmış çıktı) → CTAS kural motoru → Türkçe TTS (edge-tts, olmazsa yerel Piper) → TranscriptionSync → Atlas avatarı.
- Avatar: `ATLAS_DIR` (varsayılan `~/tsync_exp/atlas`) altındaki `public/human.glb`. Başka model: `?avatar=/public/dosya.glb`.
- Sağdaki hemşire görünümü: bulgular, kural/AI seviyesi, elle sensör değerleri, yazarak test, süreler.
- Ayarlar: `WHISPER_MODEL` (small), `TTS_ENGINE` (edge|piper), `EDGE_VOICE`, `CLAUDE_MODEL`, `KIOSK_PORT` (8787).
- Oturum kayıtları ve sözlü onay sesleri `kiosk/data/` altına yazılır (repoya girmez).
- Gerçek kioskta Chrome'u `--kiosk --autoplay-policy=no-user-gesture-required` ile açın.
