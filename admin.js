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
}

async function refreshAdminData() {
  if (adminSessionPin) {
    const result = await DataStore.getAdminConfig(adminSessionPin);
    if (result.success) {
      adminDuos = result.duos || [];
      adminConfig = result.config || adminConfig;
      penaltyCatalog = result.penaltyCatalog || penaltyCatalog;
      return;
    }
  }
  adminDuos = await DataStore.getDuos();
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
    const scope = debuff.scope || pen.scope;
    return `<tr>
      <td><time>${escapeHtml(formatPenaltyTimestamp(debuff.assignedAt || debuff.timestamp))}</time></td>
      <td><strong>${escapeHtml(duo.teamName || 'Equipo')}</strong></td>
      <td><span class="admin-penalty-name">${pen.icon || '⚡'} ${escapeHtml(pen.name || 'Castigo')}</span></td>
      <td>${escapeHtml(scope === 'BOTH' ? 'Ambos' : scope === 'SPECIAL' ? 'Especial' : 'Uno')}</td>
      <td><span class="admin-penalty-status ${completed ? 'is-completed' : 'is-active'}">${completed ? 'Cumplido' : 'Activo'}</span></td>
      <td>${completed ? `<time>${escapeHtml(formatPenaltyTimestamp(debuff.resolvedAt))}</time>` : '<span class="admin-penalty-empty">—</span>'}</td>
      <td>${debuff.id ? `<button type="button" class="btn-refresh admin-penalty-action" onclick="window.adminPenaltyAction('${escapeHtml(debuff.id)}','${completed ? 'REOPEN' : 'COMPLETE'}')">${completed ? 'Reabrir' : 'Marcar cumplido'}</button>` : '<span class="legacy-penalty-label">Antiguo</span>'}</td>
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
  if (startInput) startInput.value = adminConfig.startDate || '';
  if (endInput) endInput.value = adminConfig.endDate || '';
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
            Rango: ${duo.tier} ${duo.division} (${duo.lp} LP) | Net LP: +${duo.netLp} LP | ${duo.wins}W / ${duo.losses}L
          </div>
        </div>
        <div>
          <button class="btn-danger" onclick="handleDeleteDuo('${duo.id}')">
            <i class="fa-solid fa-trash"></i> Eliminar
          </button>
        </div>
      </div>
      <div style="display: flex; align-items: end; gap: 0.65rem; flex-wrap: wrap;">
        <div class="form-group" style="flex: 1 1 220px; margin: 0;">
          <label for="p1-role-${duo.id}">Rol principal · ${escapeHtml(duo.player1.name)}</label>
          <select id="p1-role-${duo.id}" class="form-control" required>
            ${renderRoleOptions(duo.player1.mainRole)}
          </select>
        </div>
        <div class="form-group" style="flex: 1 1 220px; margin: 0;">
          <label for="p2-role-${duo.id}">Rol principal · ${escapeHtml(duo.player2.name)}</label>
          <select id="p2-role-${duo.id}" class="form-control" required>
            ${renderRoleOptions(duo.player2.mainRole)}
          </select>
        </div>
        <button class="btn-refresh" onclick="handleSaveRoles('${duo.id}')" style="height: fit-content;">
          <i class="fa-solid fa-user-tag"></i> Guardar roles
        </button>
      </div>
      <div style="display: flex; align-items: end; gap: 0.65rem; flex-wrap: wrap;">
        <div class="form-group" style="flex: 1 1 320px; margin: 0;">
          <label for="twitch-url-${duo.id}">Canal de Twitch</label>
          <input type="url" id="twitch-url-${duo.id}" class="form-control" value="${escapeHtml(duo.twitchUrl || '')}" placeholder="https://www.twitch.tv/nombre_del_canal">
        </div>
        <button class="btn-refresh" onclick="handleSaveTwitch('${duo.id}')" style="height: fit-content;">
          <i class="fa-brands fa-twitch"></i> Guardar Twitch
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
        adminDuos = result.duos || await DataStore.getDuos();
        renderAdminDuosList();
        const message = `Twitch comprobado: ${result.checked || 0} canal(es), ${result.live || 0} en directo.`;
        window.showToast ? showToast(message, 'success') : alert(message);
      } else {
        alert(result.error || 'No se pudo comprobar el estado de Twitch.');
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

      const res = await DataStore.calculateShells();
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

      adminDuos = await DataStore.triggerRiotSync();
      renderAdminDuosList();

      if (icon) icon.classList.remove('spinning');
      btnSyncMatches.disabled = false;

      if (window.showToast) {
        showToast('¡Últimas 5 partidas de cada equipo recuperadas con éxito desde la API de Riot Games!', 'success');
      } else {
        alert('¡Últimas 5 partidas de cada equipo recuperadas con éxito desde la API de Riot Games!');
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
  const twitchInput = document.getElementById('new-twitch-url');
  const rawTwitchUrl = twitchInput ? twitchInput.value.trim() : '';
  const twitchUrl = normalizeTwitchUrl(rawTwitchUrl);

  if (!teamName || !p1NameTag || !p2NameTag || !p1Role || !p2Role) {
    alert("Por favor rellena todos los campos del nuevo dúo.");
    return;
  }

  if (rawTwitchUrl && !twitchUrl) {
    alert("Introduce una URL válida de canal de Twitch, por ejemplo: https://www.twitch.tv/nombre_del_canal");
    twitchInput.focus();
    return;
  }

  const [p1Name, p1Tag = 'EUW'] = p1NameTag.split('#');
  const [p2Name, p2Tag = 'EUW'] = p2NameTag.split('#');

  const newDuo = {
    id: `duo-${Date.now()}`,
    teamName: teamName,
    twitchUrl: twitchUrl,
    password: password,
    blueShells: 0,
    player1: {
      name: p1Name,
      tag: p1Tag,
      mainRole: p1Role,
      avatar: `https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/29.png`,
      champ: "LeeSin"
    },
    player2: {
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

  duo.player1.mainRole = p1Input.value;
  duo.player2.mainRole = p2Input.value;
  const result = await DataStore.saveDuo(duo, adminSessionPin);
  if (!result || result.success === false) {
    alert((result && result.error) || 'No se pudieron guardar los roles.');
    return;
  }

  await refreshAdminData();
  renderAdminDuosList();
  alert(`Roles principales guardados para "${duo.teamName}".`);
}

async function handleSaveTwitch(id) {
  const duo = adminDuos.find(d => d.id === id);
  const input = document.getElementById(`twitch-url-${id}`);
  if (!duo || !input) return;

  const rawTwitchUrl = input.value.trim();
  const twitchUrl = normalizeTwitchUrl(rawTwitchUrl);

  if (rawTwitchUrl && !twitchUrl) {
    alert("Introduce una URL válida de canal de Twitch, por ejemplo: https://www.twitch.tv/nombre_del_canal");
    input.focus();
    return;
  }

  duo.twitchUrl = twitchUrl;
  const result = await DataStore.saveDuo(duo, adminSessionPin);
  if (!result || result.success === false) {
    alert((result && result.error) || 'No se pudo guardar el canal de Twitch.');
    return;
  }
  await refreshAdminData();
  renderAdminDuosList();
  alert(twitchUrl ? `Canal de Twitch guardado para "${duo.teamName}".` : `Canal de Twitch eliminado de "${duo.teamName}".`);
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
  const nextConfig = {
    ...adminConfig,
    challengeTitle: document.getElementById('cfg-title').value.trim(),
    prizePool: document.getElementById('cfg-prize').value.trim(),
    startDate: document.getElementById('cfg-start').value,
    endDate: document.getElementById('cfg-end').value,
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
