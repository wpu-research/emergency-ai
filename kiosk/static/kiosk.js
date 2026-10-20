// EmergencyAI kiosk istemcisi: kamera ile kişi algılama, sesle konuşma, Atlas avatarı.
import { AvatarRenderer } from '/atlas/avatar_renderer.js';

const $ = id => document.getElementById(id);
const kiosk = $('kiosk');
const LV = {1:['r','Resüsitasyon','Kırmızı'],2:['r','Acil','Kırmızı'],3:['r','Aciliyetli','Kırmızı'],4:['y','Az acil','Sarı'],5:['g','Acil değil','Yeşil']};
const FLAG_TR = {unresponsive:'yanıtsız',cardiac_chest_pain:'kardiyak göğüs ağrısı',severe_dyspnea:'ağır nefes darlığı',altered_consciousness:'bilinç değişikliği',stroke_signs:'inme bulgusu',severe_bleeding:'ciddi kanama',anaphylaxis:'anafilaksi',seizure:'nöbet',suicidal_ideation:'intihar düşüncesi',pregnancy_bleeding:'gebelikte kanama',sudden_severe_headache:'ani şiddetli baş ağrısı',high_risk_trauma:'yüksek riskli travma'};

let state = 'boot', sessionId = null, avatar = null, finished = false;
const setState = s => { state = s; kiosk.dataset.state = s; $('micText').textContent = {idle:'Kişi bekleniyor', listening:'Dinliyorum, konuşabilirsiniz', recording:'Kaydediliyor…', thinking:'Düşünüyorum…', speaking:'Konuşuyor', done:'Görüşme tamamlandı'}[s] || s; };

// ── avatar ────────────────────────────────────────────────────────
function initAvatar(){
  const url = new URLSearchParams(location.search).get('avatar') || '/public/human.glb';
  try{ avatar = new AvatarRenderer($('avatar'), url); }
  catch(e){ console.warn('Avatar yüklenemedi', e); avatar = null; }
}
async function playSpeech(r, emotion){
  setState('speaking');
  try{ avatar?.setBodyAnim?.('speaking'); }catch(_){}
  if(avatar?.playSpeech){ await avatar.playSpeech(r.audio_b64, r.blendshapes, r.n_frames, r.fps, emotion || 'neutral'); }
  else { await new Promise(res => { const a = new Audio('data:audio/wav;base64,' + r.audio_b64); a.onended = a.onerror = res; a.play().catch(res); }); }
  try{ avatar?.setBodyAnim?.('idle'); }catch(_){}
}

// ── UI helpers ────────────────────────────────────────────────────
function esc(s){ return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function log(who, text){ const p = document.createElement('p'); p.className = who; p.innerHTML = `<b>${esc(who)}</b><span>${esc(text)}</span>`; $('log').appendChild(p); $('log').scrollTop = 1e9; }
function showButtons(list){ $('buttons').innerHTML = (list || []).map(b => `<button type="button">${esc(b)}</button>`).join(''); }
$('buttons').addEventListener('click', e => { const b = e.target.closest('button'); if(b && sessionId && state !== 'thinking') sendTurn({text: b.textContent}); });
function vitals(){
  const n = id => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };
  return {hr:n('vHr'), spo2:n('vSpo2'), sbp:n('vSbp'), dbp:n('vDbp'), temp:n('vTemp')};
}
function renderFindings(f){
  if(!f) return;
  const rows = [['Onay', f.consent === 'given' ? 'sözlü ✓' : f.consent === 'refused' ? 'reddetti' : '—'],
    ['Şikâyet', f.complaint || '—'], ['Grup', f.cedis_group || '—'], ['Başlangıç', f.onset || '—'],
    ['Ağrı', f.pain_score >= 0 ? `${f.pain_score}/10 · ${f.pain_location}` : '—'],
    ['Kırmızı bayrak', (f.red_flags || []).map(x => FLAG_TR[x] || x).join(', ') || 'yok', (f.red_flags||[]).length ? 'crit' : ''],
    ['Anlama güveni', f.confidence != null ? Math.round(f.confidence*100) + '%' : '—']];
  $('findings').innerHTML = rows.map(([k,v,c]) => `<dt>${k}</dt><dd${c?` class="${c}"`:''}>${esc(v)}</dd>`).join('');
}
function renderEngine(e){
  if(!e) return;
  $('eRule').textContent = e.rule ? 'CTAS ' + e.rule : '—';
  $('eAi').textContent = e.ai ? 'CTAS ' + e.ai : '—';
  const lv = LV[e.proposed]; const b = $('eFinal');
  b.className = 'n-badge' + (lv ? ' ' + lv[0] : '');
  b.innerHTML = (e.proposed ? 'CTAS ' + e.proposed : '—') + `<small>${lv ? lv[1].toUpperCase() : 'ÖNERİ'}</small>`;
  $('eWhy').innerHTML = (e.why || []).map(w => `<li>${esc(w)}</li>`).join('');
  if(e.alarm && $('alarm').hidden){ $('alarm').hidden = false; log('Alarm', 'Kritik bulgu → hemşireye bildirim'); beep(); }
}
function beep(){ try{ const c = new AudioContext(), o = c.createOscillator(), g = c.createGain(); o.frequency.value = 880; g.gain.value = .05; o.connect(g).connect(c.destination); o.start(); o.stop(c.currentTime + .25); }catch(_){} }

// ── session ───────────────────────────────────────────────────────
async function startSession(){
  if(sessionId || state === 'thinking') return;
  setState('thinking'); finished = false; lastSeen = performance.now();
  $('alarm').hidden = true; $('result').hidden = true; $('heard').hidden = true; $('log').innerHTML = '';
  const r = await (await fetch('/api/session', {method:'POST'})).json();
  sessionId = r.session_id; $('sid').textContent = 'Oturum ' + sessionId;
  $('say').textContent = r.say; showButtons(r.buttons); log('Avatar', r.say);
  await playSpeech(r, 'happy');
  lastSeen = Math.max(lastSeen, performance.now());
  setState('listening');
}
async function endSession(reason){
  if(!sessionId) return;
  const id = sessionId; sessionId = null;
  fetch('/api/end/' + id, {method:'POST'});
  log('Sistem', reason || 'Oturum bitti');
  $('say').textContent = 'Lütfen ekrana doğru yaklaşın.'; showButtons([]); $('heard').hidden = true;
  $('sid').textContent = 'Oturum yok'; setState('idle');
}
async function sendTurn(payload){
  if(!sessionId) return;
  setState('thinking');
  const body = {session_id: sessionId, vitals: vitals(), ...payload};
  let r;
  try{ r = await (await fetch('/api/turn', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)})).json(); }
  catch(e){ log('Sistem', 'Sunucuya ulaşılamadı'); setState('listening'); return; }
  if(r.heard){ $('heard').textContent = r.heard; $('heard').hidden = false; log('Hasta', r.heard); }
  $('say').textContent = r.say; showButtons(r.buttons); log('Avatar', r.say);
  renderFindings(r.findings); renderEngine(r.engine);
  const t = r.timing || {}; $('timing').textContent = `STT ${t.stt_ms ?? '–'} ms · Claude ${t.claude_ms ?? '–'} ms · TTS ${t.tts_ms ?? '–'} ms (${r.tts_engine || ''}) · TSYNC ${t.lipsync_ms ?? '–'} ms`;
  finished = !!(r.findings && r.findings.finished) || r.consent === 'refused';
  await playSpeech(r, r.engine?.alarm ? 'concerned' : 'neutral');
  lastSeen = Math.max(lastSeen, performance.now());
  if(finished){
    const lv = LV[r.engine?.proposed];
    if(lv){ $('result').className = 'k-result ' + lv[0]; $('result').textContent = 'Hemşiremiz sizi birazdan çağıracak'; $('result').hidden = false; }
    showButtons([]); setState('done');
  } else setState('listening');
}
$('typeForm').addEventListener('submit', e => { e.preventDefault(); const v = $('typeIn').value.trim(); if(v && sessionId){ $('typeIn').value = ''; sendTurn({text: v}); } });
$('resetBtn').onclick = () => endSession('Hemşire oturumu bitirdi');
$('manualBtn').onclick = () => { if(state === 'boot') boot().then(startSession); else startSession(); };

// ── microphone + voice activity detection ─────────────────────────
let analyser, recorder, chunks = [], recStart = 0, lastVoice = 0, noise = 0.01, voiceRun = 0;
function initMic(stream){
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
  analyser = ctx.createAnalyser(); analyser.fftSize = 1024; src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
  recorder = new MediaRecorder(new MediaStream(stream.getAudioTracks()), mime ? {mimeType: mime} : {});
  recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    const dur = performance.now() - recStart, blob = new Blob(chunks, {type: recorder.mimeType}); chunks = [];
    if(dur < 550 || !sessionId){ if(sessionId) setState('listening'); return; }
    const b64 = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(',')[1]); fr.readAsDataURL(blob); });
    sendTurn({audio_b64: b64, audio_mime: recorder.mimeType});
  };
  setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let s = 0; for(const v of buf) s += v*v; const rms = Math.sqrt(s / buf.length);
    $('micLevel').style.width = Math.min(100, rms * 900) + '%';
    const now = performance.now(), thr = Math.max(0.012, noise * 3.2);
    if(state === 'listening'){
      if(rms > thr){ if(++voiceRun >= 3){ chunks = []; recorder.start(); recStart = now; lastVoice = now; setState('recording'); } }
      else { voiceRun = 0; noise += 0.05 * (rms - noise); }
    } else if(state === 'recording'){
      if(rms > thr){ lastVoice = now; lastSeen = now; }
      if(now - lastVoice > 950 || now - recStart > 15000){ recorder.stop(); setState('thinking'); }
    }
  }, 50);
}

// ── camera + person detection (MediaPipe) ─────────────────────────
let detector = null, presentSince = 0, lastSeen = 0;
async function initDetector(){
  try{
    const v = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs');
    const files = await v.FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm');
    detector = await v.FaceDetector.createFromOptions(files, {
      baseOptions:{modelAssetPath:'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite', delegate:'GPU'},
      runningMode:'VIDEO', minDetectionConfidence:0.6 });
  }catch(e){ console.warn('Yüz algılayıcı yüklenemedi', e); $('presence').textContent = 'Algılayıcı yok · dokunarak başlayın'; }
}
function detectLoop(){
  const video = $('cam'), cv = $('camOverlay'), g = cv.getContext('2d');
  if(detector && video.readyState >= 2){
    cv.width = video.videoWidth; cv.height = video.videoHeight;
    const res = detector.detectForVideo(video, performance.now());
    g.clearRect(0, 0, cv.width, cv.height);
    const face = (res.detections || []).sort((a,b) => b.boundingBox.width - a.boundingBox.width)[0];
    const now = performance.now();
    if(face){
      const bb = face.boundingBox, near = bb.width / cv.width > 0.16;
      g.strokeStyle = near ? '#5fd07e' : '#f2b13c'; g.lineWidth = 4; g.strokeRect(bb.originX, bb.originY, bb.width, bb.height);
      lastSeen = now;
      if(near){ presentSince ||= now; } else presentSince = 0;
      $('presence').textContent = near ? 'Sizi görüyorum' : 'Biraz yaklaşın';
      $('presence').classList.toggle('on', near);
      if(near && !sessionId && state === 'idle' && now - presentSince > 1000) startSession();
    } else {
      presentSince = 0; $('presence').textContent = 'Kişi yok'; $('presence').classList.remove('on');
      if(sessionId && now - lastSeen > 12000 && (state === 'listening' || state === 'done')) endSession('Hasta kioskun önünden ayrıldı');
    }
  }
  requestAnimationFrame(detectLoop);
}

// ── boot: one tap unlocks camera, microphone and audio ───────────
async function boot(){
  $('startBtn').hidden = true; setState('idle');
  try{
    const stream = await navigator.mediaDevices.getUserMedia({video:{width:640, height:480, facingMode:'user'}, audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
    $('cam').srcObject = stream; initMic(stream);
  }catch(e){ $('presence').textContent = 'Kamera/mikrofon izni yok'; log('Sistem', 'Kamera veya mikrofon açılamadı: ' + e.message); }
  await initDetector();
  if(!detector){ $('startBtn').textContent = 'Görüşmeyi başlat'; $('startBtn').hidden = false; $('startBtn').onclick = () => { $('startBtn').hidden = true; startSession(); }; }
  else $('presence').textContent = 'Kişi bekleniyor';
  detectLoop();
}
initAvatar();
$('startBtn').hidden = false;
$('startBtn').onclick = boot;
renderFindings({});
