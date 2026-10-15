/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Player Panel Logic (player.js)
   ========================================================================== */

let activeDuo = null;
let rouletteBusy = false;
const ROULETTE_RESULT_HOLD_MS = 13500;
let allDuos = [];
let playerPanelTeamId = null;
let playerPanelTab = 'shells';
let playerPenaltyView = 'pending';
let playerHistoryPage = 1;
const PLAYER_HISTORY_PAGE_SIZE = 20;
let playerSessionToken = sessionStorage.getItem('pepes_player_token') || '';

document.addEventListener('DOMContentLoaded', () => {
  initPlayerApp();
});

async function initPlayerApp() {
  allDuos = await DataStore.getDuos();
  populateTeamsDropdown();

  // Check existing session
  const savedSession = sessionStorage.getItem('pepes_player_session');
  if (savedSession && playerSessionToken) {
    try {
      const state = await DataStore.getPlayerState(playerSessionToken);
      if (!state.success || !state.duo) {
        if (state.status === 401) throw new Error('Sesión caducada');
        showLoginView(); setupPlayerListeners(); return;
      }
      activeDuo = state.duo;
      sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
      showDashboardView();
    } catch (e) {
      sessionStorage.removeItem('pepes_player_session');
      const previousToken = playerSessionToken;
      sessionStorage.removeItem('pepes_player_token');
      playerSessionToken = '';
      DataStore.logoutPlayer(previousToken);
      document.dispatchEvent(new Event('player-session-changed'));
      showLoginView();
    }
  } else {
    showLoginView();
  }

  setupPlayerListeners();

  let signature = '';
  async function refresh() {
    try {
      if (!document.hidden) {
        allDuos = await DataStore.getDuos();
        if (activeDuo && !rouletteBusy) {
          const state = await DataStore.getPlayerState(playerSessionToken);
          if (rouletteBusy) return;
          if (state.success && state.duo) {
            const next = JSON.stringify([state.duo, allDuos]);
            activeDuo = state.duo;
            if (next !== signature) { signature = next; renderDashboardData(); }
          } else if (state.status === 401) {
            activeDuo = null;
            playerSessionToken = '';
            sessionStorage.removeItem('pepes_player_session');
            sessionStorage.removeItem('pepes_player_token');
            showLoginView();
          }
        } else { populateTeamsDropdown(); }
      }
    } finally { setTimeout(refresh, 15000); }
  }
  setTimeout(refresh, 15000);
}

function populateTeamsDropdown() {
  const teamSelect = document.getElementById('login-team-select');
  if (!teamSelect) return;

  const selectedTeam = teamSelect.value;
  teamSelect.innerHTML = '<option value="">Selecciona tu equipo / pareja...</option>';
  allDuos.forEach(d => {
    const p2Str = d.player2 && d.player2.name ? ` & ${d.player2.name}` : '';
    teamSelect.add(new Option(`${d.teamName} (${d.player1.name}${p2Str})`, d.id));
  });
  if (Array.from(teamSelect.options).some(option => option.value === selectedTeam)) teamSelect.value = selectedTeam;
}

function showLoginView() {
  const loginSec = document.getElementById('player-login-section');
  const dashSec = document.getElementById('player-dashboard-section');
  if (loginSec) loginSec.style.display = 'block';
  if (dashSec) dashSec.style.display = 'none';
}

function showDashboardView() {
  const loginSec = document.getElementById('player-login-section');
  const dashSec = document.getElementById('player-dashboard-section');
  if (loginSec) loginSec.style.display = 'none';
  if (dashSec) dashSec.style.display = 'block';

  if (playerPanelTeamId !== activeDuo?.id) {
    playerPanelTeamId = activeDuo?.id;
    playerPanelTab = 'shells';
    playerPenaltyView = 'pending';
    playerHistoryPage = 1;
  }
  selectPlayerPanel(playerPanelTab);
  renderDashboardData();
}

function renderDashboardData() {
  if (rouletteBusy) return;
  if (!activeDuo) return;

  const teamNameEl = document.getElementById('dash-team-name');
  const playersEl = document.getElementById('dash-players-text');
  const tierBadgeEl = document.getElementById('dash-tier-badge');
  const shellsCountEl = document.getElementById('dash-shells-count');
  const streakTextEl = document.getElementById('dash-streak-text');
  const streakBarEl = document.getElementById('dash-streak-bar');
  const targetSelect = document.getElementById('target-team-select');

  if (teamNameEl) teamNameEl.textContent = activeDuo.teamName;
  
  const hasP2 = activeDuo.player2 && activeDuo.player2.name;
  if (playersEl) {
    playersEl.textContent = `${activeDuo.player1.name}#${activeDuo.player1.tag}` + 
                            (hasP2 ? ` & ${activeDuo.player2.name}#${activeDuo.player2.tag}` : ' (Jugador Individual)');
  }

  if (tierBadgeEl) {
    tierBadgeEl.textContent = `${activeDuo.tier} ${activeDuo.division}`;
    tierBadgeEl.style.color = getTierColor(activeDuo.tier);
  }

  const shells = activeDuo.blueShells || 0;
  if (shellsCountEl) shellsCountEl.textContent = shells;

  // Streak calculations (1 shell per 3 consecutive wins)
  const streak = activeDuo.streak || 0;
  const progressInCycle = streak % 3;
  const progressPercent = Math.min(100, Math.round((progressInCycle / 3) * 100));

  if (streakTextEl) {
    const remaining = 3 - progressInCycle;
    streakTextEl.textContent = `${streak}W racha activa • ${remaining} victoria${remaining !== 1 ? 's' : ''} más para +1 Pepazo`;
  }
  if (streakBarEl) {
    streakBarEl.style.width = `${progressPercent}%`;
  }

  // Populate Target Select (all teams except current)
  const selectedTarget = targetSelect ? targetSelect.value : "";
  if (targetSelect) {
    targetSelect.innerHTML = '<option value="">Selecciona equipo objetivo...</option>';
    allDuos.filter(d => d.id !== activeDuo.id).forEach(d => {
      targetSelect.add(new Option(`#${d.teamName} (${d.tier} ${d.division})`, d.id));
    });
  }

  if (targetSelect && Array.from(targetSelect.options).some(o => o.value === selectedTarget)) targetSelect.value = selectedTarget;

  // Render received penalties table
  renderPendingShells();
  renderOutgoingShells();
  renderActiveDebuffs();
}

function renderOutgoingShells() {
  const container = document.getElementById('outgoing-shells-list');
  if (!container || !activeDuo) return;
  const attacks = activeDuo.outgoingShellAttacks || [];
  if (!attacks.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `<div class="outgoing-shell-title">Últimos lanzamientos</div>` + attacks.slice(0, 3).map(attack => {
    const result = attack.result;
    const status = attack.status === 'PENDING_SPIN' ? 'Esperando que el rival gire' :
      attack.status === 'RETURNED' ? 'Pepazo devuelto' : (result ? result.name : attack.status);
    return `<div class="outgoing-shell-row"><span>→ ${escapeHtml(attack.targetName || 'Rival')}</span><strong>${escapeHtml(status)}</strong></div>`;
  }).join('');
}

function renderPendingShells() {
  const section = document.getElementById('pending-shells-section');
  const container = document.getElementById('pending-shells-list');
  if (!section || !container || !activeDuo) return;
  const attacks = activeDuo.pendingShellAttacks || [];
  section.style.display = attacks.length ? 'block' : 'none';
  container.innerHTML = attacks.map(attack => `
    <div class="pending-shell-card">
      <div><strong>${attack.returnedFromAttackId ? '↩️ Pepazo devuelto por' : '🐢 Pepazo de'} #${escapeHtml(attack.attackerName || 'Rival')}</strong><span>Recibido ${escapeHtml(formatIsoDate(attack.launchedAt))}</span></div>
      <div class="pending-shell-actions">
        <button type="button" class="btn-refresh btn-neon-gold" data-spin-id="${escapeHtml(attack.id)}">🎰 Girar ruleta</button>
        <button type="button" class="btn-refresh" data-spin-outside-id="${escapeHtml(attack.id)}">Girar ruleta fuera ↗</button>
      </div>
    </div>
  `).join('');
}

function selectPlayerPanel(tab) {
  playerPanelTab = tab === 'penalties' ? 'penalties' : 'shells';
  document.querySelectorAll('[data-player-panel-tab]').forEach(button => {
    const selected = button.dataset.playerPanelTab === playerPanelTab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    document.getElementById(button.getAttribute('aria-controls')).hidden = !selected;
  });
}

function playerPenaltyFinished(d) {
  return d.status === 'CANCELLED' || d.status === 'COMPLETED' || !!d.resolved;
}

function playerPenaltyGroup(d) {
  const scope = d.scope || d.penalty?.scope;
  if (scope === 'BOTH') return 'both';
  const req = d.requirements || {};
  if (scope === 'ONE') {
    const key = req.assignedPlayer;
    if (key !== 'player1' && key !== 'player2') return req.assignmentVersion >= 2 ? 'unassigned' : 'any';
    const saved = req.assignedAccount || {};
    const current = activeDuo[key] || {};
    // Account-bound assignments must not move to a replacement team member.
    const normalized = value => String(value || '').trim().toLowerCase();
    const changed = saved.puuid && current.puuid ? saved.puuid !== current.puuid :
      saved.name && (normalized(saved.name) !== normalized(current.name) || normalized(saved.tag) !== normalized(current.tag));
    return changed ? 'previous' : key;
  }
  return 'unassigned';
}

function playerPenaltyCard(d) {
  const pen = d.penalty || {};
  const retired = d.status === 'CANCELLED';
  const completed = playerPenaltyFinished(d) && !retired;
  const status = retired ? 'retired' : completed ? 'completed' : 'active';
  const date = d.assignedAt || d.timestamp || '';
  return `<article class="player-penalty-card">
    <div class="player-penalty-heading"><span aria-hidden="true">${escapeHtml(pen.icon || '⚡')}</span><h4>${escapeHtml(pen.name || 'Castigo')}</h4></div>
    <div class="penalty-assignment">${escapeHtml(penaltyAssignmentText(d, activeDuo))}</div>
    <p class="player-penalty-description">${escapeHtml(pen.desc || '')}</p>
    <div class="player-penalty-meta"><span>De #${escapeHtml(d.attacker || 'Rival')}</span>${date ? `<span>${escapeHtml(formatIsoDate(date))}</span>` : ''}</div>
    <span class="penalty-status-${status}" title="${escapeHtml(retired ? d.retirementReason || '' : '')}"><i class="fa-solid ${retired ? 'fa-ban' : completed ? 'fa-circle-check' : 'fa-clock'}" aria-hidden="true"></i> ${retired ? 'Retirado' : completed ? 'Cumplido' : 'Pendiente'}</span>
  </article>`;
}

function renderActiveDebuffs() {
  const container = document.getElementById('active-debuffs-list');
  if (!container || !activeDuo) return;
  const records = activeDuo.activeDebuffs || [];
  // Legacy free-choice penalties stay stored, but no longer appear in this panel.
  const pending = records.filter(d => !playerPenaltyFinished(d) && playerPenaltyGroup(d) !== 'any');
  const history = records.filter(playerPenaltyFinished).sort((a, b) => {
    const time = d => Number(d.assignedAtEpochMs) || Date.parse(d.assignedAt || d.timestamp || '') || 0;
    return time(b) - time(a);
  });
  document.getElementById('player-penalties-count').textContent = pending.length;
  document.getElementById('player-pending-count').textContent = pending.length;
  document.getElementById('player-history-count').textContent = history.length;
  document.querySelectorAll('[data-player-penalty-view]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.playerPenaltyView === playerPenaltyView));
  });
  if (playerPenaltyView === 'history') {
    const pages = Math.max(1, Math.ceil(history.length / PLAYER_HISTORY_PAGE_SIZE));
    playerHistoryPage = Math.min(playerHistoryPage, pages);
    const start = (playerHistoryPage - 1) * PLAYER_HISTORY_PAGE_SIZE;
    container.innerHTML = history.length ? `<div class="player-penalty-history">${history.slice(start, start + PLAYER_HISTORY_PAGE_SIZE).map(playerPenaltyCard).join('')}</div>
      <nav class="player-history-pagination" aria-label="Páginas del historial de castigos">
        <button type="button" data-player-history-step="-1" ${playerHistoryPage === 1 ? 'disabled' : ''}>Anterior</button>
        <span aria-live="polite">Página ${playerHistoryPage} de ${pages}</span>
        <button type="button" data-player-history-step="1" ${playerHistoryPage === pages ? 'disabled' : ''}>Siguiente</button>
      </nav>` : '<p class="player-penalty-empty">Todavía no hay castigos cumplidos ni retirados.</p>';
    return;
  }
  if (!pending.length) {
    container.innerHTML = '<p class="player-penalty-empty"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i> No tenéis castigos pendientes. ¡Equipo limpio! 🎉</p>';
    return;
  }
  const groups = [
    ...['player1', 'player2'].map((key, index) => {
      const player = activeDuo[key] || {};
      return {key, title: player.displayName || player.name || `Integrante ${index + 1}`,
        subtitle: player.name ? `${player.name}#${player.tag || 'EUW'}` : 'Integrante sin configurar'};
    }),
    {key:'both', title:'Ambos integrantes', subtitle:'Debéis cumplirlos juntos en la misma partida.'},
    {key:'previous', title:'Asignaciones anteriores', subtitle:'Siguen vinculados a la cuenta que recibió el castigo.'},
    {key:'unassigned', title:'Asignación pendiente', subtitle:'Revisad la asignación antes de intentar cumplirlos.'}
  ];
  container.innerHTML = `<div class="player-penalty-groups">${groups.map(group => {
    const items = pending.filter(d => playerPenaltyGroup(d) === group.key);
    if (!items.length && !['player1','player2','both'].includes(group.key)) return '';
    return `<section class="player-penalty-group ${group.key.startsWith('player') ? '' : 'player-penalty-group-shared'}" data-penalty-group="${group.key}">
      <h3>${escapeHtml(group.title)} <span class="player-tab-count">${items.length}</span></h3>
      <p class="player-penalty-group-subtitle">${escapeHtml(group.subtitle)}</p>
      ${items.length ? items.map(playerPenaltyCard).join('') : '<p class="player-penalty-empty">Sin castigos pendientes.</p>'}
    </section>`;
  }).join('')}</div>`;
}

window.openShellRouletteOutside = function(attackId) {
  if (rouletteBusy || !playerSessionToken) return;
  const attack = activeDuo?.pendingShellAttacks?.find(item => item.id === attackId);
  if (!attack) return;
  RouletteWindow.update({phase: 'prepared', teamName: activeDuo.teamName, attackId,
    message: `Pepazo de ${attack.attackerName || 'Rival'}. Pulsa Girar cuando estés listo.`});
  if (!RouletteWindow.open()) {
    showPlayerToast('Permite las ventanas emergentes para abrir la ruleta fuera.', true);
    return;
  }
  document.getElementById('open-roulette-window').hidden = false;
};

window.spinShellHandler = async function(attackId, outside = false) {
  if (rouletteBusy) return;
  const teamName = activeDuo?.teamName || 'Tu equipo';
  if (!playerSessionToken || !activeDuo?.pendingShellAttacks?.some(attack => attack.id === attackId)) {
    if (outside) RouletteWindow.update({phase: 'unavailable', teamName, message: 'Este pepazo ya no está pendiente. Vuelve al panel de tu equipo.'});
    return;
  }
  rouletteBusy = true;
  const spinToken = playerSessionToken;
  document.querySelectorAll('[data-spin-id], [data-spin-outside-id]').forEach(button => { button.disabled = true; });
  RouletteWindow.update(outside ? {phase: 'waiting', teamName} :
    {phase: 'unavailable', teamName, message: 'La ruleta se está girando en el panel del equipo.'});
  const res = await DataStore.spinShell(attackId, spinToken);
  if (playerSessionToken !== spinToken) {
    rouletteBusy = false;
    RouletteWindow.update({phase: 'unavailable', teamName, message: 'La sesión del equipo ha terminado. Vuelve a entrar desde el panel.'});
    return;
  }
  if (!res.success) {
    rouletteBusy = false;
    renderDashboardData();
    if (outside) RouletteWindow.update({phase: 'error', teamName, attackId, canSpin: true, message: res.error || 'No se pudo girar la ruleta.'});
    showPlayerToast(res.error || 'No se pudo girar la ruleta.', true);
    return;
  }
  const instance = res.penaltyInstance || res.duo?.activeDebuffs?.find(item => item.id === res.attack?.penaltyInstanceId);
  const state = {
    phase: 'spinning', teamName, startedAt: Date.now(), holdMs: ROULETTE_RESULT_HOLD_MS,
    penalty: {name: String(res.penalty?.name || 'CASTIGO'), icon: String(res.penalty?.icon || '⚡'), desc: String(res.penalty?.desc || ''),
      assignment: penaltyAssignmentText(instance, res.duo)}
  };
  const finish = async () => {
    rouletteBusy = false;
    if (playerSessionToken !== spinToken) return;
    activeDuo = res.duo;
    sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
    allDuos = await DataStore.getDuos();
    renderDashboardData();
  };
  if (outside) {
    RouletteWindow.update(state);
    ShellRoulette.animate(state, () => {}, finish);
  } else {
    showRouletteInline(state, finish);
  }
};

RouletteWindow.onSpin(attackId => window.spinShellHandler(attackId, true));

function setupPlayerListeners() {
  const tabs = Array.from(document.querySelectorAll('[data-player-panel-tab]'));
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => selectPlayerPanel(button.dataset.playerPanelTab));
    button.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      selectPlayerPanel(tabs[next].dataset.playerPanelTab);
      tabs[next].focus();
    });
  });
  document.querySelectorAll('[data-player-penalty-view]').forEach(button => {
    button.addEventListener('click', () => {
      playerPenaltyView = button.dataset.playerPenaltyView;
      playerHistoryPage = 1;
      renderActiveDebuffs();
    });
  });
  document.getElementById('active-debuffs-list').addEventListener('click', event => {
    const button = event.target.closest('[data-player-history-step]');
    if (!button || button.disabled) return;
    playerHistoryPage += Number(button.dataset.playerHistoryStep);
    renderActiveDebuffs();
    document.querySelector(`[data-player-history-step="${button.dataset.playerHistoryStep}"]`)?.focus();
  });
  const loginForm = document.getElementById('player-login-form');
  const launchForm = document.getElementById('launch-shell-form');
  const btnLogout = document.getElementById('btn-logout');

  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const teamId = document.getElementById('login-team-select').value;
      const pwd = document.getElementById('login-password-input').value;
      const errorMsg = document.getElementById('login-error-msg');
      const errorText = document.getElementById('login-error-text');

      const res = await DataStore.loginPlayer(teamId, pwd);
      if (res.success && res.duo) {
        activeDuo = res.duo;
        playerSessionToken = res.sessionToken || '';
        sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
        sessionStorage.setItem('pepes_player_token', playerSessionToken);
        document.dispatchEvent(new Event('player-session-changed'));
        if (errorMsg) errorMsg.style.display = 'none';
        showDashboardView();
      } else {
        if (errorMsg) errorMsg.style.display = 'block';
        if (errorText) errorText.textContent = res.error || "Contraseña o equipo incorrecto.";
      }
    });
  }

  if (launchForm) {
    launchForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const targetSelect = document.getElementById('target-team-select');
      const targetId = targetSelect ? targetSelect.value : '';
      const btnSubmit = document.getElementById('btn-launch-shell');

      if (!targetId) {
        showPlayerToast("Por favor selecciona un equipo objetivo (rival).", true);
        return;
      }

      if ((activeDuo.blueShells || 0) <= 0) {
        showPlayerToast("No tienes Pepazos disponibles en tu inventario.", true);
        return;
      }

      const targetDuo = allDuos.find(d => d.id === targetId);
      const targetName = targetDuo ? targetDuo.teamName : "Equipo Rival";

      if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Lanzando...`;
      }

      try {
        const res = await DataStore.launchShell(targetId, playerSessionToken);
        if (res && res.success) {
          activeDuo = res.attacker;
          sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
          allDuos = await DataStore.getDuos();
          renderDashboardData();
          showPlayerToast(`Pepazo enviado a ${targetName}. Ellos girarán la ruleta.`);
          if (btnSubmit) { btnSubmit.disabled = false; btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Pepazo!`; }
        } else {
          showPlayerToast(res?.error || "Error al lanzar el Pepazo.", true);
          if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Pepazo!`;
          }
        }
      } catch (err) {
        showPlayerToast("Error de conexión con el servidor.", true);
        if (btnSubmit) {
          btnSubmit.disabled = false;
          btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Pepazo!`;
        }
      }
    });
  }

  if (btnLogout) {
    btnLogout.addEventListener('click', () => {
      activeDuo = null;
      sessionStorage.removeItem('pepes_player_session');
      const previousToken = playerSessionToken;
      sessionStorage.removeItem('pepes_player_token');
      playerSessionToken = '';
      DataStore.logoutPlayer(previousToken);
      document.dispatchEvent(new Event('player-session-changed'));
      showLoginView();
    });
  }
}

function showRouletteInline(state, onCloseCallback) {
  const container = document.getElementById('inline-roulette-container');
  const targetText = document.getElementById('inline-target-name');
  const rouletteIcon = document.getElementById('inline-roulette-icon');
  const rouletteName = document.getElementById('inline-roulette-name');
  const resultDesc = document.getElementById('inline-roulette-desc');
  const assignmentText = document.getElementById('inline-roulette-assignment');
  if (!container) {
    if (onCloseCallback) onCloseCallback();
    return;
  }
  if (targetText) targetText.textContent = 'Tu equipo está girando el Pepazo...';
  container.style.display = 'block';
  ShellRoulette.animate(state, current => {
    if (rouletteIcon) rouletteIcon.textContent = current.icon;
    if (rouletteName) {
      rouletteName.textContent = current.name;
      rouletteName.style.color = current.revealed ? 'var(--gold-hextech)' : '#fff';
    }
    if (assignmentText) {
      assignmentText.textContent = current.assignment || '';
      assignmentText.hidden = !current.revealed || !current.assignment;
    }
    if (resultDesc) {
      resultDesc.innerHTML = current.revealed ? `<i class="fa-solid fa-bullhorn"></i> <strong>${escapeHtml(state.penalty.name)}:</strong> ${escapeHtml(current.desc)}` : '';
      resultDesc.style.display = current.revealed ? 'block' : 'none';
    }
  }, () => {
    container.style.display = 'none';
    if (onCloseCallback) onCloseCallback();
  });
}

document.getElementById('open-roulette-window').addEventListener('click', () => {
  if (!RouletteWindow.open()) showPlayerToast('Permite las ventanas emergentes para abrir la ruleta para stream.', true);
});

function formatIsoDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('es-ES');
}

function showPlayerToast(msg, isError = false) {
  let toast = document.getElementById('player-toast-notification');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'player-toast-notification';
    toast.style.cssText = `
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      padding: 0.8rem 1.4rem;
      border-radius: 8px;
      font-weight: 700;
      font-size: 0.9rem;
      z-index: 99999;
      box-shadow: 0 4px 15px rgba(0,0,0,0.5);
      transition: all 0.3s ease;
      opacity: 0;
      transform: translateY(20px);
      pointer-events: none;
    `;
    document.body.appendChild(toast);
  }

  if (isError) {
    toast.style.background = 'rgba(255, 77, 77, 0.95)';
    toast.style.color = '#ffffff';
    toast.style.border = '1px solid #ff4d4d';
  } else {
    toast.style.background = 'rgba(245, 197, 66, 0.95)';
    toast.style.color = '#000000';
    toast.style.border = '1px solid var(--gold-hextech)';
  }

  toast.textContent = msg;
  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
  }, 3500);
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getTierColor(tier) {
  const t = String(tier || '').toLowerCase();
  if (t === 'unranked') return 'var(--text-muted)';
  if (t === 'iron') return 'var(--tier-iron)';
  if (t === 'bronze') return 'var(--tier-bronze)';
  if (t === 'silver') return 'var(--tier-silver)';
  if (t === 'gold') return 'var(--tier-gold)';
  if (t === 'platinum') return 'var(--tier-platinum)';
  if (t === 'emerald') return 'var(--tier-emerald)';
  if (t === 'diamond') return 'var(--tier-diamond)';
  return 'var(--cyan-primary)';
}

document.addEventListener('click', event => {
  const outsideButton = event.target.closest('[data-spin-outside-id]');
  if (outsideButton) { window.openShellRouletteOutside(outsideButton.dataset.spinOutsideId); return; }
  const button = event.target.closest('[data-spin-id]');
  if (button) window.spinShellHandler(button.dataset.spinId);
});

document.addEventListener('player-session-ended', () => {
  activeDuo = null;
  playerSessionToken = '';
  showLoginView();
});
