/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Player Panel Logic (player.js)
   ========================================================================== */

let activeDuo = null;
let allDuos = [];

document.addEventListener('DOMContentLoaded', () => {
  initPlayerApp();
});

async function initPlayerApp() {
  allDuos = await DataStore.getDuos();
  populateTeamsDropdown();

  // Check existing session
  const savedSession = sessionStorage.getItem('pepes_player_session');
  if (savedSession) {
    try {
      activeDuo = JSON.parse(savedSession);
      // Refresh duo data from server
      const match = allDuos.find(d => d.id === activeDuo.id);
      if (match) activeDuo = match;
      showDashboardView();
    } catch (e) {
      sessionStorage.removeItem('pepes_player_session');
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
        const match = allDuos.find(d => d.id === activeDuo.id);
        if (match) {
          activeDuo = match;
          renderPlayerDashboard();
        }
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

  // Streak calculations (1 shell per 2 consecutive wins)
  const streak = activeDuo.streak || 0;
  const progressInCycle = streak % 2;
  const progressPercent = Math.min(100, Math.round((progressInCycle / 2) * 100));

  if (streakTextEl) {
    const remaining = 2 - progressInCycle;
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
  renderActiveDebuffs();
}

function renderActiveDebuffs() {
  const container = document.getElementById('active-debuffs-list');
  if (!container || !activeDuo) return;

  const rawDebuffs = activeDuo.activeDebuffs || [];
  const activeDebuffs = rawDebuffs.filter(d => !d.resolved);

  if (activeDebuffs.length === 0) {
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
            <th style="padding: 0.6rem; text-align: right;">Acción</th>
          </tr>
        </thead>
        <tbody>
  `;

  activeDebuffs.forEach((d) => {
    const pen = d.penalty || { name: 'Castigo', icon: '⚡', desc: '' };
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
          <button 
            type="button"
            class="btn-refresh" 
            style="background: #28a745; border-color: #28a745; color: #fff; font-size: 0.75rem; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer;"
            onclick="window.resolveDebuffHandler('${escapeHtml(d.timestamp || '')}', '${escapeHtml(pen.id || '')}')"
          >
            <i class="fa-solid fa-check"></i> Resolver
          </button>
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

window.resolveDebuffHandler = async function(timestamp, penaltyId) {
  if (!activeDuo) return;

  try {
    const res = await DataStore.resolveDebuff(activeDuo.id, timestamp, penaltyId);
    if (res && res.success && res.duo) {
      activeDuo = res.duo;
      sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
      
      allDuos = await DataStore.getDuos();
      renderDashboardData();
      showPlayerToast("¡Castigo resuelto correctamente!");
    } else {
      showPlayerToast(res?.error || "No se pudo resolver el castigo", true);
    }
  } catch (err) {
    showPlayerToast("Error de conexión al resolver el castigo", true);
  }
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
        sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
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
        const res = await DataStore.launchShell(activeDuo.id, targetId);
        if (res && res.success) {
          showRouletteInline(targetName, res.penalty, async () => {
            allDuos = await DataStore.getDuos();
            const match = allDuos.find(d => d.id === (res.attacker ? res.attacker.id : activeDuo.id));
            activeDuo = match ? match : res.attacker;
            sessionStorage.setItem('pepes_player_session', JSON.stringify(activeDuo));
            renderDashboardData();
            if (btnSubmit) {
              btnSubmit.disabled = false;
              btnSubmit.innerHTML = `🐢⚡ ¡Lanzar Caparazón Azul!`;
            }
          });
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
      showLoginView();
    });
  }
}

function showRouletteInline(targetName, finalPenalty, onCloseCallback) {
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
    { name: "SIN FLASH", icon: "⚡", desc: "¡Prohibido usar el Hechizo de Invocador Flash en la siguiente partida!" },
    { name: "AUTOFILL / ROL SECUNDARIO", icon: "🎲", desc: "¡Debéis jugar la siguiente partida en rol autofill / secundario!" },
    { name: "SIN BOTAS", icon: "👢", desc: "¡Prohibido comprar o usar botas durante toda la siguiente partida!" }
  ];

  if (targetText) targetText.textContent = `Lanzando Caparazón Azul contra ${targetName}...`;
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
        resultDesc.innerHTML = `<i class="fa-solid fa-bullhorn"></i> <strong>Castigo asignado a ${escapeHtml(targetName)}:</strong> ${escapeHtml(finalPenalty.desc || '')}`;
        resultDesc.style.display = 'block';
      }

      setTimeout(() => {
        container.style.display = 'none';
        if (onCloseCallback) onCloseCallback();
      }, 3500);
    }
  }

  cycle();
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
