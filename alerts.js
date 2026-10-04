/* Personal shell alerts. Session, audio and seen IDs stay in this tab. */
(() => {
  let token = '';
  let team = null;
  let seen = new Set();
  let controller = null;
  let retryTimer = null;
  let sessionGeneration = 0;
  let connected = false;
  let enabled = false;
  let audio = null;
  let activeSound = null;
  let bar, label, toggle, preview, connectionLabel, notice;

  const preferenceKey = () => `pepes_shell_sound_${team.id}`;
  const seenKey = () => `pepes_shell_seen_${team.id}`;
  const audioReady = () => enabled && audio?.state === 'running';

  function stopSound() {
    if (activeSound) {
      activeSound.gain.disconnect();
      activeSound.limiter.disconnect();
      for (const source of activeSound.sources) { try { source.stop(); } catch (_) {} }
      activeSound = null;
    }
  }

  function getAudio() {
    if (!audio) {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) throw new Error('Este navegador no permite reproducir el aviso sonoro.');
      audio = new Audio();
      audio.addEventListener('statechange', render);
    }
    return audio;
  }

  // An eight-second accelerating warning followed by a short, low explosion.
  function playBomb() {
    if (!audioReady()) return;
    if (activeSound && audio.currentTime < activeSound.until) return;
    stopSound();
    const start = audio.currentTime + .03;
    const master = audio.createGain();
    master.gain.value = 2.25; // A modest +25% gain; keep the peak limiter below.
    const limiter = audio.createDynamicsCompressor();
    limiter.threshold.value = -3;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = .003;
    limiter.release.value = .12;
    master.connect(limiter);
    limiter.connect(audio.destination);
    const sources = [];
    const warningDuration = 8.2;
    const pulseCount = 36;
    activeSound = {gain: master, limiter, sources, until: start + warningDuration + 1.3};
    for (let i = 0; i < pulseCount; i++) {
      const pitchRise = (i / (pulseCount - 1)) * 715;
      const at = start + (warningDuration - .1) * (1 - Math.pow(1 - i / pulseCount, 1.5));
      const tone = audio.createOscillator();
      const envelope = audio.createGain();
      tone.type = 'triangle';
      tone.frequency.setValueAtTime(500 + pitchRise, at);
      tone.frequency.exponentialRampToValueAtTime(850 + pitchRise, at + .09);
      envelope.gain.setValueAtTime(0, at);
      envelope.gain.linearRampToValueAtTime(.32, at + .012);
      envelope.gain.exponentialRampToValueAtTime(.001, at + .12);
      tone.connect(envelope); envelope.connect(master);
      tone.start(at); tone.stop(at + .13); sources.push(tone);
    }
    const impact = start + warningDuration;
    const buffer = audio.createBuffer(1, Math.ceil(audio.sampleRate * 1.25), audio.sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    const noise = audio.createBufferSource();
    noise.buffer = buffer;
    const filter = audio.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(1500, impact);
    filter.frequency.exponentialRampToValueAtTime(70, impact + 1.2);
    const blast = audio.createGain();
    blast.gain.setValueAtTime(.001, impact);
    blast.gain.linearRampToValueAtTime(.85, impact + .015);
    blast.gain.exponentialRampToValueAtTime(.001, impact + 1.2);
    noise.connect(filter); filter.connect(blast); blast.connect(master);
    noise.start(impact); noise.stop(impact + 1.25); sources.push(noise);
    const bass = audio.createOscillator();
    const bassGain = audio.createGain();
    bass.frequency.setValueAtTime(90, impact);
    bass.frequency.exponentialRampToValueAtTime(28, impact + .8);
    bassGain.gain.setValueAtTime(.6, impact);
    bassGain.gain.exponentialRampToValueAtTime(.001, impact + .85);
    bass.connect(bassGain); bassGain.connect(master);
    bass.start(impact); bass.stop(impact + .9); sources.push(bass);
    noise.onended = () => {
      master.disconnect();
      limiter.disconnect();
      if (activeSound?.gain === master) activeSound = null;
    };
  }

  function render() {
    if (!bar) return;
    bar.hidden = !team;
    if (!team) return;
    label.textContent = `👥 ${team.name}`;
    const ready = audioReady();
    toggle.textContent = ready ? '🔔 Avisos activados · Silenciar' : '🔕 Activar avisos';
    toggle.setAttribute('aria-pressed', String(ready));
    preview.hidden = !ready;
    connectionLabel.textContent = connected ? '' : 'Conectando avisos…';
  }

  function showNotice(message) {
    notice.hidden = false;
    notice.querySelector('p').textContent = message;
  }

  function persistSeen() {
    seen = new Set(Array.from(seen).slice(-500));
    sessionStorage.setItem(seenKey(), JSON.stringify([...seen]));
  }

  function receive(state) {
    if (!team || state.team?.id !== team.id || !Array.isArray(state.attacks)) return;
    team.name = state.team.name;
    connected = true;
    const fresh = state.attacks.filter(attack => attack.id && !seen.has(attack.id));
    for (const attack of state.attacks) if (attack.id) seen.add(attack.id);
    persistSeen();
    if (fresh.length) {
      const last = fresh[fresh.length - 1];
      showNotice(fresh.length === 1 ? `🐢 ¡${last.attackerName || 'Un rival'} te ha lanzado un caparazón!` : `🐢 ¡Tu equipo ha recibido ${fresh.length} caparazones!`);
      playBomb();
    }
    if (!state.attacks.length) notice.hidden = true;
    render();
  }

  function disconnect() {
    controller?.abort();
    controller = null;
    clearTimeout(retryTimer);
    retryTimer = null;
    connected = false;
  }

  function endSession() {
    sessionGeneration++;
    disconnect(); stopSound();
    token = ''; team = null; enabled = false;
    sessionStorage.removeItem('pepes_player_token');
    sessionStorage.removeItem('pepes_player_session');
    if (notice) notice.hidden = true;
    render();
    document.dispatchEvent(new Event('player-session-ended'));
  }

  async function connect(generation) {
    if (!token || generation !== sessionGeneration) return;
    const current = new AbortController();
    controller = current;
    try {
      const response = await fetch(`${API_BASE_URL}/player/events`, {headers: {Authorization: `Bearer ${token}`}, signal: current.signal});
      if (response.status === 401) { endSession(); return; }
      if (!response.ok || !response.body) throw new Error('No se pudo conectar el canal de avisos.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (!current.signal.aborted) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true}).replace(/\r/g, '');
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          if (generation !== sessionGeneration) return;
          if (block.startsWith('event: expired')) { endSession(); return; }
          const data = block.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
          if (data) receive(JSON.parse(data));
        }
      }
    } catch (error) {
      if (error.name !== 'AbortError') connected = false;
    } finally {
      if (generation === sessionGeneration && !current.signal.aborted && token) {
        connected = false; render();
        retryTimer = setTimeout(() => connect(generation), 3000);
      }
    }
  }

  async function refreshSession() {
    const generation = ++sessionGeneration;
    disconnect(); stopSound();
    token = sessionStorage.getItem('pepes_player_token') || '';
    if (!token) { team = null; enabled = false; render(); if (notice) notice.hidden = true; return; }
    const state = await DataStore.getPlayerState(token);
    if (generation !== sessionGeneration) return;
    if (!state.success || !state.duo) {
      if (state.status === 401) endSession();
      else retryTimer = setTimeout(refreshSession, 5000);
      return;
    }
    team = {id: state.duo.id, name: state.duo.teamName};
    try { seen = new Set(JSON.parse(sessionStorage.getItem(seenKey()) || '[]')); } catch (_) { seen = new Set(); }
    // Existing pending shells are shown silently on page load, not replayed as new attacks.
    const pending = state.duo.pendingShellAttacks || [];
    for (const attack of pending) seen.add(attack.id);
    persistSeen();
    enabled = sessionStorage.getItem(preferenceKey()) === 'true';
    if (enabled) { try { getAudio(); } catch (_) { enabled = false; } }
    if (pending.length) showNotice(`🐢 Tu equipo tiene ${pending.length} caparazón(es) pendiente(s) de abrir.`);
    render();
    connect(generation);
  }

  document.addEventListener('DOMContentLoaded', () => {
    bar = document.createElement('div');
    bar.className = 'container personal-alert-bar';
    bar.id = 'personal-alert-bar';
    bar.hidden = true;
    label = document.createElement('strong');
    toggle = document.createElement('button');
    toggle.type = 'button'; toggle.className = 'btn-refresh'; toggle.id = 'toggle-shell-sound';
    preview = document.createElement('button');
    preview.type = 'button'; preview.className = 'btn-refresh'; preview.textContent = 'Probar sonido'; preview.id = 'preview-shell-sound';
    connectionLabel = document.createElement('span'); connectionLabel.className = 'personal-alert-connection';
    const logout = document.createElement('button');
    logout.type = 'button'; logout.className = 'personal-alert-logout'; logout.textContent = 'Cerrar sesión';
    bar.append(label, toggle, preview, connectionLabel, logout);
    const header = document.querySelector('header');
    if (header) header.after(bar); else document.body.prepend(bar);
    notice = document.createElement('aside');
    notice.className = 'shell-received-notice'; notice.id = 'shell-received-notice'; notice.hidden = true;
    notice.setAttribute('role', 'status');
    const message = document.createElement('p');
    const link = document.createElement('a'); link.href = 'player.html'; link.textContent = 'Ir a abrirlo'; link.className = 'btn-refresh';
    const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.textContent = 'Cerrar aviso'; dismiss.className = 'personal-alert-logout';
    dismiss.addEventListener('click', () => { notice.hidden = true; stopSound(); });
    notice.append(message, link, dismiss); document.body.append(notice);
    toggle.addEventListener('click', async () => {
      if (audioReady()) {
        enabled = false; sessionStorage.setItem(preferenceKey(), 'false'); stopSound(); render(); return;
      }
      try {
        await getAudio().resume();
        enabled = audio.state === 'running';
        sessionStorage.setItem(preferenceKey(), String(enabled));
        render();
      } catch (error) { showNotice(error.message); }
    });
    preview.addEventListener('click', playBomb);
    logout.addEventListener('click', () => { const oldToken = token; endSession(); DataStore.logoutPlayer(oldToken); });
    refreshSession();
  });
  document.addEventListener('player-session-changed', refreshSession);
  // A fresh document may need another gesture before the browser allows sound.
  document.addEventListener('pointerdown', event => { if (!event.target.closest('#toggle-shell-sound') && enabled && audio?.state === 'suspended') audio.resume().catch(() => {}); });
  window.addEventListener('pagehide', () => { disconnect(); stopSound(); });
  window.addEventListener('pageshow', event => { if (event.persisted) refreshSession(); });
})();
