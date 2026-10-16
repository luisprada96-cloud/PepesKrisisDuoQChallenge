/* OBS overlay: independent sessions, existing authenticated SSE; no game mutations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const suggestedTeam = params.get('team'); // A UI hint only; the server authenticates the receiver.
  const instance = params.get('instance') || 'default';
  const key = `pepes_obs_session_v1_${instance}`;
  let token = '', team = null, controller, retry, generation = 0;
  let seen = new Set(), queue = [], playing = false, animationTimer, audio;
  let connected = false, volume = .4;
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
  async function enableAudio() {
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      await audio.resume();
    } catch (_) { status('Audio no disponible. La animación seguirá funcionando.'); }
  }
  function sound() {
    if (!audio || audio.state !== 'running' || !volume) return;
    const start = audio.currentTime;
    const master = audio.createGain();
    master.gain.value = volume * .4;
    master.connect(audio.destination);
    for (let i = 0; i < 9; i++) {
      const at = start + i * .19;
      const tone = audio.createOscillator(), gain = audio.createGain();
      tone.type = 'triangle'; tone.frequency.value = 500 + i * 90;
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(.65, at + .01);
      gain.gain.exponentialRampToValueAtTime(.001, at + .13);
      tone.connect(gain); gain.connect(master); tone.start(at); tone.stop(at + .14);
    }
    const bass = audio.createOscillator(), blast = audio.createGain();
    bass.frequency.setValueAtTime(150, start + 1.8);
    bass.frequency.exponentialRampToValueAtTime(30, start + 2.5);
    blast.gain.setValueAtTime(.8, start + 1.8);
    blast.gain.exponentialRampToValueAtTime(.001, start + 2.6);
    bass.connect(blast); blast.connect(master); bass.start(start + 1.8); bass.stop(start + 2.65);
    bass.onended = () => master.disconnect();
  }
  function playNext() {
    if (playing || !queue.length) return;
    const attack = queue.shift(); playing = true;
    $('attacker').textContent = `${attack.attackerName || 'Un rival'} os ha lanzado un pepazo`;
    $('target').textContent = team?.name || 'Equipo de prueba';
    $('alert').hidden = false;
    sound();
    animationTimer = setTimeout(() => {
      $('alert').hidden = true; playing = false;
      animationTimer = setTimeout(playNext, 250);
    }, 5800);
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
    clearTimeout(animationTimer); queue = []; playing = false; $('alert').hidden = true;
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
      const state = await api('/player/state', {sessionToken:token});
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
      const result = await api('/player/login', {teamId:$('team').value, password:$('password').value});
      token = result.sessionToken; $('password').value = ''; save(); await start();
    } catch (error) { status(error.message); }
    finally { $('submit').disabled = false; }
  });
  $('volume').addEventListener('input', () => { volume = Number($('volume').value)/100; save(); });
  $('preview').addEventListener('click', async () => {
    await enableAudio(); queue.push({attackerName:'Dúo de prueba'}); hideSettings(); playNext();
  });
  $('hide').addEventListener('click', hideSettings);
  $('logout').addEventListener('click', () => {
    const old = token; expired(); $('warning').hidden = true;
    status('Sesión cerrada. Selecciona un equipo.');
    api('/player/logout', {sessionToken:old}).catch(() => {});
  });
  document.addEventListener('dblclick', event => { if (!$('settings').contains(event.target)) showSettings(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideSettings(); });
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
