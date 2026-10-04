/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Data & API Services Layer
   ========================================================================== */

const API_BASE_URL = window.PEPES_API_URL || '/api';

function normalizeTwitchUrl(value) {
  const rawValue = String(value || '').trim();
  if (!rawValue) return '';

  try {
    const url = new URL(rawValue);
    const hostname = url.hostname.toLowerCase().replace(/^www\./, '');
    const pathParts = url.pathname.split('/').filter(Boolean);

    if (url.protocol !== 'https:' || hostname !== 'twitch.tv' || pathParts.length !== 1 || url.username || url.password || url.port) {
      return '';
    }

    const channel = pathParts[0];
    if (!/^[a-zA-Z0-9_]{4,25}$/.test(channel)) return '';

    return `https://www.twitch.tv/${channel.toLowerCase()}`;
  } catch (error) {
    return '';
  }
}

function participantTwitch(duo, playerKey) {
  const player = duo[playerKey] || {};
  const ownChannel = Object.prototype.hasOwnProperty.call(player, 'twitchUrl');
  const rawUrl = ownChannel ? player.twitchUrl : playerKey === 'player1' ? duo.twitchUrl : '';
  return {url: normalizeTwitchUrl(rawUrl), live: Object.prototype.hasOwnProperty.call(player, 'twitchIsLive') ? player.twitchIsLive === true : !ownChannel && playerKey === 'player1' && duo.twitchIsLive === true};
}

function penaltyAssignmentText(instance, duo = {}) {
  const scope = instance?.scope || instance?.penalty?.scope;
  const req = instance?.requirements || {};
  const label = (key, account = {}) => {
    const player = duo[key] || {};
    const name = account.name || player.name || '';
    const tag = account.tag || player.tag || 'EUW';
    const displayName = account.displayName || player.displayName || name || (key === 'player1' ? 'Integrante 1' : 'Integrante 2');
    return name ? `${displayName} · ${name}#${tag}` : displayName;
  };
  const flashInstruction = key => {
    if (instance?.penalty?.baseId !== 'swap_flash') return '';
    const slot = req.flashBaselines?.[key]?.slot;
    return slot === 1 || slot === 2 ? `Flash en ${slot === 1 ? 'F' : 'D'} (posición ${slot === 1 ? 2 : 1})` : 'Referencia pendiente: primera partida con Flash';
  };
  if (scope === 'ONE') {
    const key = req.assignedPlayer;
    if (key !== 'player1' && key !== 'player2') return req.assignmentVersion >= 2 ? 'Asignación pendiente' : 'Puede cumplirlo cualquiera de los dos (castigo anterior).';
    return `Debe cumplirlo: ${label(key, req.assignedAccount)}${req.randomChampions?.[key] ? ` · Campeón: ${req.randomChampions[key]}` : ''}${flashInstruction(key) ? ` · ${flashInstruction(key)}` : ''}`;
  }
  if (scope === 'BOTH') {
    const champions = ['player1', 'player2'].filter(key => req.randomChampions?.[key])
      .map(key => `${label(key)}: ${req.randomChampions[key]}`);
    const flash = instance?.penalty?.baseId === 'swap_flash' ? ['player1','player2'].map(key => `${label(key, req.flashAccounts?.[key])}: ${flashInstruction(key)}`) : [];
    return `Lo cumplen ambos integrantes.${champions.length ? ' ' + champions.join(' · ') : ''}${flash.length ? ' ' + flash.join(' · ') : ''}`;
  }
  return '';
}

const DEFAULT_CONFIG = {
  challengeTitle: "Pepes Krisis Duo Q Challenge",
  startDate: "2026-10-15T18:00:00+02:00",
  endDate: "2026-11-15T23:59:00+01:00",
  prizePool: "Bote: 500€ + Cena de Ganadores 🏆",
  server: "EUW",
  twitchClientId: ""
};

const TOURNAMENT_TIME_ZONE = 'Europe/Madrid';

function tournamentDateInput(value) {
  const timestamp = tournamentDateTimestamp(value);
  if (!Number.isFinite(timestamp)) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: TOURNAMENT_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).formatToParts(timestamp).map(p => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function tournamentDateTimestamp(value) {
  const text = String(value || '').trim();
  if (!text) return NaN;
  if (/(?:Z|[+-]\d{2}:\d{2})$/i.test(text)) return Date.parse(text);
  // datetime-local has no zone: treat it as Madrid, never the viewer's timezone.
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(text);
  if (!match) return NaN;
  const [, year, month, day, hour = '00', minute = '00', second = '00'] = match;
  const expected = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
  const wallTime = Date.parse(expected + 'Z');
  if (!Number.isFinite(wallTime)) return NaN;
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: TOURNAMENT_TIME_ZONE, year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'
  });
  const madridTime = timestamp => {
    const p = Object.fromEntries(formatter.formatToParts(timestamp).map(part => [part.type, part.value]));
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
  };
  let timestamp = wallTime;
  for (let i = 0; i < 3; i++) timestamp += wallTime - Date.parse(madridTime(timestamp) + 'Z');
  return madridTime(timestamp) === expected ? timestamp : NaN;
}

// Only confirmed server reads are retained, in memory, for this page session.
const readCache = new Map();
const unavailableReads = new Set();
let lastReadAt = null;
let latestSyncStatus = {};

function renderConnectionStatus() {
  if (document.body.dataset.panel !== 'admin') return;
  const element = document.getElementById('connection-status');
  if (!element) return;
  const messages = [];
  if (unavailableReads.size) {
    messages.push('Conexión interrumpida. Mostrando los últimos datos disponibles' + (lastReadAt ? ` (${new Date(lastReadAt).toLocaleTimeString()})` : '') + '.');
  }
  const visibleJobs = ['riot', 'twitch'];
  for (const name of visibleJobs) {
    const state = latestSyncStatus[name];
    if (!state) continue;
    const label = name === 'riot' ? 'Riot' : 'Twitch';
    if (state.running) messages.push(`${label}: sincronizando…`);
    else if (state.error) messages.push(`${label}: ${state.error}`);
    if (state.lastSuccessAt) messages.push(`${label}: última sincronización correcta ${new Date(state.lastSuccessAt).toLocaleString()}.`);
    if (state.pending) messages.push(`${state.pending} partidas pendientes de completar.`);
  }
  element.textContent = messages.join(' ');
  element.hidden = messages.length === 0;
  element.classList.toggle('connection-warning', unavailableReads.size > 0 || visibleJobs.some(name => latestSyncStatus[name]?.error));
}

async function apiRequest(path, payload, method = 'POST') {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method, signal: controller.signal,
      ...(method === 'GET' ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload || {})})
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'No se pudo completar la solicitud.');
      error.status = response.status;
      throw error;
    }
    return result;
  } finally {
    clearTimeout(timeout);
  }
}

async function cachedRead(path, fallback) {
  try {
    const result = await apiRequest(path, null, 'GET');
    readCache.set(path, result);
    unavailableReads.delete(path);
    lastReadAt = Date.now();
    renderConnectionStatus();
    return result;
  } catch (error) {
    unavailableReads.add(path);
    renderConnectionStatus();
    return readCache.has(path) ? readCache.get(path) : fallback;
  }
}

async function mutation(path, payload, method) {
  try {
    const result = await apiRequest(path, payload, method);
    unavailableReads.delete(path);
    renderConnectionStatus();
    return {ok: true, ...result};
  } catch (error) {
    if (!error.status || error.status >= 500) { unavailableReads.add(path); renderConnectionStatus(); }
    return {ok: false, success: false, status: error.status, error: error.message || 'No se pudo conectar con el servidor.'};
  }
}

const DataStore = {
  getWeeklySummary: (week = '') => apiRequest(`/weekly-summary${week ? `?week=${encodeURIComponent(week)}` : ''}`, null, 'GET'),
  getTrophies: () => cachedRead('/trophies', {cards: []}),
  getDuos: () => cachedRead('/duos', []),
  getConfig: () => cachedRead('/config', DEFAULT_CONFIG),
  getEvents: () => cachedRead('/events?type=SHELL_SPUN&limit=10', []),
  getHistory: (id, offset = 0) => apiRequest(`/duos/${encodeURIComponent(id)}/history?offset=${offset}&limit=30`, null, 'GET'),
  getAdminConfig: pin => mutation('/admin/login', {pin}),
  saveDuo: (duo, authPin) => mutation('/duos', {duo, authPin}),
  deleteDuo: (id, authPin) => mutation(`/duos/${encodeURIComponent(id)}`, {authPin}, 'DELETE'),
  saveConfig: (config, authPin) => mutation('/config', {config, authPin}),
  triggerRiotSync: authPin => mutation('/sync', {authPin}),
  triggerTwitchSync: authPin => mutation('/twitch/sync', {authPin}),
  calculateShells: authPin => mutation('/calculate-shells', {authPin}),
  loginPlayer: (teamId, password) => mutation('/player/login', {teamId, password}),
  logoutPlayer: sessionToken => mutation('/player/logout', {sessionToken}),
  getPlayerState: sessionToken => mutation('/player/state', {sessionToken}),
  launchShell: (targetId, sessionToken) => mutation('/player/launch-shell', {targetId, sessionToken}),
  spinShell: (attackId, sessionToken) => mutation('/player/spin-shell', {attackId, sessionToken}),
  adminResolvePenalty: (penaltyInstanceId, action, note, authPin) => mutation('/admin/resolve-penalty', {penaltyInstanceId, action, note, authPin}),
  async refreshSyncStatus() {
    const previous = latestSyncStatus;
    latestSyncStatus = await cachedRead('/sync/status', latestSyncStatus);
    renderConnectionStatus();
    if (Object.keys(latestSyncStatus).some(name => latestSyncStatus[name].finishedAt && latestSyncStatus[name].finishedAt !== previous[name]?.finishedAt)) {
      document.dispatchEvent(new CustomEvent('sync-finished'));
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  // Technical diagnostics belong exclusively to the admin panel. Polling stays
  // shared so existing refresh and sync-finished behavior remains unchanged.
  renderConnectionStatus();
  async function poll() {
    try { if (!document.hidden) await DataStore.refreshSyncStatus(); }
    finally { setTimeout(poll, 15000); }
  }
  poll();
});
