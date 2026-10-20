# EmergencyAI

Acil serviste yetişkin hastalar için AI hemşire avatarlı triaj kiosku. Hasta koridorda termal ve RGB kamerayla taranır, kioskta sensörlerle vital bulguları ölçülür ve ekrandaki avatarla Türkçe konuşur. CTAS kural motoru seviye önerir; AI seviyeyi yalnızca yükseltebilir; kararı triaj hemşiresi onaylar.

- `docs/ARCHITECTURE.md` — mimari (metin)
- `docs/architecture.html` — görsel mimari, canlı sistem şeması ve 3D simülasyon
- `docs/simulation.html` — tek başına 3D simülasyon

Konuşma hattı: faster-whisper → Claude Haiku 5.5 → Türkçe TTS → TranscriptionSync → Atlas avatarı.

Yerel çalıştırma: `docker build -t emergency-ai . && docker run -p 8080:8080 emergency-ai`

Gizli bilgiler `.env` dosyasında tutulur ve repoya girmez (`ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`).
