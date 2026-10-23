/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Main Frontend Logic (app.js)
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById("leaderboard-tbody")) initApp();
});

let currentDuos = [];
let currentConfig = {};
let bestMatchesMode = 'duo';
let countdownInterval = null;
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
  window.StatProgression?.init();

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
        await window.StatProgression?.refresh();
      }
    } finally { setTimeout(refresh, 15000); }
  }
  setTimeout(refresh, 15000);
}

/* Header & Timer */
function setupHeaderConfig() {
  const titleEl = document.getElementById('challenge-title');
  if (titleEl) titleEl.textContent = currentConfig.challengeTitle;
}

function startCountdownTimer() {
  if (countdownInterval !== null) clearInterval(countdownInterval);
  updateCountdownTimer();
  countdownInterval = setInterval(updateCountdownTimer, 1000);
}

function updateCountdownTimer(now = Date.now()) {
  const countdownEl = document.getElementById('countdown-timer');
  if (!countdownEl) return;
  const label = document.getElementById('countdown-label');
  const start = tournamentDateTimestamp(currentConfig.startDate || DEFAULT_CONFIG.startDate);
  const end = tournamentDateTimestamp(currentConfig.endDate || DEFAULT_CONFIG.endDate);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    countdownEl.dataset.phase = 'invalid';
    if (label) label.textContent = 'Fechas del torneo';
    countdownEl.textContent = 'Pendientes de configurar';
    return;
  }
  const beforeStart = now < start;
  if (label) label.textContent = now >= end ? 'Torneo finalizado' : beforeStart ? 'El torneo empieza en' : 'El torneo acaba en:';
  countdownEl.dataset.phase = now >= end ? 'finished' : beforeStart ? 'upcoming' : 'active';
  if (now >= end) {
    countdownEl.innerHTML = '<span class="text-gradient-pink">¡DESAFÍO FINALIZADO!</span>';
    return;
  }
  const diff = (beforeStart ? start : end) - now;
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

/* The public W/L describes the challenge history, not a Riot season. */
function challengeRecord(duo) {
  const record = duo.tournamentRecord || {};
  const wins = Math.max(0, Number(record.wins) || 0);
  const losses = Math.max(0, Number(record.losses) || 0);
  return {wins, losses, games: wins + losses, winrate: wins + losses ? wins / (wins + losses) : 0};
}

/* Stats Overview */
function renderStatsOverview() {
  const duosCountEl = document.getElementById('stat-total-duos');
  const totalGamesEl = document.getElementById('stat-total-games');
  const completedPenaltiesEl = document.getElementById('stat-completed-penalties');
  const liveCountEl = document.getElementById('stat-live-count');

  if (duosCountEl) duosCountEl.textContent = currentDuos.length;

  let totalGames = 0;
  let liveCount = 0;
  let completedPenalties = 0;
  currentDuos.forEach(d => {
    totalGames += challengeRecord(d).games;
    if (d.twitchIsLive === true) liveCount++;
    completedPenalties += (d.activeDebuffs || []).filter(penalty =>
      penalty.status !== 'CANCELLED' && (penalty.status === 'COMPLETED' || penalty.resolved === true)
    ).length;
  });

  if (totalGamesEl) totalGamesEl.textContent = totalGames;
  if (liveCountEl) liveCountEl.textContent = `${liveCount} ${liveCount === 1 ? 'Dúo' : 'Dúos'}`;

  if (completedPenaltiesEl) completedPenaltiesEl.textContent = completedPenalties;
}

/* Leaderboard Rendering */
function toggleDuoAccordion(duoId) {
  const wasExpanded = expandedDuoIds.has(duoId);
  expandedDuoIds.clear();
  if (!wasExpanded) expandedDuoIds.add(duoId);
  renderLeaderboardTable();
}

function renderPlayerInsightCard(player, insight) {
  const champion = insight?.topChampion;
  const playerName = player?.name || 'Jugador';
  const riotId = `${playerName}#${player?.tag || 'EUW'}`;
  const totals = insight?.totals;
  const hasStats = Number(insight?.gamesAnalyzed) > 0 && totals;
  const kda = hasStats ? (((Number(totals.kills) || 0) + (Number(totals.assists) || 0)) / Math.max(1, Number(totals.deaths) || 0)).toFixed(2) : '—';
  const role = POSITION_LABELS[insight?.mostPlayedPosition?.position || (player?.mainRoleSource === 'most_played' ? player.mainRole : null)] || 'Pendiente de partidas';
  const opggUrl = normalizeOpggUrl(player?.opggUrl);
  return `<article class="player-insight-card${hasStats ? '' : ' is-empty'}">
    ${player?.avatar ? `<img class="insight-player-avatar" src="${escapeHtml(player.avatar)}" alt="${escapeHtml(playerName)}" onerror="this.style.visibility='hidden';">` : '<span class="insight-player-avatar insight-avatar-placeholder" aria-hidden="true"><i class="fa-solid fa-user"></i></span>'}
    <div class="insight-content">
      <div class="insight-heading"><h3>${escapeHtml(riotId)}</h3>${opggUrl ? `<a class="opgg-profile-link" href="${escapeHtml(opggUrl)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(`Ver ${riotId} en OP.GG (nueva pestaña)`)}">OP.GG <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></a>` : ''}</div>
      <div class="insight-metrics participant-insight-metrics">
        <div><span>KDA</span><strong>${kda}</strong></div>
        <div><span>Rol principal</span><strong>${role}</strong></div>
        <div><span>Campeón más jugado</span><strong>${escapeHtml(championDisplayName(champion?.name) || 'Sin datos')}</strong></div>
      </div>
    </div>
  </article>`;
}

function renderParticipantCell(duo, playerKey) {
  const player = duo[playerKey];
  if (!player?.name) return '<span class="player-rank-pending">—</span>';
  const name = player.displayName || player.name;
  const twitch = participantTwitch(duo, playerKey);
  return `<div class="participant-cell">
    <strong class="participant-name">${escapeHtml(name)}</strong>
    <div data-player-rank="${playerKey}">${renderPlayerRank(duo, playerKey)}</div>
    ${twitch.url ? `<a class="twitch-link${twitch.live ? ' is-live' : ''}" href="${escapeHtml(twitch.url)}" target="_blank" rel="noopener noreferrer" aria-label="${twitch.live ? 'Ver en directo a' : 'Ver en Twitch a'} ${escapeHtml(name)}">
      <i class="fa-brands fa-twitch" aria-hidden="true"></i>${twitch.live ? '<span class="live-dot" aria-hidden="true"></span> EN DIRECTO' : 'Ver en Twitch'}
    </a>` : ''}
  </div>`;
}

function renderPlayerRank(duo, playerKey) {
  const player = duo[playerKey];
  if (!player?.name) return '<span class="player-rank-pending">—</span>';
  // Older saves have only the first participant's rank on the duo itself.
  const rank = competitionPlayerRank(duo, playerKey);
  if (!rank?.tier) return '<span class="player-rank-pending">Pendiente</span>';
  const tier = String(rank.tier);
  const isUnranked = tier.toUpperCase() === 'UNRANKED';
  const hasDivision = !isUnranked && !['MASTER', 'GRANDMASTER', 'CHALLENGER'].includes(tier.toUpperCase());
  const label = isUnranked ? 'Sin clasificar' : `${tier}${hasDivision && rank.division ? ' ' + rank.division : ''}`;
  return `<div class="tier-pill player-rank-pill" title="${escapeHtml(participantEloAccount(player).name)}#${escapeHtml(participantEloAccount(player).tag || 'EUW')}">
    <span style="color: ${getTierColor(tier)};">${escapeHtml(label)}</span>
    ${isUnranked ? '' : `<span class="player-rank-lp">(${Number(rank.lp) || 0} LP)</span>`}
  </div>`;
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
                        p2Name.includes(query) ||
                        [duo.player1, duo.player2].some(player => String(player?.displayName || '').toLowerCase().includes(query));
    const matchesTier = selectedTier === 'ALL' || competitionAverageRank(duo).tier === selectedTier;
    return matchesName && matchesTier;
  });

  filtered.sort((a, b) => {
    if (sortBy === 'RANK' || sortBy === 'NET_LP') {
      return compareCompetitionRank(a, b);
    }
    if (sortBy === 'WINRATE') {
      return challengeRecord(b).winrate - challengeRecord(a).winrate;
    }
    if (sortBy === 'GAMES') return challengeRecord(b).games - challengeRecord(a).games;
    if (sortBy === 'NAME') return a.teamName.localeCompare(b.teamName);
    return 0;
  });

  tbody.innerHTML = '';

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 3rem; color: var(--text-muted);">
          <i class="fa-solid fa-search" style="font-size: 2rem; margin-bottom: 1rem; color: var(--cyan-primary);"></i>
          <p>No se encontraron registros con los filtros seleccionados.</p>
        </td>
      </tr>
    `;
    return;
  }

  const positions = new Map([...currentDuos].sort(compareCompetitionRank).map((duo, index) => [duo.id, index + 1]));
  filtered.forEach(duo => {
    const rankPos = competitionAverageRank(duo).ready ? positions.get(duo.id) : null;
    const record = challengeRecord(duo);
    const winrate = Math.round(record.winrate * 100);

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
        <div class="${posClass}"><span class="rank-position-number">${rankPos ?? '—'}</span></div>
      </td>
      <td>
        <div class="team-name-cell">
          <div class="team-name-heading">
            <i class="fa-solid fa-users text-cyan" aria-hidden="true"></i>
            <span>${escapeHtml(duo.teamName)}</span>
          </div>

        </div>
      </td>
      <td class="player-rank-cell">${renderParticipantCell(duo, 'player1')}</td>
      <td class="player-rank-cell">${renderParticipantCell(duo, 'player2')}</td>
      <td>
        <div class="winrate-wrapper">
          <div class="winrate-text">
            <span>${winrate}%</span>
            <span style="color: var(--text-muted);">${escapeHtml(String(record.wins))}W / ${escapeHtml(String(record.losses))}L</span>
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
        <div class="shells-summary-cell" aria-label="${Number(duo.shellsLaunched) || 0} pepazos lanzados y ${Number(duo.shellsReceived) || 0} recibidos">
          <span class="shell-count shell-count-launched" title="Pepazos lanzados">
            <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i>
            <strong>${Number(duo.shellsLaunched) || 0}</strong>
            <small>Lanzados</small>
          </span>
          <span class="shell-count-divider" aria-hidden="true"></span>
          <span class="shell-count shell-count-received" title="Pepazos recibidos">
            <i class="fa-solid fa-arrow-down" aria-hidden="true"></i>
            <strong>${Number(duo.shellsReceived) || 0}</strong>
            <small>Recibidos</small>
          </span>
        </div>
      </td>
      <td class="leaderboard-expand-column">
        <button type="button" class="duo-expand-button" aria-expanded="${isExpanded}" aria-controls="${escapeHtml(accordionId)}" aria-label="${isExpanded ? 'Plegar' : 'Desplegar'} ${escapeHtml(duo.teamName)}">
          <i class="fa-solid fa-chevron-down accordion-chevron" aria-hidden="true"></i>
        </button>
      </td>
    `;
    tr.querySelector('.duo-expand-button').onclick = event => {
      event.stopPropagation();
      toggleDuoAccordion(duo.id);
      document.getElementById(accordionId)?.previousElementSibling?.querySelector('.duo-expand-button')?.focus({preventScroll: true});
    };
    tbody.appendChild(tr);

    const detailsRow = document.createElement('tr');
    detailsRow.id = accordionId;
    detailsRow.className = 'duo-insights-row';
    detailsRow.hidden = !isExpanded;
    const insights = duo.playerInsights || {};
    detailsRow.innerHTML = `
      <td colspan="8">
        <section class="duo-insights-panel" aria-label="Estadísticas individuales de ${escapeHtml(duo.teamName)}">
          <div class="insights-panel-heading">
            <span>Estadísticas individuales · Solo/Duo desde el inicio del reto</span>
            <div class="insights-panel-actions">
              <button type="button" class="btn-refresh duo-history-button" data-history-id="${escapeHtml(duo.id)}">
                Ver partidas <i class="fa-solid fa-chevron-right" aria-hidden="true"></i>
              </button>
            </div>
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
  const solo = bestMatchesMode === 'solo';
  document.querySelectorAll('[data-best-mode]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.bestMode === bestMatchesMode));
    button.onclick = () => {
      bestMatchesMode = button.dataset.bestMode;
      renderBestMatchesTable();
    };
  });
  const labels = {
    'best-matches-entity': solo ? 'Jugador' : 'Dúo',
    'best-matches-champions': solo ? 'Campeón' : 'Campeones',
    'best-matches-positions': solo ? 'Línea' : 'Líneas',
    'best-matches-kda': solo ? 'KDA individual' : 'KDA combinado',
    'best-matches-formula': `KDA ${solo ? 'individual' : 'combinado'} = (K + A) ÷ muertes`
  };
  Object.entries(labels).forEach(([id, label]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = label;
  });
  if (solo) {
    renderBestSoloMatches(tbody);
    return;
  }

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
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="best-matches-empty">
          <i class="fa-solid fa-rotate"></i>
          Todavía no hay partidas completas para comparar.
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
    const p1Name = escapeHtml(championDisplayName(p1.championName) || 'Unknown');
    const p2Name = escapeHtml(championDisplayName(p2.championName) || 'Unknown');
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
            <span><img src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${p1Champion}.png" alt="${p1Name}"> ${p1Name}</span>
            <span><img src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${p2Champion}.png" alt="${p2Name}"> ${p2Name}</span>
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

function renderBestSoloMatches(tbody) {
  const ranked = currentDuos.flatMap(duo => ['player1', 'player2'].flatMap(key => {
    const player = duo[key];
    if (!player || !(player.displayName || player.name)) return [];
    return [{player, teamName: duo.teamName, match: duo.playerInsights?.[key]?.bestMatch}];
  })).sort((a, b) => {
    if (!a.match && !b.match) return (a.player.displayName || a.player.name).localeCompare(b.player.displayName || b.player.name);
    if (!a.match) return 1;
    if (!b.match) return -1;
    return (b.match.kda - a.match.kda) ||
      ((b.match.kills + b.match.assists) - (a.match.kills + a.match.assists)) ||
      (a.match.deaths - b.match.deaths);
  });
  tbody.innerHTML = ranked.map(({player, teamName, match}, index) => {
    const name = escapeHtml(player.displayName || player.name);
    const identity = `<strong class="best-match-team">${name}</strong><span class="best-match-date">${escapeHtml(teamName || '')}</span>`;
    if (!match) return `<tr class="best-match-unavailable"><td><span class="best-match-position">—</span></td><td>${identity}</td><td colspan="5"><span class="best-match-no-data">Sin partidas individuales registradas</span></td></tr>`;
    const champion = escapeHtml(match.championName || 'Unknown');
    const championName = escapeHtml(championDisplayName(match.championName) || 'Unknown');
    return `<tr>
      <td><span class="best-match-position">${index + 1}</span></td>
      <td>${identity}<span class="best-match-date">${escapeHtml(match.date || '')}</span></td>
      <td><div class="best-champions"><span><img src="https://ddragon.leagueoflegends.com/cdn/15.3.1/img/champion/${champion}.png" alt="${championName}"> ${championName}</span></div></td>
      <td><span class="best-lines">${POSITION_LABELS[match.position] || 'Sin datos'}</span></td>
      <td><strong class="combined-kda">${Number(match.kda).toFixed(2)}</strong></td>
      <td><strong>${match.kills}/${match.deaths}/${match.assists}</strong></td>
      <td><span class="best-result ${match.result === 'WIN' ? 'best-result-win' : 'best-result-loss'}">${match.result === 'WIN' ? 'Victoria' : 'Derrota'}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="best-matches-empty">Todavía no hay partidas individuales para comparar.</td></tr>';
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
    container.innerHTML = '<p class="fun-stats-empty"><i class="fa-solid fa-hourglass-half"></i> Todavía no hay estadísticas individuales.</p>';
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

  // Mostrar las últimas 10 aperturas de pepazos
  const recentEvents = events.slice(0, 10);

  recentEvents.forEach(ev => {
    const tr = document.createElement('tr');
    const pen = ev.penalty || {};
    const icon = pen.icon || '🐢⚡';
    const penName = pen.name || 'Pepazo';
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
          ${penaltyAssignmentText(ev) ? `<span class="penalty-assignment">${escapeHtml(penaltyAssignmentText(ev))}</span>` : ''}
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
    await window.StatProgression?.refresh();
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}

async function triggerFetchMatches() { await triggerManualSync(); }

function competitionPlayerRank(duo, key) {
  const player = duo[key];
  if (!player?.name) return null;
  if (player.accounts?.length) return participantEloAccount(player).rank || null;
  return Object.prototype.hasOwnProperty.call(player, 'rank') ? player.rank : key === 'player1' ? duo : null;
}

function competitionRankPoints(rank) {
  if (!rank) return null;
  const tiers = {IRON:0,BRONZE:400,SILVER:800,GOLD:1200,PLATINUM:1600,EMERALD:2000,DIAMOND:2400,MASTER:2800,GRANDMASTER:2800,CHALLENGER:2800};
  const divisions = {IV:0,III:100,II:200,I:300};
  const tier = String(rank.tier || '').toUpperCase();
  const division = String(rank.division || '').toUpperCase();
  const lp = Number(rank.lp || 0);
  if (!(tier in tiers) || !Number.isFinite(lp) || lp < 0 || (tiers[tier] < 2800 && !(division in divisions))) return null;
  return tiers[tier] + (tiers[tier] < 2800 ? divisions[division] : 0) + lp;
}

function competitionAverageRank(duo) {
  const ranks = ['player1', 'player2'].map(key => competitionPlayerRank(duo, key));
  const points = ranks.map(competitionRankPoints);
  if (points.some(p => p === null)) return {ready:false,totalLp:-1,rate:0,tier:'UNRANKED',label:'Media de ELO pendiente'};
  const totalLp = (points[0] + points[1]) / 2;
  const wins = ranks.reduce((sum, rank) => sum + Math.max(0, Number(rank.wins) || 0), 0);
  const losses = ranks.reduce((sum, rank) => sum + Math.max(0, Number(rank.losses) || 0), 0);
  const tiers = ['IRON','BRONZE','SILVER','GOLD','PLATINUM','EMERALD','DIAMOND','MASTER'];
  const tier = tiers[Math.min(7, Math.floor(totalLp / 400))];
  return {ready:true,totalLp,rate:wins / Math.max(1,wins + losses),tier,label:`ELO medio: ${totalLp.toLocaleString('es-ES', {maximumFractionDigits:2})} pts`};
}

function compareCompetitionRank(a, b) {
  const first = competitionAverageRank(a), second = competitionAverageRank(b);
  return Number(second.ready) - Number(first.ready) || second.totalLp - first.totalLp || second.rate - first.rate || String(a.id).localeCompare(String(b.id));
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

  const accounts = ['player1', 'player2'].filter(key => duo[key]?.name).map(key => `${duo[key].name}${duo[key].tag ? '#' + duo[key].tag : ''}`);
  modalContent.innerHTML = `
    <div class="match-history-header">
      <h2>Historial de ${escapeHtml(duo.teamName || accounts.join(' & '))}</h2>
      <p>${accounts.map(escapeHtml).join(' & ')}</p>
    </div>
    <p class="match-history-count">Mostrando las ${page.matches.length} partidas desde la ${page.total ? offset + 1 : 0}, de ${page.total} registradas</p>
    <div class="match-history-list"></div>
  `;
  MatchHistory.mount(modalContent.querySelector('.match-history-list'), duo, page.matches);

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
  if (t === 'UNRANKED') return 0;
  return (tierMap[t] || 0) + (tierMap[t] >= 2800 ? 0 : divMap[d] || 0) + (parseInt(lp, 10) || 0);
}

function str(val) { return String(val || ''); }

document.addEventListener('click', event => {
  const button = event.target.closest('[data-history-id]');
  if (button) { event.stopPropagation(); openDuoModal(button.dataset.historyId); }
});




function renderEloChart(duo) {
  const series = ['player1', 'player2'].filter(key => duo[key]?.name).map(key => {
    const player = duo[key];
    let history = player.eloHistory;
    if (!Array.isArray(history)) {
      history = key === 'player1' && player.rank !== null ? duo.eloHistory || [] : [];
      if (!history.length && player.rank?.observedAt) {
        const rank = player.rank;
        const date = new Date(rank.observedAt * 1000);
        history = [{...rank, date: `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`,
          totalLp: calcTotalLpHelper(rank.tier, rank.division, rank.lp)}];
      }
    }
    const points = [...new Map(history.filter(p => p && p.totalLp != null && Number.isFinite(Number(p.totalLp)) &&
      /^\d{4}-\d{2}-\d{2}$/.test(p.date) && Number.isFinite(Date.parse(p.date + 'T12:00:00Z')) &&
      String(p.tier).toUpperCase() !== 'UNRANKED').map(p => [p.date, p])).values()].sort((a,b) => a.date.localeCompare(b.date));
    return {key, name: `${player.name}${player.tag ? '#' + player.tag : ''}`, points};
  });
  const legend = `<div class="elo-chart-legend">${series.map(s => `<span class="elo-series-${s.key}"><i aria-hidden="true"></i>${escapeHtml(s.name)}${!s.points.length ? ' · Pendiente de rango' : s.points.length === 1 ? ' · Primer registro' : ''}</span>`).join('')}</div>`;
  const allPoints = series.flatMap(s => s.points);
  if (!allPoints.length) return `<div class="elo-chart"><h3>Evolución de ELO</h3>${legend}<p>La gráfica aparecerá cuando se registre el primer dato de ELO clasificatorio.</p></div>`;
  const width = 900, height = 230, left = 76, right = 18, top = 24, bottom = 36;
  const values = allPoints.map(p => Number(p.totalLp));
  const min = Math.max(0, Math.min(...values) - 60), max = Math.max(...values) + 60;
  const days = [...new Set(allPoints.map(p => p.date))].sort();
  const dates = days.map(day => Date.parse(day + 'T12:00:00Z'));
  const x = day => days.length === 1 ? (width + left - right) / 2 : left + (Date.parse(day + 'T12:00:00Z') - dates[0]) / (dates.at(-1) - dates[0]) * (width-left-right);
  const y = value => top + (max-value)/(max-min || 1)*(height-top-bottom);
  const formatChartDate = date => `${date.slice(8, 10)}-${date.slice(5, 7)}`;
  const label = (p, s) => {
    const games = Number(p.wins) + Number(p.losses);
    const results = p.wins != null && p.losses != null ? ` · ${p.wins}W / ${p.losses}L${games ? ' · ' + Math.round(Number(p.wins)/games*100) + '%' : ''}` : '';
    return `${s.name} · ${formatChartDate(p.date)} · ${p.tier} ${p.division || ''} · ${p.lp} LP${results}${p.source === 'initial' ? ' · Punto inicial: rango guardado' : ''}`;
  };
  const rankLabel = value => {
    const tiers = ['Iron','Bronze','Silver','Gold','Platinum','Emerald','Diamond'];
    const n = Math.max(0,Math.round(value));
    return n >= 2800 ? `Master+ ${n-2800} LP` : `${tiers[Math.floor(n/400)]} ${['IV','III','II','I'][Math.floor(n%400/100)]} ${n%100}`;
  };
  const ticks = [min,(min+max)/2,max].map(v => `<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" class="elo-grid-line"/><text x="${left-8}" y="${y(v)+4}" text-anchor="end">${escapeHtml(rankLabel(v))}</text>`).join('');
  const step = Math.max(1, Math.ceil(days.length/7));
  const curves = series.map(s => {
    if (!s.points.length) return '';
    const line = s.points.map((p,i) => `${i ? 'L' : 'M'}${x(p.date).toFixed(2)},${y(p.totalLp).toFixed(2)}`).join(' ');
    return `<g class="elo-series-${s.key}" data-elo-player="${s.key}"><path d="${line}" class="elo-line"/>${s.points.map(p => `<circle cx="${x(p.date)}" cy="${y(p.totalLp)}" r="5" class="elo-point" tabindex="0" role="button" aria-label="${escapeHtml(label(p,s))}" data-elo-detail="${escapeHtml(label(p,s))}"><title>${escapeHtml(label(p,s))}</title></circle>`).join('')}</g>`;
  }).join('');
  const dateLabels = days.map((day,i) => i%step===0 || i===days.length-1 ? `<text x="${x(day)}" y="${height-10}" text-anchor="middle">${formatChartDate(day)}</text>` : '').join('');
  return `<div class="elo-chart"><h3>Evolución de ELO</h3>${legend}<div class="elo-chart-scroll"><svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Evolución diaria del ELO de ambos integrantes de ${escapeHtml(duo.teamName)}">
    ${ticks}${curves}${dateLabels}
    </svg></div><p class="elo-chart-detail" aria-live="polite">${escapeHtml(series.filter(s => s.points.length).map(s => label(s.points.at(-1),s)).join(' | '))}</p><p class="elo-chart-note">Pasa por un punto o tócalo para ver el ELO de ese día.</p></div>`;
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
    <span class="duo-combined-note">${players.length === 2 ? 'Totales de ambos integrantes' : players.length ? 'Totales disponibles' : 'Sin estadísticas'}</span>
  </div>`;
}
