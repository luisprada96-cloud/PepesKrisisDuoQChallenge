/* OBS overlay: independent sessions, existing authenticated SSE; no game mutations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const suggestedTeam = params.get('team'); // UI hint only; authentication remains on the server.
  const instance = params.get('instance') || 'default';
  const key = `pepes_obs_session_v1_${instance}`;
  let token = '', team = null, controller, retry, generation = 0;
  let seen = new Set(), queue = [], playing = false, animationTimer, audio;
  let connected = false, volume = .4;
  let soundBuffer, soundLoad, activeSource, activeGain;
  const DURATION_MS = 10000;
  let flightAnimation, playbackGeneration = 0;
  function flyRocket() {
    flightAnimation?.cancel();
    // Smooth Catmull-Rom spline, resampled by distance for a steady flight speed.
    const points = [[-.72,.12],[-.32,.04],[.04,-.20],[.31,-.07],[.14,.20],[-.29,.17],[-.32,-.16],[.15,-.20],[.30,.12],[-.14,.17],[-.22,-.12],[.07,-.10],[0,0]];
    const samples = [];
    for (let segment=0;segment<points.length-1;segment++) {
      const p0=points[Math.max(0,segment-1)],p1=points[segment],p2=points[segment+1],p3=points[Math.min(points.length-1,segment+2)];
      for(let j=0;j<40;j++) {
        const t=j/40, t2=t*t,t3=t2*t;
        const xy=[0,1].map(k=>.5*((2*p1[k])+(-p0[k]+p2[k])*t+(2*p0[k]-5*p1[k]+4*p2[k]-p3[k])*t2+(-p0[k]+3*p1[k]-3*p2[k]+p3[k])*t3));
        const last=samples.at(-1);
        samples.push({x:xy[0],y:xy[1],d:last?last.d+Math.hypot((xy[0]-last.x)*innerWidth,(xy[1]-last.y)*innerHeight):0});
      }
    }
    const last=samples.at(-1);
    samples.push({x:0,y:0,d:last.d+Math.hypot(last.x*innerWidth,last.y*innerHeight)});
    const frames=[]; let cursor=1,previousAngle=0;
    for(let i=0;i<=372;i++) {
      const u=i/372, distance=samples.at(-1).d*u;
      while(cursor<samples.length-1 && samples[cursor].d<distance)cursor++;
      const a=samples[cursor-1],b=samples[cursor], ratio=(distance-a.d)/(b.d-a.d||1);
      const x=a.x+(b.x-a.x)*ratio, y=a.y+(b.y-a.y)*ratio;
      let angle=Math.atan2((b.y-a.y)*innerHeight,(b.x-a.x)*innerWidth)*180/Math.PI;
      while(angle-previousAngle>180)angle-=360;
      while(angle-previousAngle< -180)angle+=360;
      previousAngle=angle;
      frames.push({offset:u*.62,opacity:Math.min(1,u*18),transform:`translate(calc(-50% + ${x*100}vw),calc(-50% + ${y*100}vh)) rotate(${angle}deg) scale(${.85+.15*u})`});
    }
    frames.push({offset:.6201,opacity:0,transform:frames.at(-1).transform},{offset:1,opacity:0,transform:frames.at(-1).transform});
    flightAnimation=$('alert').querySelector('.rocket-path').animate(frames,{duration:DURATION_MS,fill:'both',easing:'linear'});
  }
  const status = text => { $('status').textContent = text; };
  const save = () => localStorage.setItem(key, JSON.stringify({token, volume}));
  const seenKey = () => `pepes_obs_seen_${instance}_${team.id}`;
  function persistSeen() {
    // Bounded to avoid unbounded storage growth during the tournament.
    seen = new Set([...seen].slice(-2000));
    localStorage.setItem(seenKey(), JSON.stringify([...seen]));
  }
  function connection(ok, message) {
    connected = ok;
    $('warning').hidden = ok || !token || !$('settings').hidden;
    status(message);
  }
  async function api(path, payload) {
    const response = await fetch(`/api${path}`, {
      method: payload === undefined ? 'GET' : 'POST',
      ...(payload === undefined ? {} : {headers: {'Content-Type':'application/json'}, body:JSON.stringify(payload)}),
      signal: AbortSignal.timeout(15000), cache: 'no-store'
    });
    const result = await response.json();
    if (!response.ok || result.success === false) {
      const error = new Error(result.error || 'No se pudo conectar.');
      error.status = response.status;
      throw error;
    }
    return result;
  }
  async function loadSound() {
    if (soundBuffer) return soundBuffer;
    if (!soundLoad) soundLoad = fetch('overlay-pepazo.mp3', {cache:'force-cache'})
      .then(response => { if (!response.ok) throw new Error('Falta el audio del overlay.'); return response.arrayBuffer(); })
      .then(bytes => audio.decodeAudioData(bytes))
      .then(buffer => soundBuffer = buffer)
      .catch(error => { soundLoad = null; throw error; });
    return soundLoad;
  }
  async function enableAudio() {
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      // Do not await resume: autoplay policies may leave it pending after a reload.
      audio.resume().catch(() => {});
      await loadSound();
    } catch (_) { status('No se pudo cargar el sonido. Comprueba overlay-pepazo.mp3 y pulsa Probar.'); }
  }
  function stopSound() {
    try { activeSource?.stop(); } catch (_) {}
    activeSource = null; activeGain?.disconnect(); activeGain = null;
  }
  function sound() {
    stopSound();
    if (!audio || audio.state !== 'running' || !soundBuffer || !volume) return;
    const source = audio.createBufferSource(), gain = audio.createGain();
    source.buffer = soundBuffer; gain.gain.value = volume;
    source.connect(gain); gain.connect(audio.destination);
    activeSource = source; activeGain = gain;
    source.onended = () => { gain.disconnect(); if (activeSource === source) { activeSource = null; activeGain = null; } };
    source.start();
  }
  function clearVideo() {
    const video = $('effect-video');
    video.onended = video.onerror = video.onplaying = video.ontimeupdate = video.onseeked = null;
    video.pause(); video.removeAttribute('src'); video.load(); video.hidden = true;
    $('alert').classList.remove('video-effect', 'video-hold', 'video-sender');
  }
  function playNext() {
    if (playing || !queue.length) return;
    const attack = queue.shift(); playing = true;
    const run = ++playbackGeneration;
    $('attacker').textContent = attack.attackerName || 'Un rival';
    $('target').textContent = team?.name || 'Equipo de prueba';
    $('alert').hidden = false;
    const finish = () => {
      if (run !== playbackGeneration) return;
      playbackGeneration++;
      clearTimeout(animationTimer); clearVideo();
      $('alert').hidden = true; playing = false;
      animationTimer = setTimeout(playNext, 250);
    };
    let usingBuiltin = false;
    const builtin = () => {
      if (run !== playbackGeneration || usingBuiltin) return;
      usingBuiltin = true;
      clearTimeout(animationTimer); clearVideo();
      flyRocket(); sound();
      animationTimer = setTimeout(finish, DURATION_MS);
    };
    const effect = attack.overlayEffect;
    if (effect?.kind !== 'video' || !/^\/api\/overlay\/media\/[a-f0-9]{64}$/.test(effect.url || '')) {
      builtin(); return;
    }
    stopSound(); flightAnimation?.cancel();
    $('alert').classList.add('video-effect');
    const video = $('effect-video'); video.hidden = false; video.volume = volume;
    const revealMs = Number(effect.senderRevealMs);
    const revealDuringVideo = Number.isFinite(revealMs) && revealMs >= 0 && revealMs < Number(effect.durationMs);
    const syncSender = () => {
      if (run !== playbackGeneration || !revealDuringVideo) return;
      $('alert').classList.toggle('video-sender', video.currentTime * 1000 >= revealMs);
    };
    video.ontimeupdate = video.onseeked = syncSender;
    let began = false, ended = false;
    const holdSender = () => {
      if (run !== playbackGeneration || ended) return;
      ended = true; clearTimeout(animationTimer); video.pause(); video.hidden = true;
      $('alert').classList.add('video-hold');
      animationTimer = setTimeout(finish, 3500);
    };
    video.onended = revealDuringVideo ? finish : holdSender;
    video.onerror = builtin; // A failed asset uses the fixed fallback, never another draw.
    video.onplaying = () => {
      if (run !== playbackGeneration || began) return;
      began = true; clearTimeout(animationTimer);
      // An invalid/unfinished file must not block the rest of the alert queue.
      animationTimer = setTimeout(holdSender, Math.min(30000, Math.max(500, Number(effect.durationMs) || 10000)) + 500);
    };
    video.src = effect.url;
    animationTimer = setTimeout(builtin, 10000);
    video.play().catch(builtin);
  }
  function receive(state) {
    if (state.team?.id !== team?.id || !Array.isArray(state.attacks)) return;
    team.name = state.team.name;
    connection(true, `Conectado · ${team.name}. Listo para recibir pepazos.`);
    for (const attack of state.attacks) {
      if (!attack.id || seen.has(attack.id)) continue;
      seen.add(attack.id); queue.push(attack);
    }
    persistSeen(); playNext();
  }
  function stopConnection() {
    generation++; controller?.abort(); clearTimeout(retry);
    clearTimeout(animationTimer); playbackGeneration++; clearVideo(); stopSound(); flightAnimation?.cancel(); queue = []; playing = false; $('alert').hidden = true;
  }
  function expired() {
    stopConnection(); token = ''; team = null; localStorage.removeItem(key);
    $('login').hidden = false; $('logout').hidden = true;
    $('warning').hidden = false;
    status('Sesión caducada. Abre el panel e inicia sesión de nuevo.');
  }
  async function connect(gen) {
    if (!token || gen !== generation) return;
    const current = new AbortController(); controller = current;
    // Heartbeats arrive every 15 seconds. Recover if a proxy silently drops the stream.
    let watchdog = setTimeout(() => current.abort(), 30000);
    try {
      const response = await fetch('/api/player/events', {headers: {Authorization:`Bearer ${token}`}, signal:current.signal, cache:'no-store'});
      if (gen !== generation) return;
      if (response.status === 401) { expired(); return; }
      if (!response.ok || !response.body) throw new Error('Canal de avisos no disponible.');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = '';
      while (gen === generation) {
        const {value, done} = await reader.read(); if (done) break;
        clearTimeout(watchdog); watchdog = setTimeout(() => current.abort(), 30000);
        buffer += decoder.decode(value, {stream:true}).replace(/\r/g, '');
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0,boundary); buffer = buffer.slice(boundary + 2);
          if (gen !== generation) return;
          if (block.split('\n').includes('event: expired')) { expired(); return; }
          const data = block.split('\n').filter(s => s.startsWith('data:')).map(s => s.slice(5).trimStart()).join('\n');
          if (data) receive(JSON.parse(data));
        }
      }
    } catch (_) { /* Retry below; preserve the seen IDs across interruptions. */ }
    finally {
      clearTimeout(watchdog);
      if (gen === generation && token) {
        connection(false, 'Conexión interrumpida. Reintentando…');
        retry = setTimeout(() => connect(gen), 3000);
      }
    }
  }
  async function start() {
    stopConnection(); const gen = generation;
    try {
      // Upgrade an existing, still-valid one-day player session automatically.
      if (!token.startsWith('obs_')) {
        const upgraded = await api('/overlay/session', {sessionToken:token});
        if (gen !== generation) return;
        token = upgraded.sessionToken; save();
      }
      const state = await api('/overlay/state', {sessionToken:token});
      if (gen !== generation) return;
      team = {id:state.duo.id, name:state.duo.teamName};
      try { seen = new Set(JSON.parse(localStorage.getItem(seenKey()) || '[]')); } catch (_) { seen = new Set(); }
      // A newly opened OBS source must not replay pre-existing inbox attacks.
      for (const attack of state.duo.pendingShellAttacks || []) seen.add(attack.id);
      persistSeen(); save();
      $('login').hidden = true; $('logout').hidden = false;
      connection(false, `Conectando · ${team.name}…`);
      // Browsers may keep resume() pending until a gesture after a reload.
      // Receiving events must never depend on the audio autoplay policy.
      enableAudio();
      connect(gen);
    } catch (error) {
      if (gen !== generation) return;
      if (error.status === 401) expired();
      else { connection(false, 'No se pudo conectar. Reintentando…'); retry = setTimeout(start, 5000); }
    }
  }
  function showSettings() { $('settings').hidden = false; $('warning').hidden = true; }
  function hideSettings() { $('settings').hidden = true; $('warning').hidden = connected || !token; }
  $('login').addEventListener('submit', async event => {
    event.preventDefault(); $('submit').disabled = true;
    await enableAudio();
    try {
      const result = await api('/overlay/login', {teamId:$('team').value, password:$('password').value});
      token = result.sessionToken; $('password').value = ''; save(); await start();
    } catch (error) { status(error.message); }
    finally { $('submit').disabled = false; }
  });
  $('volume').addEventListener('input', () => { volume = Number($('volume').value)/100; if (activeGain) activeGain.gain.value = volume; $('effect-video').volume = volume; save(); });
  $('preview').addEventListener('click', async () => {
    await enableAudio();
    let effects = [];
    try { effects = (await api('/overlay/effects')).effects || []; } catch (_) { /* Local fallback remains available. */ }
    const overlayEffect = effects.length ? effects[Math.floor(Math.random()*effects.length)] : null;
    queue.push({attackerName:'Dúo de prueba', overlayEffect}); playNext();
  });
  $('hide').addEventListener('click', hideSettings);
  $('logout').addEventListener('click', () => {
    const old = token; expired(); $('warning').hidden = true;
    status('Sesión cerrada. Selecciona un equipo.');
    api('/overlay/logout', {sessionToken:old}).catch(() => {});
  });
  document.addEventListener('dblclick', event => { if (!$('settings').contains(event.target)) showSettings(); });
  window.addEventListener('pagehide', stopConnection);
  window.addEventListener('pageshow', event => { if (event.persisted && token) start(); });
  async function loadTeams() {
    try {
      const teams = await api('/duos'); $('team').replaceChildren();
      const placeholder = new Option('Selecciona tu equipo', ''); $('team').add(placeholder);
      for (const duo of teams) $('team').add(new Option(duo.teamName, duo.id));
      if (!token && teams.some(duo => duo.id === suggestedTeam)) $('team').value = suggestedTeam;
      if (!token) status(teams.length ? 'Selecciona tu equipo para conectar.' : 'Todavía no hay equipos. Se volverá a consultar.');
      if (!teams.length) setTimeout(loadTeams, 10000);
    } catch (_) { if (!token) status('No se pudieron cargar los equipos. Reintentando…'); setTimeout(loadTeams, 5000); }
  }
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}'); token = saved.token || '';
    if (Number.isFinite(saved.volume)) volume = Math.min(1,Math.max(0,saved.volume));
  } catch (_) { /* First launch or corrupt local preferences. */ }
  $('volume').value = String(volume*100);
  loadTeams();
  if (token) start(); else showSettings();
})();
