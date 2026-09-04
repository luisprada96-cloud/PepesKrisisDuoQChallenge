/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Player Panel Logic (player.js)
   ========================================================================== */

let activeDuo = null;
let allDuos = [];
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
      if (!state.success || !state.duo) throw new Error('Sesión caducada');
      activeDuo = state.duo;
      sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
      showDashboardView();
    } catch (e) {
      sessionStorage.removeItem('pepes_player_session');
      sessionStorage.removeItem('pepes_player_token');
      playerSessionToken = '';
      showLoginView();
    }
  } else {
    showLoginView();
  }

  setupPlayerListeners();

  // Auto-refresco silencioso desde db.json cada 15 segundos (sin llamadas a Riot API)
  setInterval(async () => {
    try {
      allDuos = await DataStore.getDuos();
      if (activeDuo) {
        const state = await DataStore.getPlayerState(playerSessionToken);
        if (state.success && state.duo) activeDuo = state.duo;
        renderDashboardData();
      }
    } catch (e) {
      console.warn("Error en auto-refresco del panel del jugador:", e);
    }
  }, 15000);
}

function populateTeamsDropdown() {
  const teamSelect = document.getElementById('login-team-select');
  if (!teamSelect) return;

  teamSelect.innerHTML = '<option value="">Selecciona tu equipo / pareja...</option>';
  allDuos.forEach(d => {
    const p2Str = d.player2 && d.player2.name ? ` & ${d.player2.name}` : '';
    teamSelect.innerHTML += `<option value="${d.id}">${escapeHtml(d.teamName)} (${d.player1.name}${p2Str})</option>`;
  });
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

  renderDashboardData();
}

function renderDashboardData() {
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
    streakTextEl.textContent = `${streak}W racha activa • ${remaining} victoria${remaining !== 1 ? 's' : ''} más para +1 Caparazón`;
  }
  if (streakBarEl) {
    streakBarEl.style.width = `${progressPercent}%`;
  }

  // Populate Target Select (all teams except current)
  if (targetSelect) {
    targetSelect.innerHTML = '<option value="">Selecciona equipo objetivo...</option>';
    allDuos.filter(d => d.id !== activeDuo.id).forEach(d => {
      targetSelect.innerHTML += `<option value="${d.id}">#${d.teamName} (${d.tier} ${d.division})</option>`;
    });
  }

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
      attack.status === 'RETURNED' ? 'Caparazón devuelto' : (result ? result.name : attack.status);
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
      <div><strong>🐢 Caparazón de #${escapeHtml(attack.attackerName || 'Rival')}</strong><span>Recibido ${escapeHtml(formatIsoDate(attack.launchedAt))}</span></div>
      <button type="button" class="btn-refresh btn-neon-gold" onclick="window.spinShellHandler('${escapeHtml(attack.id)}')">🎰 Girar ruleta</button>
    </div>
  `).join('');
}

function renderActiveDebuffs() {
  const container = document.getElementById('active-debuffs-list');
  if (!container || !activeDuo) return;

  const rawDebuffs = activeDuo.activeDebuffs || [];
  const visibleDebuffs = rawDebuffs.slice(0, 20);

  if (visibleDebuffs.length === 0) {
    container.innerHTML = `
      <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 8px; text-align: center; color: var(--text-muted); font-size: 0.9rem;">
        <i class="fa-solid fa-shield-halved" style="color: #28a745; font-size: 1.2rem; margin-bottom: 0.3rem; display: block;"></i>
        No tienes ningún castigo activo actualmente. ¡Tu equipo está limpio! 🎉
      </div>
    `;
    return;
  }

  let html = `
    <div style="overflow-x: auto;">
      <table class="leaderboard-table" style="width: 100%; border-collapse: collapse;">
        <thead>
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); text-align: left; font-size: 0.8rem; color: var(--text-muted);">
            <th style="padding: 0.6rem;">Castigo</th>
            <th style="padding: 0.6rem;">Atacante</th>
            <th style="padding: 0.6rem;">Fecha</th>
            <th style="padding: 0.6rem; text-align: right;">Estado</th>
          </tr>
        </thead>
        <tbody>
  `;

  visibleDebuffs.forEach((d) => {
    const pen = d.penalty || { name: 'Castigo', icon: '⚡', desc: '' };
    const completed = d.status === 'COMPLETED' || d.resolved;
    html += `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.85rem;">
        <td style="padding: 0.75rem 0.6rem;">
          <div style="display: flex; align-items: center; gap: 0.5rem; font-weight: 700; color: #ff4d4d;">
            <span style="font-size: 1.2rem;">${pen.icon || '⚡'}</span>
            <div>
              <div>${escapeHtml(pen.name)}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 400;">${escapeHtml(pen.desc)}</div>
            </div>
          </div>
        </td>
        <td style="padding: 0.75rem 0.6rem; font-weight: 700; color: var(--cyan-primary);">
          #${escapeHtml(d.attacker || 'Rival')}
        </td>
        <td style="padding: 0.75rem 0.6rem; color: var(--text-muted); font-size: 0.8rem;">
          ${escapeHtml(d.timestamp || '')}
        </td>
        <td style="padding: 0.75rem 0.6rem; text-align: right;">
          <span class="${completed ? 'penalty-status-completed' : 'penalty-status-active'}"><i class="fa-solid ${completed ? 'fa-circle-check' : 'fa-clock'}"></i> ${completed ? 'Cumplido' : 'Pendiente'}</span>
        </td>
      </tr>
    `;
  });

  html += `
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;
}

window.spinShellHandler = async function(attackId) {
  const button = document.querySelector(`[onclick*="${attackId}"]`);
  if (button) button.disabled = true;
  const res = await DataStore.spinShell(attackId, playerSessionToken);
  if (!res.success) {
    if (button) button.disabled = false;
    showPlayerToast(res.error || 'No se pudo girar la ruleta.', true);
    return;
  }
  showRouletteInline(res.penalty, async () => {
    activeDuo = res.duo;
    sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
    allDuos = await DataStore.getDuos();
    renderDashboardData();
  });
};

function setupPlayerListeners() {
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
        showPlayerToast("No tienes Caparazones Azules disponibles en tu inventario.", true);
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
          showPlayerToast(`Caparazón enviado a ${targetName}. Ellos girarán la ruleta.`);
          if (btnSubmit) { btnSubmit.disabled = false; btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Caparazón Azul!`; }
        } else {
          showPlayerToast(res?.error || "Error al lanzar el Caparazón Azul.", true);
          if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Caparazón Azul!`;
          }
        }
      } catch (err) {
        showPlayerToast("Error de conexión con el servidor.", true);
        if (btnSubmit) {
          btnSubmit.disabled = false;
          btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Caparazón Azul!`;
        }
      }
    });
  }

  if (btnLogout) {
    btnLogout.addEventListener('click', () => {
      activeDuo = null;
      sessionStorage.removeItem('pepes_player_session');
      sessionStorage.removeItem('pepes_player_token');
      playerSessionToken = '';
      showLoginView();
    });
  }
}

function showRouletteInline(finalPenalty, onCloseCallback) {
  const container = document.getElementById('inline-roulette-container');
  const targetText = document.getElementById('inline-target-name');
  const rouletteIcon = document.getElementById('inline-roulette-icon');
  const rouletteName = document.getElementById('inline-roulette-name');
  const resultDesc = document.getElementById('inline-roulette-desc');

  if (!container) {
    if (onCloseCallback) onCloseCallback();
    return;
  }

  const options = [
    { name: "POLIVALENTE", icon: "🎲" }, { name: "SIN CAMPEÓN FAVORITO", icon: "🚫" },
    { name: "CAMPEÓN ALEATORIO", icon: "🎯" }, { name: "SIN FLASH", icon: "⚡" },
    { name: "BOTAS BÁSICAS HASTA 15", icon: "👢" }, { name: "DEVUELVE EL CAPARAZÓN", icon: "↩️" }
  ];

  if (targetText) targetText.textContent = `Tu equipo está girando el Caparazón Azul...`;
  container.style.display = 'block';
  if (resultDesc) resultDesc.style.display = 'none';

  let speed = 70;
  let counter = 0;
  const totalRounds = 22;

  function cycle() {
    const currentOpt = options[counter % options.length];
    if (rouletteIcon) rouletteIcon.textContent = currentOpt.icon;
    if (rouletteName) {
      rouletteName.textContent = currentOpt.name;
      rouletteName.style.color = "#fff";
    }

    counter++;
    if (counter < totalRounds) {
      speed += 14;
      setTimeout(cycle, speed);
    } else {
      if (rouletteIcon) rouletteIcon.textContent = finalPenalty.icon || "⚡";
      if (rouletteName) {
        rouletteName.textContent = (finalPenalty.name || "CASTIGO").toUpperCase();
        rouletteName.style.color = "var(--gold-hextech)";
      }

      if (resultDesc) {
        resultDesc.innerHTML = `<i class="fa-solid fa-bullhorn"></i> <strong>${escapeHtml(finalPenalty.name || 'Resultado')}:</strong> ${escapeHtml(finalPenalty.desc || '')}`;
        resultDesc.style.display = 'block';
      }

      setTimeout(() => {
        container.style.display = 'none';
        if (onCloseCallback) onCloseCallback();
      }, 8500);
    }
  }

  cycle();
}

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

  toast.innerHTML = `<i class="fa-solid ${isError ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${msg}`;
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
