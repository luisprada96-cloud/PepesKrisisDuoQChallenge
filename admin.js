/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Admin Panel Logic (admin.js)
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  initAdmin();
});

let adminDuos = [];
let adminConfig = {};
let adminSessionPin = '';
let penaltyCatalog = [];
let adminPenaltyPage = 1;
const ADMIN_PENALTIES_PAGE_SIZE = 10;
const ADMIN_ROLE_LABELS = {
  TOP: 'Top',
  JUNGLE: 'Jungla',
  MIDDLE: 'Mid',
  BOTTOM: 'ADC',
  UTILITY: 'Support'
};

function renderRoleOptions(selectedRole) {
  return `<option value="">Selecciona un rol</option>` + Object.entries(ADMIN_ROLE_LABELS)
    .map(([value, label]) => `<option value="${value}"${selectedRole === value ? ' selected' : ''}>${label}</option>`)
    .join('');
}

async function initAdmin() {
  setupAdminListeners();
  checkAdminAuth();
}

function checkAdminAuth() {
  const pinOverlay = document.getElementById('admin-pin-overlay');
  const pinForm = document.getElementById('admin-pin-form');
  const pinInput = document.getElementById('admin-pin-input');
  const errorMsg = document.getElementById('pin-error-msg');

  if (!pinOverlay || !pinForm) {
    loadAdminData();
    return;
  }

  // Focus input automatically
  setTimeout(() => pinInput && pinInput.focus(), 100);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && pinOverlay.classList.contains('active')) {
      event.preventDefault();
      location.assign('index.html');
    }
  });

  pinForm.onsubmit = async (e) => {
    e.preventDefault();
    const enteredPin = pinInput.value.trim();
    const submitButton = pinForm.querySelector('button[type="submit"]');
    if (submitButton) submitButton.disabled = true;

    const result = await DataStore.getAdminConfig(enteredPin);

    if (result.success && result.config) {
      adminSessionPin = enteredPin;
      adminConfig = result.config;
      penaltyCatalog = result.penaltyCatalog || [];
      if (result.duos) adminDuos = result.duos;
      await loadAdminData();
      pinOverlay.classList.remove('active');
      pinOverlay.style.display = 'none';
    } else {
      if (errorMsg) errorMsg.style.display = 'block';
      pinInput.value = '';
      pinInput.focus();
    }

    if (submitButton) submitButton.disabled = false;
  };
}

async function loadAdminData() {
  await refreshAdminData();

  renderAdminDuosList();
  renderPenaltyWeights();
  renderAdminPenalties();
  fillConfigForm();
  refreshAdminWeeklyDiagnostics();
}

async function refreshAdminData() {
  if (adminSessionPin) {
    const result = await DataStore.getAdminConfig(adminSessionPin);
    if (result.success) {
      adminDuos = result.duos || [];
      adminConfig = result.config || adminConfig;
      penaltyCatalog = result.penaltyCatalog || penaltyCatalog;
      renderAdminDiagnostics();
      return;
    }
  }
  adminDuos = await DataStore.getDuos();
  renderAdminDiagnostics();
}

function renderAdminDiagnostics() {
  if (!adminSessionPin) return;
  const section = document.getElementById('admin-diagnostics');
  if (!section) return;
  section.hidden = false;
  renderConnectionStatus();
  const count = value => value == null ? '—' : Number(value) || 0;
  const rows = adminDuos.map(duo => {
    const discovery = duo.riotMatchDiscovery;
    const unknownCredits = (duo.history || []).reduce((total, match) => total + (match.shellRewardIds || [])
      .filter(rule => typeof match.shellRewardCredits?.[rule] !== 'boolean').length, 0);
    return `<tr><td>${escapeHtml(duo.teamName)}</td>
      <td>${discovery ? count(discovery.pendingMatchIds?.length) : '—'}</td>
      <td>${count(duo.statsBackfill?.remaining)}</td><td>${count(duo.matchDetailsBackfill?.remaining)}</td>
      <td>${unknownCredits}</td></tr>`;
  }).join('');
  document.getElementById('admin-data-diagnostics').innerHTML = rows ? `<div class="admin-diagnostics-table-wrap"><table class="admin-diagnostics-table">
    <thead><tr><th>Equipo</th><th>Partidas por importar</th><th>Estadísticas pendientes</th><th>Detalles pendientes</th><th>Logros sin registro de ingreso</th></tr></thead>
    <tbody>${rows}</tbody></table></div>` : '<p class="admin-diagnostics-note">Todavía no hay equipos.</p>';
}

async function refreshAdminWeeklyDiagnostics() {
  const element = document.getElementById('admin-weekly-diagnostics');
  if (!element || !adminSessionPin) return;
  try {
    let data = await DataStore.getWeeklySummary();
    const closedWeek = data.weeks?.[1];
    if (closedWeek) data = await DataStore.getWeeklySummary(closedWeek);
    if (!data.summary) return;
    element.textContent = closedWeek
      ? `Último resumen archivado: ${data.summary.week}. Actualizado ${new Date(data.summary.updatedAt * 1000).toLocaleString('es-ES', {timeZone:'Europe/Madrid'})}.`
      : 'Resumen semanal: todavía no hay semanas archivadas. El primer cierre se realizará el lunes a las 00:00 (Madrid).';
  } catch (_) {
    element.textContent = 'No se pudo consultar el estado del archivo semanal.';
  }
}

function renderPenaltyWeights() {
  const container = document.getElementById('penalty-weights-grid');
  if (!container) return;
  const weights = adminConfig.penaltyWeights || {};
  container.innerHTML = penaltyCatalog.map(item => `
    <label class="penalty-weight-card">
      <span class="penalty-weight-icon">${item.icon}</span>
      <span class="penalty-weight-copy"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.desc)}</small></span>
      <span class="penalty-weight-input"><input type="number" min="0" max="100" step="1" value="${Number(weights[item.id] ?? item.defaultWeight ?? 0)}" data-penalty-weight="${item.id}" class="form-control"><b>%</b></span>
    </label>
  `).join('');
  container.querySelectorAll('[data-penalty-weight]').forEach(input => input.addEventListener('input', updatePenaltyWeightTotal));
  updatePenaltyWeightTotal();
}

function updatePenaltyWeightTotal() {
  const inputs = [...document.querySelectorAll('[data-penalty-weight]')];
  const total = inputs.reduce((sum, input) => sum + Math.max(0, Number(input.value) || 0), 0);
  const totalEl = document.getElementById('penalty-weight-total');
  const saveButton = document.getElementById('btn-save-penalty-weights');
  if (totalEl) {
    totalEl.textContent = `${total}%`;
    totalEl.classList.toggle('is-valid', total === 100);
    totalEl.classList.toggle('is-invalid', total !== 100);
  }
  if (saveButton) saveButton.disabled = total !== 100;
}

async function savePenaltyWeights() {
  const weights = {};
  document.querySelectorAll('[data-penalty-weight]').forEach(input => { weights[input.dataset.penaltyWeight] = Number(input.value) || 0; });
  const result = await DataStore.saveConfig({...adminConfig, penaltyWeights: weights}, adminSessionPin);
  if (!result.success) return alert(result.error || 'No se pudieron guardar los porcentajes.');
  adminConfig = result.config;
  renderPenaltyWeights();
  alert('Porcentajes de la ruleta guardados correctamente.');
}

function renderAdminPenalties() {
  const container = document.getElementById('admin-penalties-list');
  if (!container) return;
  const rows = adminDuos
    .flatMap(duo => (duo.activeDebuffs || []).map(debuff => ({duo, debuff})))
    .sort((a, b) => getPenaltyTimestamp(b.debuff) - getPenaltyTimestamp(a.debuff));
  if (!rows.length) {
    container.innerHTML = '<p class="admin-empty-state">Todavía no hay castigos asignados.</p>';
    return;
  }

  const totalPages = Math.max(1, Math.ceil(rows.length / ADMIN_PENALTIES_PAGE_SIZE));
  adminPenaltyPage = Math.min(Math.max(1, adminPenaltyPage), totalPages);
  const pageRows = rows.slice(
    (adminPenaltyPage - 1) * ADMIN_PENALTIES_PAGE_SIZE,
    adminPenaltyPage * ADMIN_PENALTIES_PAGE_SIZE
  );

  const tableRows = pageRows.map(({duo, debuff}) => {
    const pen = debuff.penalty || {};
    const completed = debuff.status === 'COMPLETED' || debuff.resolved;
    const retired = debuff.status === 'CANCELLED';
    const scope = debuff.scope || pen.scope;
    return `<tr>
      <td><time>${escapeHtml(formatPenaltyTimestamp(debuff.assignedAt || debuff.timestamp))}</time></td>
      <td><strong>${escapeHtml(duo.teamName || 'Equipo')}</strong></td>
      <td><span class="admin-penalty-name">${pen.icon || '⚡'} ${escapeHtml(pen.name || 'Castigo')}</span></td>
      <td>${escapeHtml(scope === 'BOTH' ? 'Ambos' : scope === 'SPECIAL' ? 'Especial' : 'Uno')}<div class="penalty-assignment">${escapeHtml(penaltyAssignmentText(debuff, duo))}</div></td>
      <td><span class="admin-penalty-status ${retired ? 'is-retired' : completed ? 'is-completed' : 'is-active'}">${retired ? 'Retirado' : completed ? 'Cumplido' : 'Activo'}</span></td>
      <td>${completed ? `<time>${escapeHtml(formatPenaltyTimestamp(debuff.resolvedAt))}</time>` : '<span class="admin-penalty-empty">—</span>'}</td>
      <td>${debuff.retiredPenalty || retired ? '<span class="legacy-penalty-label">Castigo retirado</span>' : debuff.id ? `<button type="button" class="btn-refresh admin-penalty-action" data-penalty-id="${escapeHtml(debuff.id)}" data-penalty-action="${completed ? 'REOPEN' : 'COMPLETE'}">${completed ? 'Reabrir' : 'Marcar cumplido'}</button>` : '<span class="legacy-penalty-label">Antiguo</span>'}</td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="admin-penalties-table-wrap">
      <table class="admin-penalties-table">
        <thead><tr><th>Recibido</th><th>Equipo</th><th>Castigo</th><th>Alcance</th><th>Estado</th><th>Resuelto</th><th>Acción</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <div class="admin-penalties-pagination">
      <span>Página ${adminPenaltyPage} de ${totalPages} · ${rows.length} castigo${rows.length === 1 ? '' : 's'}</span>
      <div>
        <button type="button" class="btn-refresh" onclick="window.changeAdminPenaltyPage(-1)" ${adminPenaltyPage === 1 ? 'disabled' : ''}>Anterior</button>
        <button type="button" class="btn-refresh" onclick="window.changeAdminPenaltyPage(1)" ${adminPenaltyPage === totalPages ? 'disabled' : ''}>Siguiente</button>
      </div>
    </div>`;
}

function getPenaltyTimestamp(debuff) {
  const epoch = Number(debuff.assignedAtEpochMs);
  if (Number.isFinite(epoch) && epoch > 0) return epoch;
  const raw = debuff.assignedAt || debuff.timestamp || '';
  const legacy = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
  if (legacy) return new Date(+legacy[3], +legacy[2] - 1, +legacy[1], +(legacy[4] || 0), +(legacy[5] || 0)).getTime();
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatPenaltyTimestamp(value) {
  if (!value) return 'Sin fecha';
  if (/^\d{2}\/\d{2}\/\d{4}/.test(value)) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('es-ES', {dateStyle: 'short', timeStyle: 'short'});
}

window.changeAdminPenaltyPage = function(delta) {
  adminPenaltyPage += delta;
  renderAdminPenalties();
};

window.adminPenaltyAction = async function(instanceId, action) {
  const defaultNote = action === 'COMPLETE' ? 'Comprobación manual del administrador' : 'Corrección: el castigo debe continuar activo';
  const note = prompt('Motivo de la corrección administrativa:', defaultNote);
  if (note === null) return;
  const result = await DataStore.adminResolvePenalty(instanceId, action, note, adminSessionPin);
  if (!result.success) return alert(result.error || 'No se pudo corregir el castigo.');
  adminDuos = result.duos || await DataStore.getDuos();
  renderAdminPenalties();
};

function fillConfigForm() {
  const titleInput = document.getElementById('cfg-title');
  const prizeInput = document.getElementById('cfg-prize');
  const startInput = document.getElementById('cfg-start');
  const endInput = document.getElementById('cfg-end');
  const pinInput = document.getElementById('cfg-pin');
  const keyInput = document.getElementById('cfg-riot-key');
  const twitchClientIdInput = document.getElementById('cfg-twitch-client-id');
  const twitchClientSecretInput = document.getElementById('cfg-twitch-client-secret');

  if (titleInput) titleInput.value = adminConfig.challengeTitle || '';
  if (prizeInput) prizeInput.value = adminConfig.prizePool || '';
  if (startInput) startInput.value = tournamentDateInput(adminConfig.startDate);
  if (endInput) endInput.value = tournamentDateInput(adminConfig.endDate);
  if (pinInput) {
    pinInput.value = '';
    pinInput.placeholder = adminConfig.adminPinConfigured ? 'PIN guardado — déjalo vacío para conservarlo' : 'Nuevo PIN';
  }
  if (keyInput) {
    keyInput.value = '';
    keyInput.placeholder = adminConfig.riotApiKeyConfigured
      ? 'Clave Riot guardada — déjala vacía para conservarla'
      : 'RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx';
  }
  if (twitchClientIdInput) twitchClientIdInput.value = adminConfig.twitchClientId || '';
  if (twitchClientSecretInput) {
    twitchClientSecretInput.value = '';
    twitchClientSecretInput.placeholder = adminConfig.twitchClientSecretConfigured
      ? 'Client Secret guardado — déjalo vacío para conservarlo'
      : 'Introduce el Client Secret';
  }
}

function renderParticipantSettings(duo, playerKey, index) {
  const player = duo[playerKey] || {};
  const prefix = `p${index}`;
  return `<fieldset class="admin-participant-settings">
    <legend>Integrante ${index} · ${escapeHtml(player.name || '')}#${escapeHtml(player.tag || 'EUW')}</legend>
    <div class="form-group">
      <label for="${prefix}-display-name-${escapeHtml(duo.id)}">Nombre del integrante</label>
      <input type="text" class="form-control" id="${prefix}-display-name-${escapeHtml(duo.id)}" value="${escapeHtml(player.displayName || player.name || '')}" maxlength="60" required>
    </div>
    <div class="form-group">
      <label for="${prefix}-twitch-url-${escapeHtml(duo.id)}">Canal de Twitch (opcional)</label>
      <input type="url" class="form-control" id="${prefix}-twitch-url-${escapeHtml(duo.id)}" value="${escapeHtml(participantTwitch(duo, playerKey).url)}" placeholder="https://www.twitch.tv/nombre_del_canal">
    </div>
  </fieldset>`;
}

function renderAdminDuosList() {
  const container = document.getElementById('admin-duos-list');
  if (!container) return;

  container.innerHTML = '';

  if (adminDuos.length === 0) {
    container.innerHTML = `<p style="color: var(--text-muted);">No hay dúos registrados. Añade la primera pareja usando el formulario.</p>`;
    return;
  }

  adminDuos.forEach((duo, idx) => {
    const card = document.createElement('div');
    card.className = 'stat-card';
    card.style.display = 'flex';
    card.style.flexDirection = 'column';
    card.style.justifyContent = 'space-between';
    card.style.alignItems = 'stretch';
    card.style.gap = '1rem';
    card.style.marginBottom = '0.75rem';

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;">
        <div>
          <div style="font-family: var(--font-heading); font-weight: 700; color: #fff; font-size: 1.05rem;">
            #${idx + 1} ${escapeHtml(duo.teamName)}
          </div>
          <div style="font-size: 0.85rem; color: var(--text-muted);">
            Jugador 1: <strong>${escapeHtml(duo.player1.name)}#${escapeHtml(duo.player1.tag)}</strong> |
            Jugador 2: <strong>${escapeHtml(duo.player2.name)}#${escapeHtml(duo.player2.tag)}</strong>
          </div>
          ${!duo.player1.mainRole || !duo.player2.mainRole ? `
            <div style="font-size: 0.8rem; color: var(--gold-hextech); margin-top: 0.35rem;">
              <i class="fa-solid fa-triangle-exclamation"></i> Asigna los dos roles principales para activar la comprobación de Polivalente.
            </div>
          ` : ''}
          <div style="font-size: 0.8rem; color: var(--cyan-primary); margin-top: 0.2rem;">
            Rango: ${escapeHtml(duo.tier)} ${escapeHtml(duo.division)} (${escapeHtml(duo.lp)} LP) | Net LP: +${escapeHtml(duo.netLp)} LP | ${escapeHtml(duo.wins)}W / ${escapeHtml(duo.losses)}L
          </div>
        </div>
        <div>
          <button class="btn-danger" data-team-action="delete" data-team-id="${escapeHtml(duo.id)}">
            <i class="fa-solid fa-trash"></i> Eliminar
          </button>
        </div>
      </div>
      <div style="display: flex; align-items: end; gap: 0.65rem; flex-wrap: wrap;">
        <div class="form-group" style="flex: 1 1 220px; margin: 0;">
          <label for="p1-role-${escapeHtml(duo.id)}">Rol principal · ${escapeHtml(duo.player1.name)}</label>
          <select id="p1-role-${escapeHtml(duo.id)}" class="form-control" required>
            ${renderRoleOptions(duo.player1.mainRole)}
          </select>
        </div>
        <div class="form-group" style="flex: 1 1 220px; margin: 0;">
          <label for="p2-role-${escapeHtml(duo.id)}">Rol principal · ${escapeHtml(duo.player2.name)}</label>
          <select id="p2-role-${escapeHtml(duo.id)}" class="form-control" required>
            ${renderRoleOptions(duo.player2.mainRole)}
          </select>
        </div>
        <button class="btn-refresh" data-team-action="roles" data-team-id="${escapeHtml(duo.id)}" style="height: fit-content;">
          <i class="fa-solid fa-user-tag"></i> Guardar roles
        </button>
      </div>
      <div class="admin-participant-grid">
        ${renderParticipantSettings(duo, 'player1', 1)}
        ${renderParticipantSettings(duo, 'player2', 2)}
      </div>
      <button type="button" class="btn-refresh" data-team-action="profiles" data-team-id="${escapeHtml(duo.id)}" style="align-self: flex-start;">
        <i class="fa-solid fa-save"></i> Guardar nombres y Twitch
      </button>
      <div style="display: flex; align-items: end; gap: 0.65rem; flex-wrap: wrap; margin-top: 0.5rem; padding-top: 0.75rem; border-top: 1px solid rgba(255, 255, 255, 0.08);">
        <div class="form-group" style="flex: 1 1 320px; margin: 0;">
          <label for="discord-webhook-${escapeHtml(duo.id)}"><i class="fa-brands fa-discord" style="color: #5865F2;"></i> Webhook Discord del Dúo (Alertas Caparazones)</label>
          <input type="url" id="discord-webhook-${escapeHtml(duo.id)}" class="form-control" value="${escapeHtml(duo.discordWebhook || '')}" placeholder="https://discord.com/api/webhooks/..." style="font-family: monospace; font-size: 0.85rem;">
        </div>
        <button type="button" class="btn-refresh" data-team-action="webhook" data-team-id="${escapeHtml(duo.id)}" style="height: fit-content;">
          <i class="fa-solid fa-save"></i> Guardar Webhook
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function setupAdminListeners() {
  if (document.body.dataset.adminListenersReady === 'true') return;
  document.body.dataset.adminListenersReady = 'true';

  const addForm = document.getElementById('add-duo-form');
  const cfgForm = document.getElementById('config-form');
  const btnReset = document.getElementById('btn-reset-data');
  const btnExport = document.getElementById('btn-export-data');
  const btnSyncTwitch = document.getElementById('btn-sync-twitch-admin');
  const btnTestDiscord = document.getElementById('btn-test-discord-admin');
  if (btnTestDiscord) {
    btnTestDiscord.addEventListener('click', async () => {
      btnTestDiscord.disabled = true;
      try {
        const result = await DataStore.testDiscord(adminSessionPin);
        if (result.success) showToast('Mensaje de prueba enviado a Discord.');
        else alert(result.error || 'No se pudo enviar la prueba de Discord.');
      } finally { btnTestDiscord.disabled = false; }
    });
  }
  const btnSavePenaltyWeights = document.getElementById('btn-save-penalty-weights');

  if (addForm) {
    addForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await addNewDuo();
    });
  }

  if (cfgForm) {
    cfgForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await saveConfigForm();
    });
  }

  if (btnReset) {
    btnReset.addEventListener('click', async () => {
      if (confirm("¿Estás seguro de restablecer los datos originales de la competición?")) {
        localStorage.clear();
        location.reload();
      }
    });
  }

  if (btnExport) {
    btnExport.addEventListener('click', () => {
      const jsonStr = JSON.stringify({ duos: adminDuos, config: adminConfig }, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `pepes_duoq_backup_${new Date().toISOString().slice(0,10)}.json`;
      a.click();
    });
  }

  if (btnSyncTwitch) {
    btnSyncTwitch.addEventListener('click', async () => {
      const icon = btnSyncTwitch.querySelector('i');
      if (icon) icon.classList.add('spinning');
      btnSyncTwitch.disabled = true;

      const result = await DataStore.triggerTwitchSync(adminSessionPin);
      if (result.success) {
        showToast(result.alreadyRunning ? 'Twitch ya se está sincronizando.' : 'Sincronización de Twitch iniciada. El estado aparece sobre el panel.');
        await DataStore.refreshSyncStatus();
      } else {
        alert(result.error || 'No se pudo iniciar la sincronización de Twitch.');
      }

      if (icon) icon.classList.remove('spinning');
      btnSyncTwitch.disabled = false;
    });
  }

  if (btnSavePenaltyWeights) btnSavePenaltyWeights.addEventListener('click', savePenaltyWeights);

  const btnCalcShells = document.getElementById('btn-calc-shells');
  if (btnCalcShells) {
    btnCalcShells.addEventListener('click', async () => {
      const icon = btnCalcShells.querySelector('i');
      if (icon) icon.classList.add('spinning');
      btnCalcShells.disabled = true;

      const res = await DataStore.calculateShells(adminSessionPin);
      if (!res.success) {
        if (icon) icon.classList.remove('spinning');
        btnCalcShells.disabled = false;
        alert(res.error || 'No se pudieron calcular los caparazones.');
        return;
      }
      if (res.duos) adminDuos = res.duos;
      renderAdminDuosList();

      if (icon) icon.classList.remove('spinning');
      btnCalcShells.disabled = false;

      // Animación de éxito en el botón (destello verde + pulso)
      btnCalcShells.style.transition = 'all 0.3s ease';
      btnCalcShells.style.background = 'rgba(0, 255, 136, 0.3)';
      btnCalcShells.style.borderColor = '#00ff88';
      btnCalcShells.style.boxShadow = '0 0 25px rgba(0, 255, 136, 0.8)';
      btnCalcShells.style.transform = 'scale(1.05)';

      const originalIcon = icon ? icon.className : 'fa-solid fa-calculator';
      if (icon) icon.className = 'fa-solid fa-check-double';

      setTimeout(() => {
        btnCalcShells.style.background = 'rgba(0, 240, 255, 0.15)';
        btnCalcShells.style.borderColor = 'var(--cyan-primary)';
        btnCalcShells.style.boxShadow = 'none';
        btnCalcShells.style.transform = 'scale(1)';
        if (icon) icon.className = originalIcon;
      }, 2000);

      const added = res.newShells || 0;
      const msg = added > 0 
        ? `¡Cálculo completado! 🐢⚡ Se han otorgado +${added} nuevo(s) Caparazón(es) Azul(es).` 
        : `¡Cálculo completado! Todos los caparazones ya estaban al día (0 nuevos otorgados).`;

      if (window.showToast) {
        showToast(msg, added > 0 ? 'success' : 'info');
      } else {
        alert(msg);
      }
    });
  }

  const btnSyncMatches = document.getElementById('btn-sync-matches-admin');
  if (btnSyncMatches) {
    btnSyncMatches.addEventListener('click', async () => {
      const icon = btnSyncMatches.querySelector('i');
      if (icon) icon.classList.add('spinning');
      btnSyncMatches.disabled = true;

      const result = await DataStore.triggerRiotSync(adminSessionPin);
      if (icon) icon.classList.remove('spinning');
      btnSyncMatches.disabled = false;
      if (result.success) {
        showToast(result.alreadyRunning ? 'Riot ya se está sincronizando.' : 'Sincronización de Riot iniciada. El estado aparece sobre el panel.');
        await DataStore.refreshSyncStatus();
      } else {
        alert(result.error || 'No se pudo iniciar la sincronización.');
      }
    });
  }

  // Setup Delete HTML Modal listeners
  const btnCancelDel = document.getElementById('btn-cancel-delete');
  const btnConfirmDel = document.getElementById('btn-confirm-delete');
  const delOverlay = document.getElementById('delete-confirm-overlay');

  if (btnCancelDel) {
    btnCancelDel.onclick = () => {
      pendingDeleteId = null;
      if (delOverlay) delOverlay.classList.remove('active');
    };
  }

  if (btnConfirmDel) {
    btnConfirmDel.onclick = async () => {
      if (pendingDeleteId) {
        await DataStore.deleteDuo(pendingDeleteId, adminSessionPin);
        await refreshAdminData();
        renderAdminDuosList();
        pendingDeleteId = null;
      }
      if (delOverlay) delOverlay.classList.remove('active');
    };
  }
}

async function addNewDuo() {
  const teamName = document.getElementById('new-team-name').value.trim();
  const p1NameTag = document.getElementById('new-p1').value.trim();
  const p2NameTag = document.getElementById('new-p2').value.trim();
  const tier = document.getElementById('new-tier').value;
  const p1Role = document.getElementById('new-p1-role').value;
  const p2Role = document.getElementById('new-p2-role').value;
  const pwdInput = document.getElementById('new-password');
  const password = (pwdInput && pwdInput.value.trim()) ? pwdInput.value.trim() : "1234";
  const profiles = {};
  for (const i of [1, 2]) {
    const nameInput = document.getElementById(`new-p${i}-display-name`);
    const twitchInput = document.getElementById(`new-p${i}-twitch-url`);
    const displayName = nameInput.value.trim();
    const rawUrl = twitchInput.value.trim();
    const twitchUrl = normalizeTwitchUrl(rawUrl);
    if (!displayName || displayName.length > 60) {
      alert('Introduce el nombre de cada integrante (máximo 60 caracteres).');
      nameInput.focus();
      return;
    }
    if (rawUrl && !twitchUrl) {
      alert('Introduce un enlace válido de canal de Twitch.');
      twitchInput.focus();
      return;
    }
    profiles[`player${i}`] = {displayName, twitchUrl};
  }
  if (!teamName || !p1NameTag || !p2NameTag || !p1Role || !p2Role) {
    alert('Por favor rellena todos los campos del nuevo dúo.');
    return;
  }

  const [p1Name, p1Tag = 'EUW'] = p1NameTag.split('#');
  const [p2Name, p2Tag = 'EUW'] = p2NameTag.split('#');

  const newDuo = {
    id: `duo-${Date.now()}`,
    teamName: teamName,
    password: password,
    discordWebhook: document.getElementById('new-discord-webhook')?.value?.trim() || '',
    blueShells: 0,
    player1: {
      ...profiles.player1,
      name: p1Name,
      tag: p1Tag,
      mainRole: p1Role,
      avatar: `https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/29.png`,
      champ: "LeeSin"
    },
    player2: {
      ...profiles.player2,
      name: p2Name,
      tag: p2Tag,
      mainRole: p2Role,
      avatar: `https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/1.png`,
      champ: "Ahri"
    },
    tier: tier,
    division: tier === "Unranked" ? "" : "IV",
    lp: 0,
    netLp: 0,
    initialTotalLp: 0,
    wins: 0,
    losses: 0,
    streak: 0,
    isLive: false,
    history: []
  };

  const result = await DataStore.saveDuo(newDuo, adminSessionPin);
  if (!result || result.success === false) {
    alert((result && result.error) || 'No se pudo añadir el dúo.');
    return;
  }
  await refreshAdminData();
  renderAdminDuosList();

  document.getElementById('add-duo-form').reset();
  alert(`¡Dúo "${teamName}" añadido correctamente!`);
}

async function handleSaveRoles(id) {
  const duo = adminDuos.find(d => d.id === id);
  const p1Input = document.getElementById(`p1-role-${id}`);
  const p2Input = document.getElementById(`p2-role-${id}`);
  if (!duo || !p1Input || !p2Input) return;

  if (!p1Input.value || !p2Input.value) {
    alert('Debes seleccionar el rol principal de ambos integrantes.');
    (!p1Input.value ? p1Input : p2Input).focus();
    return;
  }

  const result = await DataStore.saveDuo({id, player1: {mainRole: p1Input.value}, player2: {mainRole: p2Input.value}}, adminSessionPin);
  if (!result || result.success === false) {
    alert((result && result.error) || 'No se pudieron guardar los roles.');
    return;
  }

  await refreshAdminData();
  renderAdminDuosList();
  alert(`Roles principales guardados para "${duo.teamName}".`);
}

async function handleSaveDiscordWebhook(id) {
  const duo = adminDuos.find(d => d.id === id);
  const input = document.getElementById(`discord-webhook-${id}`);
  if (!duo || !input) return;
  const webhookUrl = input.value.trim();
  const result = await DataStore.saveDuo({id, discordWebhook: webhookUrl}, adminSessionPin);
  if (!result || result.success === false) {
    alert(result?.error || 'No se pudo guardar el webhook de Discord.');
    return;
  }
  await refreshAdminData();
  renderAdminDuosList();
  alert(`Webhook de Discord guardado para "${duo.teamName}".`);
}

async function handleSaveParticipantProfiles(id) {
  const duo = adminDuos.find(d => d.id === id);
  if (!duo) return;
  const profiles = {};
  for (const i of [1, 2]) {
    const nameInput = document.getElementById(`p${i}-display-name-${id}`);
    const twitchInput = document.getElementById(`p${i}-twitch-url-${id}`);
    if (!nameInput || !twitchInput) return;
    const displayName = nameInput.value.trim();
    const rawUrl = twitchInput.value.trim();
    const twitchUrl = normalizeTwitchUrl(rawUrl);
    if (!displayName || displayName.length > 60) {
      alert('Introduce el nombre de cada integrante (máximo 60 caracteres).');
      nameInput.focus();
      return;
    }
    if (rawUrl && !twitchUrl) {
      alert('Introduce un enlace válido de canal de Twitch.');
      twitchInput.focus();
      return;
    }
    profiles[`player${i}`] = {displayName, twitchUrl};
  }
  const result = await DataStore.saveDuo({id, ...profiles}, adminSessionPin);
  if (!result || result.success === false) {
    alert(result?.error || 'No se pudieron guardar los integrantes.');
    return;
  }
  await refreshAdminData();
  renderAdminDuosList();
  alert(`Nombres y canales de Twitch guardados para "${duo.teamName}".`);
}

let pendingDeleteId = null;

function handleDeleteDuo(id) {
  const duo = adminDuos.find(d => d.id === id);
  pendingDeleteId = id;
  const overlay = document.getElementById('delete-confirm-overlay');
  const msgEl = document.getElementById('delete-confirm-msg');
  
  if (msgEl && duo) {
    const p2Str = duo.player2 && duo.player2.name ? ` & ${duo.player2.name}` : '';
    msgEl.textContent = `¿Estás seguro de eliminar a "${duo.teamName}" (${duo.player1.name}${p2Str})? Esta acción borrará de forma permanente todos sus datos de db.json.`;
  }
  
  if (overlay) overlay.classList.add('active');
}

async function saveConfigForm() {
  const start = tournamentDateTimestamp(document.getElementById('cfg-start').value);
  const end = tournamentDateTimestamp(document.getElementById('cfg-end').value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    alert('Introduce fechas válidas en hora de Madrid; el cierre debe ser posterior al inicio.');
    return;
  }
  const nextConfig = {
    ...adminConfig,
    challengeTitle: document.getElementById('cfg-title').value.trim(),
    prizePool: document.getElementById('cfg-prize').value.trim(),
    startDate: new Date(start).toISOString(),
    endDate: new Date(end).toISOString(),
    twitchClientId: document.getElementById('cfg-twitch-client-id').value.trim()
  };
  const nextAdminPin = document.getElementById('cfg-pin').value.trim();
  const riotApiKey = document.getElementById('cfg-riot-key').value.trim();
  const twitchSecretInput = document.getElementById('cfg-twitch-client-secret');
  const twitchClientSecret = twitchSecretInput.value.trim();

  delete nextConfig.twitchClientSecretConfigured;
  delete nextConfig.adminPinConfigured;
  delete nextConfig.riotApiKeyConfigured;
  if (nextAdminPin) nextConfig.adminPin = nextAdminPin;
  if (riotApiKey) nextConfig.riotApiKey = riotApiKey;
  if (twitchClientSecret) nextConfig.twitchClientSecret = twitchClientSecret;

  const result = await DataStore.saveConfig(nextConfig, adminSessionPin);
  if (!result || !result.success) {
    alert((result && result.error) || "No se pudo guardar la configuración.");
    return;
  }

  if (nextAdminPin) adminSessionPin = nextAdminPin;
  adminConfig = result.config;
  fillConfigForm();
  alert("Configuración actualizada. Twitch comprobará los canales cada 5 minutos.");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener('sync-finished', async () => {
  if (adminSessionPin) { await refreshAdminData(); renderAdminDuosList(); renderAdminPenalties(); refreshAdminWeeklyDiagnostics(); }
});

document.addEventListener('click', event => {
  const penalty = event.target.closest('[data-penalty-id]');
  if (penalty) window.adminPenaltyAction(penalty.dataset.penaltyId, penalty.dataset.penaltyAction);
  const team = event.target.closest('[data-team-action]');
  if (team) ({delete: handleDeleteDuo, roles: handleSaveRoles, profiles: handleSaveParticipantProfiles, webhook: handleSaveDiscordWebhook})[team.dataset.teamAction]?.(team.dataset.teamId);
});
