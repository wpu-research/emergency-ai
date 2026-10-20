"""Triaj görüşmesi (Claude) ve CTAS kural motoru.

Claude yalnızca görüşmeyi yürütür ve bulguları yapılandırılmış olarak çıkarır.
Seviyeyi kural motoru belirler; AI önerisi seviyeyi yalnızca yükseltebilir:
öneri = min(kural, AI)  (CTAS'ta küçük sayı = daha acil).
"""
from __future__ import annotations

import json
import os
import time

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

GREETING = (
    "Merhaba, ben acil servisin triaj asistanıyım. Size yardımcı olabilmem için "
    "konuşmamızı kaydetmem gerekiyor; bilgileriniz yalnızca tedaviniz için kullanılacak. "
    "Onaylıyorsanız onaylıyorum deyin."
)
GREETING_BUTTONS = ["Onaylıyorum", "Tekrar oku", "Hemşire çağır"]

RED_FLAGS = [
    "unresponsive", "cardiac_chest_pain", "severe_dyspnea", "altered_consciousness",
    "stroke_signs", "severe_bleeding", "anaphylaxis", "seizure", "suicidal_ideation",
    "pregnancy_bleeding", "sudden_severe_headache", "high_risk_trauma",
]
RED_FLAG_TR = {
    "unresponsive": "yanıtsız", "cardiac_chest_pain": "kardiyak göğüs ağrısı",
    "severe_dyspnea": "ağır nefes darlığı", "altered_consciousness": "bilinç değişikliği",
    "stroke_signs": "inme bulgusu", "severe_bleeding": "ciddi kanama", "anaphylaxis": "anafilaksi",
    "seizure": "nöbet", "suicidal_ideation": "intihar düşüncesi", "pregnancy_bleeding": "gebelikte kanama",
    "sudden_severe_headache": "ani şiddetli baş ağrısı", "high_risk_trauma": "yüksek riskli travma",
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["say", "buttons", "consent", "complaint", "cedis_group", "onset", "pain_score",
                 "pain_location", "red_flags", "ai_ctas", "confidence", "next_topic", "finished"],
    "properties": {
        "say": {"type": "string", "description": "Hastaya söylenecek Türkçe cümle(ler); en fazla iki kısa cümle."},
        "buttons": {"type": "array", "items": {"type": "string"}, "description": "Ekranda gösterilecek 0-5 kısa cevap seçeneği."},
        "consent": {"type": "string", "enum": ["unknown", "given", "refused"]},
        "complaint": {"type": "string", "description": "Ana şikâyet, kısa Türkçe; bilinmiyorsa boş."},
        "cedis_group": {"type": "string", "enum": [
            "unknown", "cardiovascular", "respiratory", "neurologic", "gastrointestinal",
            "musculoskeletal_trauma", "skin", "eent", "genitourinary", "obstetric_gynecologic",
            "mental_health", "general_fever", "other"]},
        "onset": {"type": "string", "description": "Başlangıç zamanı (ör. '30 dakika önce'); bilinmiyorsa boş."},
        "pain_score": {"type": "integer", "description": "0-10; bilinmiyorsa -1."},
        "pain_location": {"type": "string", "enum": ["unknown", "none", "central", "peripheral"]},
        "red_flags": {"type": "array", "items": {"type": "string", "enum": RED_FLAGS}},
        "ai_ctas": {"type": "integer", "description": "Önerilen CTAS 1-5; yeterli bilgi yoksa 0."},
        "confidence": {"type": "number", "description": "Hastayı anlama güveni 0-1."},
        "next_topic": {"type": "string", "enum": ["consent", "complaint", "onset", "pain", "red_flags", "wrap_up"]},
        "finished": {"type": "boolean"},
    },
}

SYSTEM = f"""Sen bir acil servisin girişindeki kioskta çalışan triaj asistanısın. Ekranda bir hemşire avatarı olarak görünüyorsun ve yetişkin hastalarla sesli, Türkçe konuşuyorsun.

Görüşme şu cümlenle başladı: "{GREETING}"

Kurallar:
- Çok kısa ve sade Türkçe konuş: en fazla iki kısa cümle. Tıbbi terim kullanma. Okuma yazma bilmeyen biriyle konuşur gibi konuş.
- Teşhis koyma, tetkik veya ilaç önerme, "ciddi değil" gibi güvence verme. Seviyeyi hastaya söyleme.
- Sıra: önce onay; onay yoksa başka bir şey sorma. Sonra ana şikâyet, ne zaman başladığı, ağrı şiddeti (0-10), şikâyete uygun 1-2 kırmızı bayrak sorusu, sonra kapanış.
- Onay: hasta "onaylıyorum", "onayladım", "evet" gibi açıkça onay verirse consent="given". Reddederse consent="refused" ve hemşireyi çağıracağını söyle.
- Hastayı anlamadıysan confidence düşük olsun, kısaca tekrar sor ve buttons alanına anladığına en yakın 4-5 seçenek koy.
- Her soruda uygun hazır cevapları buttons alanına koy (ör. ağrı için "0-3", "4-7", "8-10"; evet/hayır sorularında "Evet", "Hayır").
- Kritik bir durum duyarsan (göğüs ağrısı kola/çeneye yayılıyor, ağır nefes darlığı, bilinç bulanıklığı, inme bulgusu, ciddi kanama, intihar düşüncesi vb.) ilgili red_flags değerini işaretle ve hastaya hemşirenin hemen geleceğini söyle.
- Tüm bilgiler toplandığında finished=true yap ve "Teşekkürler, hemşiremiz sizi birazdan değerlendirecek." benzeri bir kapanış söyle.
- Önceki turlarda topladığın bilgileri her cevapta koru (complaint, onset, pain_score, red_flags vb. boşalmasın).
- ai_ctas: CTAS ölçeğine göre önerin (1 resüsitasyon … 5 acil değil); bilgi yetersizse 0.
"""


def client() -> anthropic.Anthropic:
    headers = {}
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if ws:
        headers["anthropic-workspace-id"] = ws
    return anthropic.Anthropic(default_headers=headers)


def ask_claude(cl: anthropic.Anthropic, history: list[dict], extra: str = "") -> tuple[dict, float]:
    """history: [{'role':'user'|'assistant','content':str}]. Returns (parsed, ms)."""
    system = SYSTEM + (f"\n\nGüncel ölçümler ve durum: {extra}" if extra else "")
    t0 = time.perf_counter()
    resp = cl.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=history,
        # output_config: kurulu SDK sürümü parametreyi tanımadığı için gövdeye doğrudan eklenir
        extra_body={"output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}},
    )
    ms = (time.perf_counter() - t0) * 1000
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude isteği reddetti")
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    data["pain_score"] = max(-1, min(10, int(data.get("pain_score", -1))))
    data["ai_ctas"] = max(0, min(5, int(data.get("ai_ctas", 0))))
    data["buttons"] = [b for b in data.get("buttons", []) if b][:5]
    return data, ms


def rule_ctas(f: dict, vitals: dict) -> tuple[int, list[str]]:
    """Deterministik CTAS kuralları. Bilgi yoksa 0 döner."""
    level, why = 6, []

    def up(lv: int, reason: str) -> None:
        nonlocal level
        why.append(f"{reason} → CTAS {lv}")
        level = min(level, lv)

    flags = f.get("red_flags") or []
    for fl in flags:
        up(1 if fl == "unresponsive" else 2, RED_FLAG_TR.get(fl, fl))

    spo2, hr, sbp, temp = (vitals.get(k) for k in ("spo2", "hr", "sbp", "temp"))
    if spo2 is not None:
        if spo2 < 85: up(1, f"SpO₂ %{spo2:g}")
        elif spo2 < 90: up(2, f"SpO₂ %{spo2:g}")
        elif spo2 < 93: up(3, f"SpO₂ %{spo2:g}")
    if sbp is not None and sbp < 90: up(2, f"sistolik TA {sbp:g}")
    if hr is not None and (hr > 130 or hr < 40): up(2, f"nabız {hr:g}")
    elif hr is not None and hr > 110: up(3, f"nabız {hr:g}")
    if temp is not None and temp >= 38.0:
        up(3 if (hr or 0) > 100 else 4, f"ateş {temp:g} °C" + (" + taşikardi" if (hr or 0) > 100 else ""))

    pain, loc = f.get("pain_score", -1), f.get("pain_location", "unknown")
    if pain >= 0:
        central = loc == "central"
        if pain >= 8: up(2 if central else 3, f"{'santral' if central else 'periferik'} ağrı {pain}/10")
        elif pain >= 4: up(3 if central else 4, f"{'santral' if central else 'periferik'} ağrı {pain}/10")
        else: up(5, f"hafif ağrı {pain}/10")
    elif f.get("complaint") and f.get("finished"):
        up(5, "kırmızı bayrak ve belirgin ağrı yok")

    return (0 if level == 6 else level), why


def decide(f: dict, vitals: dict) -> dict:
    rule, why = rule_ctas(f, vitals)
    ai = f.get("ai_ctas", 0)
    if rule and ai:
        proposed = min(rule, ai)
        if ai < rule:
            why.append(f"AI daha acil gördü → CTAS {ai} (AI yalnız yükseltebilir)")
    else:
        proposed = rule or ai
    critical = any(fl in (f.get("red_flags") or []) for fl in RED_FLAGS) or (proposed and proposed <= 2)
    return {"rule": rule, "ai": ai, "proposed": proposed, "why": why, "alarm": bool(critical)}
