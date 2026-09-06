/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Main Frontend Logic (app.js)
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById("leaderboard-tbody")) initApp();
});

let currentDuos = [];
let currentConfig = {};
const expandedDuoIds = new Set();

const POSITION_LABELS = {
  TOP: 'Top',
  JUNGLE: 'Jungla',
  MIDDLE: 'Mid',
  BOTTOM: 'ADC',
  UTILITY: 'Support',
  UNKNOWN: 'Sin datos'
};

async function initApp() {
  currentDuos = await DataStore.getDuos();
  currentConfig = await DataStore.getConfig();

  setupHeaderConfig();
  startCountdownTimer();
  renderStatsOverview();
  renderLeaderboardTable();
  renderFunStatistics();
  renderBestMatchesTable();
  await renderRecentAttacksTable();
  setupEventListeners();

  let signature = JSON.stringify(currentDuos);
  async function refresh() {
    try {
      if (!document.hidden) {
        const next = await DataStore.getDuos();
        const nextSignature = JSON.stringify(next);
        if (nextSignature !== signature) {
          currentDuos = next;
          signature = nextSignature;
          renderStatsOverview();
          renderLeaderboardTable();
          renderFunStatistics();
          renderBestMatchesTable();
        }
        await renderRecentAttacksTable();
      }
    } finally { setTimeout(refresh, 15000); }
  }
  setTimeout(refresh, 15000);
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
    if (d.twitchIsLive === true) liveCount++;
  });

  if (totalGamesEl) totalGamesEl.textContent = totalGames;
  if (liveCountEl) liveCountEl.textContent = `${liveCount} ${liveCount === 1 ? 'Dúo' : 'Dúos'}`;

  const sorted = [...currentDuos].sort(compareCompetitionRank);
  if (topDuoEl && sorted.length > 0) {
    topDuoEl.textContent = sorted[0].teamName;
  }
}

/* Leaderboard Rendering */
function toggleDuoAccordion(duoId) {
  const wasExpanded = expandedDuoIds.has(duoId);
  expandedDuoIds.clear();
  if (!wasExpanded) expandedDuoIds.add(duoId);
  renderLeaderboardTable();
}

function renderPlayerInsightCard(player, insight) {
  const champion = insight && insight.topChampion;
  const position = insight && insight.mostPlayedPosition;
  const playerName = player && player.name ? player.name : 'Jugador';
  const mainRoleLabel = POSITION_LABELS[player && player.mainRole] || 'Sin configurar';

  if (!champion) {
    return `
      <article class="player-insight-card is-empty">
        <img class="insight-player-avatar" src="${escapeHtml(player && player.avatar ? player.avatar : '')}" alt="${escapeHtml(playerName)}" onerror="this.style.display='none';">
        <div>
          <h3>${escapeHtml(playerName)}</h3>
          <p>Estadísticas pendientes de recuperar desde Riot.</p>
          <div class="insight-role-summary"><span>Rol principal</span><strong>${mainRoleLabel}</strong></div>
        </div>
      </article>
    `;
  }

  const championName = escapeHtml(champion.name || 'Unknown');
  const positionLabel = POSITION_LABELS[position && position.position] || 'Sin datos';
  return `
    <article class="player-insight-card">
      <img class="insight-champion-icon" src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${championName}.png" alt="${championName}" onerror="this.style.display='none';">
      <div class="insight-content">
        <div class="insight-heading">
          <h3>${escapeHtml(playerName)}</h3>
          <span>${championName}</span>
        </div>
        <div class="insight-metrics">
          <div><span>Partidas</span><strong>${Number(champion.games) || 0}</strong></div>
          <div><span>KDA</span><strong>${Number(champion.kda || 0).toFixed(2)}</strong></div>
          <div><span>Winrate</span><strong>${Number(champion.winrate) || 0}%</strong></div>
          <div><span>Rol principal</span><strong>${mainRoleLabel}</strong></div>
          <div><span>Más jugada</span><strong>${positionLabel}</strong></div>
        </div>
      </div>
    </article>
  `;
}

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
      return compareCompetitionRank(a, b);
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

  const positions = new Map([...currentDuos].sort(compareCompetitionRank).map((duo, index) => [duo.id, index + 1]));
  filtered.forEach(duo => {
    const rankPos = positions.get(duo.id);
    const totalG = duo.wins + duo.losses;
    const winrate = totalG > 0 ? Math.round((duo.wins / totalG) * 100) : 0;

    let posClass = 'rank-position';
    if (rankPos === 1) posClass += ' rank-1';
    else if (rankPos === 2) posClass += ' rank-2';
    else if (rankPos === 3) posClass += ' rank-3';

    const currentStreakCount = Number(duo.currentStreakCount) || 0;
    const currentStreakType = duo.currentStreakType;
    let streakBadge = '';
    if (currentStreakCount >= 3 && currentStreakType === 'WIN') {
      streakBadge = `<span class="streak-pill streak-win" title="${currentStreakCount} victorias consecutivas"><span class="streak-icon" aria-hidden="true">📈</span><span>${currentStreakCount}W</span></span>`;
    } else if (currentStreakCount >= 3 && currentStreakType === 'LOSS') {
      streakBadge = `<span class="streak-pill streak-loss" title="${currentStreakCount} derrotas consecutivas"><span class="streak-icon" aria-hidden="true">📉</span><span>${currentStreakCount}L</span></span>`;
    } else {
      streakBadge = `<span class="streak-pill streak-neutral" title="Sin racha activa de 3 o más partidas">-</span>`;
    }

    const hasP2 = duo.player2 && duo.player2.name;
    const twitchUrl = normalizeTwitchUrl(duo.twitchUrl);
    const isTwitchLive = Boolean(twitchUrl && duo.twitchIsLive === true);
    const isExpanded = expandedDuoIds.has(duo.id);
    const accordionId = `duo-insights-${duo.id}`;

    const tr = document.createElement('tr');
    tr.className = `duo-row${isExpanded ? ' is-expanded' : ''}`;
    tr.setAttribute('data-id', duo.id);
    tr.setAttribute('role', 'button');
    tr.setAttribute('tabindex', '0');
    tr.setAttribute('aria-expanded', String(isExpanded));
    tr.setAttribute('aria-controls', accordionId);
    tr.onclick = event => { if (!event.target.closest('button, a')) toggleDuoAccordion(duo.id); };
    tr.onkeydown = event => {
      if (event.target === tr && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        toggleDuoAccordion(duo.id);
      }
    };

    tr.innerHTML = `
      <td>
        <div class="${posClass}">${rankPos}</div>
      </td>
      <td>
        <div class="team-name-cell">
          <div class="team-name-heading">
            <i class="fa-solid fa-users text-cyan" aria-hidden="true"></i>
            <span>${escapeHtml(duo.teamName)}</span>
          </div>
          ${twitchUrl ? `
            <a class="twitch-link${isTwitchLive ? ' is-live' : ''}" href="${escapeHtml(twitchUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" aria-label="Ver a ${escapeHtml(duo.teamName)} en Twitch${isTwitchLive ? ' — en directo' : ''}">
              <i class="fa-brands fa-twitch" aria-hidden="true"></i>
              ${isTwitchLive ? '<span class="live-dot" aria-hidden="true"></span> EN DIRECTO' : 'Ver en Twitch'}
            </a>
          ` : ''}
        </div>
      </td>
      <td>
        <div class="tier-pill">
          <span style="color: ${getTierColor(duo.tier)};">${escapeHtml(duo.tier)} ${escapeHtml(duo.division)}</span>
          <span style="color: var(--text-muted); font-size: 0.8rem;">(${escapeHtml(duo.lp)} LP)</span>
          <span class="net-lp-label">${Number(duo.netLp) || 0} LP netos</span>
        </div>
      </td>
      <td>
        <div class="winrate-wrapper">
          <div class="winrate-text">
            <span>${winrate}%</span>
            <span style="color: var(--text-muted);">${escapeHtml(duo.wins)}W / ${escapeHtml(duo.losses)}L</span>
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
        <div class="shells-summary-cell" aria-label="${Number(duo.shellsLaunched) || 0} caparazones lanzados y ${Number(duo.shellsReceived) || 0} recibidos">
          <span class="shell-count shell-count-launched" title="Caparazones lanzados">
            <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i>
            <strong>${Number(duo.shellsLaunched) || 0}</strong>
            <small>Lanzados</small>
          </span>
          <span class="shell-count-divider" aria-hidden="true"></span>
          <span class="shell-count shell-count-received" title="Caparazones recibidos">
            <i class="fa-solid fa-arrow-down" aria-hidden="true"></i>
            <strong>${Number(duo.shellsReceived) || 0}</strong>
            <small>Recibidos</small>
          </span>
        </div>
      </td>
      <td>
        <div class="leaderboard-actions">
        <button type="button" class="btn-refresh" style="padding: 0.35rem 0.75rem; font-size: 0.75rem;" data-history-id="${escapeHtml(duo.id)}">
          Ver Partidas <i class="fa-solid fa-chevron-right"></i>
        </button>
        <i class="fa-solid fa-chevron-down accordion-chevron" aria-hidden="true"></i>
        </div>
      </td>
    `;
    tbody.appendChild(tr);

    const detailsRow = document.createElement('tr');
    detailsRow.id = accordionId;
    detailsRow.className = 'duo-insights-row';
    detailsRow.hidden = !isExpanded;
    const insights = duo.playerInsights || {};
    const backfill = duo.statsBackfill || {};
    const pendingText = Number(backfill.remaining) > 0
      ? `<span class="insights-backfill"><i class="fa-solid fa-rotate"></i> Recuperando ${Number(backfill.remaining)} partidas pendientes</span>`
      : '';
    detailsRow.innerHTML = `
      <td colspan="7">
        <section class="duo-insights-panel" aria-label="Estadísticas individuales de ${escapeHtml(duo.teamName)}">
          <div class="insights-panel-heading">
            <span>Estadísticas individuales · Solo/Duo desde el inicio del reto</span>
            ${pendingText}
          </div>
          ${renderCombinedDuoStats(duo)}
          ${renderEloChart(duo)}
          <div class="player-insights-grid">
            ${renderPlayerInsightCard(duo.player1, insights.player1)}
            ${hasP2 ? renderPlayerInsightCard(duo.player2, insights.player2) : ''}
          </div>
        </section>
      </td>
    `;
    tbody.appendChild(detailsRow);
  });
}

function renderBestMatchesTable() {
  const tbody = document.getElementById('best-matches-tbody');
  if (!tbody) return;

  const ranked = [...currentDuos].sort((a, b) => {
      const matchA = a.bestCombinedKdaMatch;
      const matchB = b.bestCombinedKdaMatch;
      if (!matchA && !matchB) return a.teamName.localeCompare(b.teamName);
      if (!matchA) return 1;
      if (!matchB) return -1;
      return (matchB.combinedKda - matchA.combinedKda) ||
        ((matchB.kills + matchB.assists) - (matchA.kills + matchA.assists)) ||
        (matchA.deaths - matchB.deaths);
    });

  if (ranked.length === 0) {
    const pending = currentDuos.reduce((total, duo) => total + Number(duo.statsBackfill && duo.statsBackfill.remaining || 0), 0);
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="best-matches-empty">
          <i class="fa-solid fa-rotate"></i>
          ${pending > 0 ? `Esperando las estadísticas de ${pending} partidas de Riot.` : 'Todavía no hay partidas completas para comparar.'}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = ranked.map((duo, index) => {
    const match = duo.bestCombinedKdaMatch;
    if (!match) {
      return `
        <tr class="best-match-unavailable">
          <td><span class="best-match-position">—</span></td>
          <td><strong class="best-match-team">${escapeHtml(duo.teamName)}</strong></td>
          <td colspan="5">
            <span class="best-match-no-data"><i class="fa-solid fa-users-slash"></i> Sin partidas registradas con ambos integrantes</span>
          </td>
        </tr>
      `;
    }
    const p1 = match.player1;
    const p2 = match.player2;
    const p1Champion = escapeHtml(p1.championName || 'Unknown');
    const p2Champion = escapeHtml(p2.championName || 'Unknown');
    const p1Position = POSITION_LABELS[p1.position] || 'Sin datos';
    const p2Position = POSITION_LABELS[p2.position] || 'Sin datos';
    const resultClass = match.result === 'WIN' ? 'best-result-win' : 'best-result-loss';
    const resultLabel = match.result === 'WIN' ? 'Victoria' : 'Derrota';

    return `
      <tr>
        <td><span class="best-match-position">${index + 1}</span></td>
        <td><strong class="best-match-team">${escapeHtml(duo.teamName)}</strong><span class="best-match-date">${escapeHtml(match.date || '')}</span></td>
        <td>
          <div class="best-champions">
            <span><img src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${p1Champion}.png" alt="${p1Champion}"> ${p1Champion}</span>
            <span><img src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${p2Champion}.png" alt="${p2Champion}"> ${p2Champion}</span>
          </div>
        </td>
        <td><span class="best-lines">${p1Position} <i class="fa-solid fa-plus"></i> ${p2Position}</span></td>
        <td><strong class="combined-kda">${Number(match.combinedKda).toFixed(2)}</strong></td>
        <td><strong>${match.kills}/${match.deaths}/${match.assists}</strong><span class="best-match-date">${escapeHtml(p1.kda)} · ${escapeHtml(p2.kda)}</span></td>
        <td><span class="best-result ${resultClass}">${resultLabel}</span></td>
      </tr>
    `;
  }).join('');
}

function renderFunStatistics() {
  const container = document.getElementById('fun-stats-grid');
  if (!container) return;

  const players = currentDuos.flatMap(duo => ['player1', 'player2'].map(playerKey => {
    const player = duo[playerKey];
    const insight = duo.playerInsights && duo.playerInsights[playerKey];
    if (!player || !player.name || !insight || !insight.totals || !Number(insight.gamesAnalyzed)) return null;
    return {
      name: player.name,
      tag: player.tag || '',
      avatar: player.avatar || '',
      teamName: duo.teamName,
      games: Number(insight.gamesAnalyzed) || 0,
      kills: Number(insight.totals.kills) || 0,
      deaths: Number(insight.totals.deaths) || 0,
      assists: Number(insight.totals.assists) || 0
    };
  })).filter(Boolean);

  const metrics = [
    {key: 'kills', title: 'Kills', subtitle: 'Más asesinatos', icon: 'fa-crosshairs', accent: 'kills'},
    {key: 'deaths', title: 'Muertes', subtitle: 'Más veces eliminado', icon: 'fa-skull', accent: 'deaths'},
    {key: 'assists', title: 'Asistencias', subtitle: 'Más asistencias', icon: 'fa-handshake-angle', accent: 'assists'}
  ];

  if (!players.length) {
    container.innerHTML = '<p class="fun-stats-empty"><i class="fa-solid fa-hourglass-half"></i> Recuperando estadísticas individuales desde Riot.</p>';
    return;
  }

  container.innerHTML = metrics.map(metric => {
    const leaders = [...players]
      .sort((a, b) => b[metric.key] - a[metric.key] || b.games - a.games || a.name.localeCompare(b.name))
      .slice(0, 5);
    const winner = leaders[0];
    const rest = leaders.slice(1);
    return `
      <article class="fun-stat-column fun-stat-${metric.accent}">
        <header>
          <i class="fa-solid ${metric.icon}" aria-hidden="true"></i>
          <div><h3>${metric.title}</h3><span>${metric.subtitle}</span></div>
        </header>
        <div class="fun-stat-winner">
          <span class="fun-stat-rank">1</span>
          <img src="${escapeHtml(winner.avatar)}" alt="${escapeHtml(winner.name)}" onerror="this.style.visibility='hidden';">
          <div class="fun-stat-player">
            <strong>${escapeHtml(winner.name)}${winner.tag ? `#${escapeHtml(winner.tag)}` : ''}</strong>
            <span>${escapeHtml(winner.teamName)} · ${winner.games} partidas</span>
          </div>
          <b>${winner[metric.key]}</b>
        </div>
        <ol class="fun-stat-list">
          ${rest.map((player, index) => `
            <li>
              <span class="fun-stat-rank">${index + 2}</span>
              <img src="${escapeHtml(player.avatar)}" alt="" onerror="this.style.visibility='hidden';">
              <span class="fun-stat-player"><strong>${escapeHtml(player.name)}</strong><small>${escapeHtml(player.teamName)} · ${player.games} partidas</small></span>
              <b>${player[metric.key]}</b>
            </li>
          `).join('')}
        </ol>
      </article>`;
  }).join('');
}

async function renderRecentAttacksTable() {
  const tbody = document.getElementById('recent-attacks-tbody');
  if (!tbody) return;

  const events = (await DataStore.getEvents()).filter(event => event.type === "SHELL_SPUN");
  tbody.innerHTML = '';

  if (!events || events.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 2rem;">
          <i class="fa-solid fa-shield-halved" style="font-size: 1.5rem; margin-bottom: 0.5rem; display: block; opacity: 0.5;"></i>
          Todavía no hay castigos abiertos por los receptores.
        </td>
      </tr>
    `;
    return;
  }

  // Mostrar las últimas 10 aperturas de caparazones
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

/* Public refresh only reads the last confirmed server state. */
async function triggerManualSync() {
  const buttons = ['btn-sync', 'btn-sync-matches'].map(id => document.getElementById(id)).filter(Boolean);
  buttons.forEach(button => button.disabled = true);
  try {
    currentDuos = await DataStore.getDuos();
    renderStatsOverview();
    renderLeaderboardTable();
    renderFunStatistics();
    renderBestMatchesTable();
    await renderRecentAttacksTable();
    await DataStore.refreshSyncStatus();
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}

async function triggerFetchMatches() { await triggerManualSync(); }

function compareCompetitionRank(a, b) {
  const rate = duo => Number(duo.wins) / ((Number(duo.wins) + Number(duo.losses)) || 1);
  const tiers = ['UNRANKED', 'IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER'];
  const tier = duo => Math.max(0, tiers.indexOf(String(duo.tier || '').toUpperCase()));
  const division = duo => tier(duo) >= 8 || tier(duo) === 0 ? 0 : ({IV: 0, III: 1, II: 2, I: 3}[String(duo.division || '').toUpperCase()] || 0);
  const lp = duo => tier(duo) === 0 ? 0 : Number(duo.lp) || 0;
  return tier(b) - tier(a) || division(b) - division(a) || lp(b) - lp(a) || rate(b) - rate(a) || String(a.id).localeCompare(String(b.id));
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
  toast.textContent = msg;
  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
  }, 3500);
}

/* Player/Duo Detail Modal */
let modalRequest = 0;
async function openDuoModal(id, offset = 0) {
  const request = ++modalRequest;
  let duo = currentDuos.find(d => d.id === id);
  if (!duo) return;

  const modalOverlay = document.getElementById('modal-overlay');
  const modalContent = document.getElementById('modal-content');
  if (!modalOverlay || !modalContent) return;

  let page;
  try { page = await DataStore.getHistory(id, offset); }
  catch (error) { showToast(error.message); return; }
  if (request !== modalRequest) return;
  duo = {...duo, history: page.matches};

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
          ${m.pentaKill ? `<span class="match-result-badge" style="background: linear-gradient(135deg, #ff0055, #ffaa00); color: #fff; font-weight: 800; box-shadow: 0 0 10px rgba(255, 0, 85, 0.6);"><i class="fa-solid fa-fire"></i> PENTAKILL</span>` : ''}
          <div style="display: flex; gap: 0.4rem;">
            <img class="champ-icon" src="https://ddragon.leagueoflegends.com/cdn/14.15.1/img/champion/${escapeHtml(m.championP1)}.png" title="${escapeHtml(m.championP1)}">
            ${m.championP2 ? `<img class="champ-icon" src="https://ddragon.leagueoflegends.com/cdn/14.15.1/img/champion/${escapeHtml(m.championP2)}.png" title="${escapeHtml(m.championP2)}">` : ''}
          </div>
          <div>
            <div style="font-size: 0.9rem; font-weight: 700;">Campeón: ${escapeHtml(m.championP1)} | KDA: ${escapeHtml(m.kda1)}${m.kda2 ? ` | ${escapeHtml(m.kda2)}` : ''}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">Duración: ${escapeHtml(m.duration)} • Ranked Solo/Duo${m.date ? ` • <i class="fa-regular fa-calendar"></i> ${escapeHtml(m.date)}` : ''}</div>
          </div>
        </div>
        <div class="lp-gain ${m.result === 'WIN' ? 'lp-positive' : 'lp-negative'}">
          ${escapeHtml(m.lpChange)}
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
        <span>${escapeHtml(duo.tier)} ${escapeHtml(duo.division)}</span>
        <span style="color: var(--gold-hextech); font-weight: 800;">${escapeHtml(duo.lp)} LP</span>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
      <div class="stat-card">
        <div class="stat-label">Winrate Global</div>
        <div class="stat-value text-gradient-gold">${winrate}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Victorias / Derrotas</div>
        <div class="stat-value" style="font-size: 1.3rem;">${escapeHtml(duo.wins)}W / ${escapeHtml(duo.losses)}L</div>
      </div>
    </div>

    <h3 class="font-heading" style="font-size: 1.1rem; color: var(--cyan-primary); margin-bottom: 1rem;">
      <i class="fa-solid fa-history"></i> Historial Reciente (Mostrando las ${page.matches.length} partidas desde la ${page.total ? offset + 1 : 0}, de ${page.total} registradas)
    </h3>
    <div style="max-height: 450px; overflow-y: auto; padding-right: 0.5rem;">
      ${historyHtml}
    </div>
  `;

  const navigation = document.createElement('div');
  navigation.className = 'history-navigation';
  for (const [label, next, disabled] of [['Anterior', Math.max(0, offset - 30), offset === 0], ['Siguiente', offset + 30, offset + page.matches.length >= page.total]]) {
    const button = document.createElement('button');
    button.className = 'btn-refresh';
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener('click', () => openDuoModal(id, next));
    navigation.append(button);
  }
  modalContent.append(navigation);
  modalOverlay.classList.add('active');
}

function closeDuoModal() {
  modalRequest += 1;
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

document.addEventListener('click', event => {
  const button = event.target.closest('[data-history-id]');
  if (button) { event.stopPropagation(); openDuoModal(button.dataset.historyId); }
});




function renderEloChart(duo) {
  const points = (duo.eloHistory || []).filter(p => Number.isFinite(Number(p.totalLp)) && /^\d{4}-\d{2}-\d{2}$/.test(p.date));
  if (!points.length) return '<div class="elo-chart"><h3>Evolución de ELO</h3><p>La gráfica aparecerá cuando se registre el primer dato de ELO.</p></div>';
  const width = 900, height = 230, left = 76, right = 18, top = 24, bottom = 36;
  const values = points.map(p => Number(p.totalLp));
  const min = Math.max(0, Math.min(...values) - 60), max = Math.max(...values) + 60;
  const dates = points.map(p => Date.parse(p.date + 'T12:00:00Z'));
  const x = i => points.length === 1 ? (width + left - right) / 2 : left + (dates[i] - dates[0]) / (dates.at(-1) - dates[0] || 1) * (width-left-right);
  const y = value => top + (max-value)/(max-min || 1)*(height-top-bottom);
  const label = p => {
    const games = Number(p.wins) + Number(p.losses);
    return `${new Date(p.date + 'T12:00:00').toLocaleDateString('es-ES', {day:'2-digit',month:'short'})} · ${p.tier} ${p.division || ''} · ${p.lp} LP · ${p.wins}W / ${p.losses}L${games ? ' · ' + Math.round(Number(p.wins)/games*100) + '%' : ''}${p.source === 'initial' ? ' · Punto inicial: rango guardado' : ''}`;
  };
  const rankLabel = value => {
    const tiers = ['Iron','Bronze','Silver','Gold','Platinum','Emerald','Diamond'];
    const n = Math.max(0,Math.round(value));
    return n >= 2800 ? `Master+ ${n-2800} LP` : `${tiers[Math.floor(n/400)]} ${['IV','III','II','I'][Math.floor(n%400/100)]} ${n%100}`;
  };
  const line = points.map((p,i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(p.totalLp).toFixed(2)}`).join(' ');
  const ticks = [min,(min+max)/2,max].map(v => `<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" class="elo-grid-line"/><text x="${left-8}" y="${y(v)+4}" text-anchor="end">${escapeHtml(rankLabel(v))}</text>`).join('');
  const step = Math.max(1, Math.ceil(points.length/7));
  return `<div class="elo-chart"><h3>Evolución de ELO</h3><div class="elo-chart-scroll"><svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Evolución diaria del ELO de ${escapeHtml(duo.teamName)}">
    ${ticks}<path d="${line}" class="elo-line"/>
    ${points.map((p,i) => `<circle cx="${x(i)}" cy="${y(p.totalLp)}" r="5" class="elo-point" tabindex="0" role="button" aria-label="${escapeHtml(label(p))}" data-elo-detail="${escapeHtml(label(p))}"><title>${escapeHtml(label(p))}</title></circle>${i%step===0 || i===points.length-1 ? `<text x="${x(i)}" y="${height-10}" text-anchor="middle">${escapeHtml(new Date(p.date+'T12:00:00').toLocaleDateString('es-ES',{day:'2-digit',month:'short'}))}</text>` : ''}`).join('')}
    </svg></div><p class="elo-chart-detail" aria-live="polite">${escapeHtml(label(points.at(-1)))}</p><p class="elo-chart-note">Último ELO registrado de cada día. ${points.length === 1 ? 'La curva aparecerá al registrar más días. ' : ''}Sin datos anteriores al inicio del registro. Pasa por un punto o tócalo para ver el detalle.</p></div>`;
}

for (const type of ['pointerover', 'focusin', 'click']) {
  document.addEventListener(type, event => {
    const point = event.target.closest('[data-elo-detail]');
    if (point) point.closest('.elo-chart').querySelector('.elo-chart-detail').textContent = point.dataset.eloDetail;
  });
}


function renderCombinedDuoStats(duo) {
  const insights = duo.playerInsights || {};
  const players = [insights.player1, duo.player2 ? insights.player2 : null].filter(p => p && Number(p.gamesAnalyzed) > 0 && p.totals);
  const totals = players.reduce((sum, player) => {
    for (const key of ['kills', 'deaths', 'assists']) sum[key] += Number(player.totals[key]) || 0;
    return sum;
  }, {kills: 0, deaths: 0, assists: 0});
  const number = value => value.toLocaleString('es-ES');
  const kda = players.length ? ((totals.kills + totals.assists) / Math.max(1, totals.deaths)).toFixed(2) : '—';
  return `<div class="duo-combined-stats" role="group" aria-label="KDA y estadísticas combinadas del dúo">
    <div class="duo-combined-kda"><strong>${kda}</strong><span>KDA combinado</span></div>
    <div class="duo-combined-totals"><div aria-label="${totals.kills} asesinatos, ${totals.deaths} muertes, ${totals.assists} asistencias"><strong class="combined-kills">${number(totals.kills)}</strong><span> / </span><strong class="combined-deaths">${number(totals.deaths)}</strong><span> / </span><strong class="combined-assists">${number(totals.assists)}</strong></div><span>Asesinatos / Muertes / Asistencias</span></div>
    <span class="duo-combined-note">${players.length ? 'Totales de ambos integrantes' : 'Pendiente de estadísticas'}<small>${players.length ? 'Según las estadísticas disponibles' : 'Se actualizará al sincronizar'}</small></span>
  </div>`;
}
