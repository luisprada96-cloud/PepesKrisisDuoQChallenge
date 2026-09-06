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

    if (url.protocol !== 'https:' || hostname !== 'twitch.tv' || pathParts.length !== 1) {
      return '';
    }

    const channel = pathParts[0];
    if (!/^[a-zA-Z0-9_]{4,25}$/.test(channel)) return '';

    return `https://www.twitch.tv/${channel}`;
  } catch (error) {
    return '';
  }
}

const DEFAULT_CONFIG = {
  challengeTitle: "Pepes Krisis Duo Q Challenge",
  startDate: "2026-08-01T00:00:00",
  endDate: "2026-08-31T23:59:59",
  prizePool: "Bote: 500€ + Cena de Ganadores 🏆",
  server: "EUW",
  twitchClientId: ""
};

// Only confirmed server reads are retained, in memory, for this page session.
const readCache = new Map();
const unavailableReads = new Set();
let lastReadAt = null;
let latestSyncStatus = {};

function renderConnectionStatus() {
  const element = document.getElementById('connection-status');
  if (!element) return;
  const messages = [];
  if (unavailableReads.size) {
    messages.push('Conexión interrumpida. Mostrando los últimos datos disponibles' + (lastReadAt ? ` (${new Date(lastReadAt).toLocaleTimeString()})` : '') + '.');
  }
  const visibleJobs = document.body.dataset.panel === 'admin' ? ['riot', 'twitch'] : ['riot'];
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
  const status = document.createElement('p');
  status.id = 'connection-status';
  status.hidden = true;
  status.className = 'container connection-status';
  status.setAttribute('role', 'status');
  const header = document.querySelector('header');
  if (header) header.after(status); else document.body.prepend(status);
  async function poll() {
    try { if (!document.hidden) await DataStore.refreshSyncStatus(); }
    finally { setTimeout(poll, 15000); }
  }
  poll();
});
