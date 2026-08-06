/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Main Frontend Logic (app.js)
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

let currentDuos = [];
let currentConfig = {};

async function initApp() {
  currentDuos = await DataStore.getDuos();
  currentConfig = await DataStore.getConfig();

  setupHeaderConfig();
  startCountdownTimer();
  renderStatsOverview();
  renderLeaderboardTable();
  await renderRecentAttacksTable();
  setupEventListeners();

  // Auto-refresco silencioso desde db.json cada 15 segundos (sin llamadas a Riot API)
  setInterval(async () => {
    try {
      currentDuos = await DataStore.getDuos();
      renderStatsOverview();
      renderLeaderboardTable();
      await renderRecentAttacksTable();
    } catch (e) {
      console.warn("Error en auto-refresco del panel:", e);
    }
  }, 15000);
}

/* Header & Timer */
function setupHeaderConfig() {
  const titleEl = document.getElementById('challenge-title');
  const prizeEl = document.getElementById('prize-pool-text');
  if (titleEl) titleEl.textContent = currentConfig.challengeTitle;
  if (prizeEl) prizeEl.textContent = currentConfig.prizePool;
}

function startCountdownTimer() {
  const countdownEl = document.getElementById('countdown-timer');
  if (!countdownEl) return;

  function updateTimer() {
    const end = new Date(currentConfig.endDate).getTime();
    const now = new Date().getTime();
    const diff = end - now;

    if (diff <= 0) {
      countdownEl.innerHTML = '<span class="text-gradient-pink">¡DESAFÍO FINALIZADO!</span>';
      return;
    }

    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const secs = Math.floor((diff % (1000 * 60)) / 1000);

    countdownEl.innerHTML = `
      <span class="countdown-unit">${days}d</span> :
      <span class="countdown-unit">${hours}h</span> :
      <span class="countdown-unit">${mins}m</span> :
      <span class="countdown-unit">${secs}s</span>
    `;
  }

  updateTimer();
  setInterval(updateTimer, 1000);
}

/* Stats Overview */
function renderStatsOverview() {
  const duosCountEl = document.getElementById('stat-total-duos');
  const totalGamesEl = document.getElementById('stat-total-games');
  const topDuoEl = document.getElementById('stat-top-duo');
  const liveCountEl = document.getElementById('stat-live-count');

  if (duosCountEl) duosCountEl.textContent = currentDuos.length;

  let totalGames = 0;
  let liveCount = 0;
  currentDuos.forEach(d => {
    totalGames += (d.wins + d.losses);
    if (d.isLive) liveCount++;
  });

  if (totalGamesEl) totalGamesEl.textContent = totalGames;
  if (liveCountEl) liveCountEl.textContent = `${liveCount} Jugadores`;

  const sorted = [...currentDuos].sort((a, b) => b.netLp - a.netLp);
  if (topDuoEl && sorted.length > 0) {
    topDuoEl.textContent = sorted[0].teamName;
  }
}

/* Leaderboard Rendering */
function renderLeaderboardTable() {
  const tbody = document.getElementById('leaderboard-tbody');
  if (!tbody) return;

  const searchInput = document.getElementById('search-input');
  const tierFilter = document.getElementById('tier-filter');
  const sortBySelect = document.getElementById('sort-by');

  const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
  const selectedTier = tierFilter ? tierFilter.value : 'ALL';
  const sortBy = sortBySelect ? sortBySelect.value : 'NET_LP';

  let filtered = currentDuos.filter(duo => {
    const p1Name = duo.player1 ? duo.player1.name.toLowerCase() : '';
    const p2Name = duo.player2 ? duo.player2.name.toLowerCase() : '';
    const matchesName = duo.teamName.toLowerCase().includes(query) ||
                        p1Name.includes(query) ||
                        p2Name.includes(query);
    const matchesTier = selectedTier === 'ALL' || duo.tier.toUpperCase() === selectedTier;
    return matchesName && matchesTier;
  });

  filtered.sort((a, b) => {
    if (sortBy === 'RANK' || sortBy === 'NET_LP') {
      const totalLpA = calcTotalLpHelper(a.tier, a.division, a.lp);
      const totalLpB = calcTotalLpHelper(b.tier, b.division, b.lp);
      return totalLpB - totalLpA;
    }
    if (sortBy === 'WINRATE') {
      const wrA = (a.wins + a.losses) > 0 ? (a.wins / (a.wins + a.losses)) : 0;
      const wrB = (b.wins + b.losses) > 0 ? (b.wins / (b.wins + b.losses)) : 0;
      return wrB - wrA;
    }
    if (sortBy === 'GAMES') return (b.wins + b.losses) - (a.wins + a.losses);
    if (sortBy === 'NAME') return a.teamName.localeCompare(b.teamName);
    return 0;
  });

  tbody.innerHTML = '';

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 3rem; color: var(--text-muted);">
          <i class="fa-solid fa-search" style="font-size: 2rem; margin-bottom: 1rem; color: var(--cyan-primary);"></i>
          <p>No se encontraron registros con los filtros seleccionados.</p>
        </td>
      </tr>
    `;
    return;
  }

  filtered.forEach((duo, index) => {
    const rankPos = index + 1;
    const totalG = duo.wins + duo.losses;
    const winrate = totalG > 0 ? Math.round((duo.wins / totalG) * 100) : 0;

    let posClass = 'rank-position';
    if (rankPos === 1) posClass += ' rank-1';
    else if (rankPos === 2) posClass += ' rank-2';
    else if (rankPos === 3) posClass += ' rank-3';

    let streakBadge = '';
    if (duo.streak > 0) {
      streakBadge = `<span class="streak-pill streak-win"><i class="fa-solid fa-fire"></i> ${duo.streak}W</span>`;
    } else if (duo.streak < 0) {
      streakBadge = `<span class="streak-pill streak-loss"><i class="fa-solid fa-snowflake"></i> ${Math.abs(duo.streak)}L</span>`;
    } else {
      streakBadge = `<span class="streak-pill" style="background: rgba(255,255,255,0.1);">-</span>`;
    }

    const hasP2 = duo.player2 && duo.player2.name;

    const tr = document.createElement('tr');
    tr.className = 'duo-row';
    tr.setAttribute('data-id', duo.id);
    tr.onclick = () => openDuoModal(duo.id);

    tr.innerHTML = `
      <td>
        <div class="${posClass}">${rankPos}</div>
      </td>
      <td>
        <div style="font-weight: 800; font-size: 1.05rem; color: var(--gold-hextech); display: flex; align-items: center; gap: 0.5rem;">
          <i class="fa-solid fa-users text-cyan" style="font-size: 0.9rem;"></i>
          <span>${escapeHtml(duo.teamName)}</span>
        </div>
      </td>
      <td>
        <div class="duo-team-cell">
          <div class="players-avatars">
            <img class="player-avatar" src="${duo.player1.avatar}" alt="${duo.player1.name}" title="${duo.player1.name}#${duo.player1.tag}" onerror="this.onerror=null; this.src='https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/29.png';">
            ${hasP2 ? `<img class="player-avatar" src="${duo.player2.avatar}" alt="${duo.player2.name}" title="${duo.player2.name}#${duo.player2.tag}" onerror="this.onerror=null; this.src='https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/1.png';">` : ''}
          </div>
          <div class="duo-names">
            <div class="duo-team-name">
              ${escapeHtml(duo.player1.name)}#${escapeHtml(duo.player1.tag)}
              ${duo.isLive ? '<span class="badge-live">EN PARTIDA</span>' : ''}
            </div>
            <div class="player-tags">
              ${hasP2 ? `${escapeHtml(duo.player1.name)} & ${escapeHtml(duo.player2.name)}` : `Jugador Individual`}
            </div>
          </div>
        </div>
      </td>
      <td>
        <div class="tier-pill">
          <span style="color: ${getTierColor(duo.tier)};">${duo.tier} ${duo.division}</span>
          <span style="color: var(--text-muted); font-size: 0.8rem;">(${duo.lp} LP)</span>
        </div>
      </td>
      <td>
        <div class="winrate-wrapper">
          <div class="winrate-text">
            <span>${winrate}%</span>
            <span style="color: var(--text-muted);">${duo.wins}W / ${duo.losses}L</span>
          </div>
          <div class="winrate-bar-bg">
            <div class="winrate-bar-fill" style="width: ${winrate}%;"></div>
          </div>
        </div>
      </td>
      <td>
        ${streakBadge}
      </td>
      <td>
        <button class="btn-refresh" style="padding: 0.35rem 0.75rem; font-size: 0.75rem;">
          Ver Partidas <i class="fa-solid fa-chevron-right"></i>
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function renderRecentAttacksTable() {
  const tbody = document.getElementById('recent-attacks-tbody');
  if (!tbody) return;

  const events = await DataStore.getEvents();
  tbody.innerHTML = '';

  if (!events || events.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 2rem;">
          <i class="fa-solid fa-shield-halved" style="font-size: 1.5rem; margin-bottom: 0.5rem; display: block; opacity: 0.5;"></i>
          No hay ataques o caparazones lanzados recientemente.
        </td>
      </tr>
    `;
    return;
  }

  // Mostrar como máximo los últimos 10 eventos
  const recentEvents = events.slice(0, 10);

  recentEvents.forEach(ev => {
    const tr = document.createElement('tr');
    const pen = ev.penalty || {};
    const icon = pen.icon || '🐢⚡';
    const penName = pen.name || 'Caparazón Azul';
    const penDesc = pen.desc || ev.message || '';

    tr.innerHTML = `
      <td style="font-size: 0.85rem; color: var(--text-muted); white-space: nowrap;">
        <i class="fa-regular fa-clock" style="margin-right: 0.3rem;"></i>${escapeHtml(ev.timestamp || '')}
      </td>
      <td>
        <strong style="color: var(--cyan-primary); font-size: 0.95rem;">${escapeHtml(ev.attacker || 'Equipo')}</strong>
      </td>
      <td>
        <strong style="color: #ff4d4d; font-size: 0.95rem;">${escapeHtml(ev.target || 'Objetivo')}</strong>
      </td>
      <td>
        <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
          <span style="font-size: 1.1rem;">${icon}</span>
          <span style="font-weight: 700; color: #ffffff;">${escapeHtml(penName)}</span>
          ${penDesc ? `<span style="font-size: 0.8rem; color: var(--text-muted);">— ${escapeHtml(penDesc)}</span>` : ''}
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

/* Event Listeners */
function setupEventListeners() {
  const searchInput = document.getElementById('search-input');
  const tierFilter = document.getElementById('tier-filter');
  const sortBySelect = document.getElementById('sort-by');
  const btnSync = document.getElementById('btn-sync');
  const modalOverlay = document.getElementById('modal-overlay');
  const modalClose = document.getElementById('modal-close');

  if (searchInput) searchInput.addEventListener('input', renderLeaderboardTable);
  if (tierFilter) tierFilter.addEventListener('change', renderLeaderboardTable);
  if (sortBySelect) sortBySelect.addEventListener('change', renderLeaderboardTable);

  const btnSyncMatches = document.getElementById('btn-sync-matches');

  if (btnSync) {
    btnSync.addEventListener('click', triggerManualSync);
  }

  if (btnSyncMatches) {
    btnSyncMatches.addEventListener('click', triggerFetchMatches);
  }

  if (modalClose) {
    modalClose.addEventListener('click', closeDuoModal);
  }

  if (modalOverlay) {
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) closeDuoModal();
    });
  }
}

/* Manual Sync */
async function triggerManualSync() {
  const btnSync = document.getElementById('btn-sync');
  if (btnSync) {
    const icon = btnSync.querySelector('i');
    if (icon) icon.classList.add('spinning');
    btnSync.disabled = true;

    currentDuos = await DataStore.triggerRiotSync();

    renderStatsOverview();
    renderLeaderboardTable();

    if (icon) icon.classList.remove('spinning');
    btnSync.disabled = false;
  }
}

/* Fetch Last 5 Matches via Riot API */
async function triggerFetchMatches() {
  const btn = document.getElementById('btn-sync-matches');
  if (btn) {
    const icon = btn.querySelector('i');
    if (icon) icon.classList.add('spinning');
    btn.disabled = true;

    currentDuos = await DataStore.triggerRiotSync();

    renderStatsOverview();
    renderLeaderboardTable();

    if (icon) icon.classList.remove('spinning');
    btn.disabled = false;

    showToast('¡Últimas 20 partidas de cada equipo recuperadas con éxito desde la API de Riot Games!');
  }
}

function showToast(msg) {
  let toast = document.getElementById('toast-notification');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast-notification';
    toast.style.cssText = `
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: var(--bg-card);
      border: 1px solid var(--gold-hextech);
      color: var(--gold-hextech);
      padding: 1rem 1.5rem;
      border-radius: 8px;
      box-shadow: 0 0 20px rgba(240, 180, 41, 0.4);
      font-family: var(--font-heading);
      font-weight: 700;
      font-size: 0.9rem;
      z-index: 9999;
      transition: all 0.3s ease;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    `;
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<i class="fa-solid fa-check-circle"></i> ${msg}`;
  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
  }, 3500);
}

/* Player/Duo Detail Modal */
async function openDuoModal(id) {
  let duo = currentDuos.find(d => d.id === id);
  if (!duo) return;

  const modalOverlay = document.getElementById('modal-overlay');
  const modalContent = document.getElementById('modal-content');
  if (!modalOverlay || !modalContent) return;

  const totalGames = duo.wins + duo.losses;
  const winrate = totalGames > 0 ? Math.round((duo.wins / totalGames) * 100) : 0;

  let historyHtml = '';
  if (duo.history && duo.history.length > 0) {
    const parseDate = (dStr) => {
      if (!dStr) return 0;
      const parts = dStr.split(' ');
      if (parts.length < 2) return 0;
      const [d, m, y] = parts[0].split('/');
      const [h, min] = parts[1].split(':');
      return new Date(y, m - 1, d, h, min).getTime();
    };

    const sortedHistory = [...duo.history].sort((a, b) => {
      const tA = parseDate(a.date);
      const tB = parseDate(b.date);
      if (tA !== tB) return tB - tA;
      const numA = parseInt((a.matchId || '').replace(/\D/g, '')) || 0;
      const numB = parseInt((b.matchId || '').replace(/\D/g, '')) || 0;
      return numB - numA;
    });

    historyHtml = sortedHistory.slice(0, 30).map(m => `
      <div class="match-item ${m.result === 'WIN' ? '' : 'defeat'}">
        <div style="display: flex; align-items: center; gap: 1rem;">
          <span class="match-result-badge ${m.result === 'WIN' ? 'win' : 'loss'}">${m.result === 'WIN' ? 'VICTORIA' : 'DERROTA'}</span>
          ${m.pentaKill ? `<span class="match-result-badge" style="background: linear-gradient(135deg, #ff0055, #ffaa00); color: #fff; font-weight: 800; box-shadow: 0 0 10px rgba(255, 0, 85, 0.6);"><i class="fa-solid fa-fire"></i> PENTAKILL (+1 🐢)</span>` : ''}
          <div style="display: flex; gap: 0.4rem;">
            <img class="champ-icon" src="https://ddragon.leagueoflegends.com/cdn/14.15.1/img/champion/${m.championP1}.png" title="${m.championP1}">
            ${m.championP2 ? `<img class="champ-icon" src="https://ddragon.leagueoflegends.com/cdn/14.15.1/img/champion/${m.championP2}.png" title="${m.championP2}">` : ''}
          </div>
          <div>
            <div style="font-size: 0.9rem; font-weight: 700;">Campeón: ${m.championP1} | KDA: ${m.kda1}${m.kda2 ? ` | ${m.kda2}` : ''}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">Duración: ${m.duration} • Ranked Solo/Duo${m.date ? ` • <i class="fa-regular fa-calendar"></i> ${m.date}` : ''}</div>
          </div>
        </div>
        <div class="lp-gain ${m.result === 'WIN' ? 'lp-positive' : 'lp-negative'}">
          ${m.lpChange}
        </div>
      </div>
    `).join('');
  } else {
    historyHtml = `<p style="color: var(--text-muted); font-size: 0.9rem;">Sin partidas clasificatorias recientes.</p>`;
  }

  const hasP2 = duo.player2 && duo.player2.name;

  modalContent.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem;">
      <div>
        <h2 class="font-heading text-gradient-cyan" style="font-size: 1.8rem;">${escapeHtml(duo.player1.name)}#${escapeHtml(duo.player1.tag)}${hasP2 ? ` & ${escapeHtml(duo.player2.name)}#${escapeHtml(duo.player2.tag)}` : ''}</h2>
        <p style="color: var(--text-muted); font-size: 0.95rem;">Estadísticas Reales del Invocador en EUW</p>
      </div>
      <div class="tier-pill" style="padding: 0.6rem 1.2rem; font-size: 1rem;">
        <span>${duo.tier} ${duo.division}</span>
        <span style="color: var(--gold-hextech); font-weight: 800;">${duo.lp} LP</span>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
      <div class="stat-card">
        <div class="stat-label">Winrate Global</div>
        <div class="stat-value text-gradient-gold">${winrate}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Victorias / Derrotas</div>
        <div class="stat-value" style="font-size: 1.3rem;">${duo.wins}W / ${duo.losses}L</div>
      </div>
    </div>

    <h3 class="font-heading" style="font-size: 1.1rem; color: var(--cyan-primary); margin-bottom: 1rem;">
      <i class="fa-solid fa-history"></i> Historial Reciente (Mostrando las ${Math.min(30, duo.history ? duo.history.length : 0)} más recientes de ${duo.history ? duo.history.length : 0} registradas)
    </h3>
    <div style="max-height: 450px; overflow-y: auto; padding-right: 0.5rem;">
      ${historyHtml}
    </div>
  `;

  modalOverlay.classList.add('active');
}

function closeDuoModal() {
  const modalOverlay = document.getElementById('modal-overlay');
  if (modalOverlay) modalOverlay.classList.remove('active');
}

/* Helper Utilities */
function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getTierColor(tier) {
  const t = str(tier).toLowerCase();
  if (t === 'unranked') return 'var(--text-muted)';
  if (t === 'iron') return 'var(--tier-iron)';
  if (t === 'bronze') return 'var(--tier-bronze)';
  if (t === 'silver') return 'var(--tier-silver)';
  if (t === 'gold') return 'var(--tier-gold)';
  if (t === 'platinum') return 'var(--tier-platinum)';
  if (t === 'emerald') return 'var(--tier-emerald)';
  if (t === 'diamond') return 'var(--tier-diamond)';
  if (t === 'master') return 'var(--tier-master)';
  return 'var(--cyan-primary)';
}

function calcTotalLpHelper(tier, division, lp) {
  const tierMap = { UNRANKED: 0, IRON: 0, BRONZE: 400, SILVER: 800, GOLD: 1200, PLATINUM: 1600, EMERALD: 2000, DIAMOND: 2400, MASTER: 2800, GRANDMASTER: 2800, CHALLENGER: 2800 };
  const divMap = { IV: 0, III: 100, II: 200, I: 300, '': 0 };
  const t = String(tier || 'UNRANKED').toUpperCase();
  const d = String(division || '').toUpperCase();
  return (tierMap[t] || 0) + (divMap[d] || 0) + (parseInt(lp, 10) || 0);
}

function str(val) { return String(val || ''); }
