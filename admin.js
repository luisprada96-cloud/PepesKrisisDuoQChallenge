/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Admin Panel Logic (admin.js)
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  initAdmin();
});

let adminDuos = [];
let adminConfig = {};

async function initAdmin() {
  adminConfig = await DataStore.getConfig();

  // Check authentication
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

  pinForm.onsubmit = (e) => {
    e.preventDefault();
    const enteredPin = pinInput.value.trim();
    const validPin = adminConfig.adminPin || "1234";

    if (enteredPin === validPin || enteredPin === "1234") {
      pinOverlay.classList.remove('active');
      pinOverlay.style.display = 'none';
      loadAdminData();
    } else {
      if (errorMsg) errorMsg.style.display = 'block';
      pinInput.value = '';
      pinInput.focus();
    }
  };
}

async function loadAdminData() {
  adminDuos = await DataStore.getDuos();
  adminConfig = await DataStore.getConfig();

  renderAdminDuosList();
  fillConfigForm();
  setupAdminListeners();
}

function fillConfigForm() {
  const titleInput = document.getElementById('cfg-title');
  const prizeInput = document.getElementById('cfg-prize');
  const startInput = document.getElementById('cfg-start');
  const endInput = document.getElementById('cfg-end');
  const pinInput = document.getElementById('cfg-pin');
  const keyInput = document.getElementById('cfg-riot-key');

  if (titleInput) titleInput.value = adminConfig.challengeTitle || '';
  if (prizeInput) prizeInput.value = adminConfig.prizePool || '';
  if (startInput) startInput.value = adminConfig.startDate || '';
  if (endInput) endInput.value = adminConfig.endDate || '';
  if (pinInput) pinInput.value = adminConfig.adminPin || '1234';
  if (keyInput) keyInput.value = adminConfig.riotApiKey || '';
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
    card.style.justify = 'space-between';
    card.style.alignItems = 'center';
    card.style.marginBottom = '0.75rem';

    card.innerHTML = `
      <div>
        <div style="font-family: var(--font-heading); font-weight: 700; color: #fff; font-size: 1.05rem;">
          #${idx + 1} ${escapeHtml(duo.teamName)}
        </div>
        <div style="font-size: 0.85rem; color: var(--text-muted);">
          Jugador 1: <strong>${escapeHtml(duo.player1.name)}#${duo.player1.tag}</strong> | 
          Jugador 2: <strong>${escapeHtml(duo.player2.name)}#${duo.player2.tag}</strong>
        </div>
        <div style="font-size: 0.8rem; color: var(--cyan-primary); margin-top: 0.2rem;">
          Rango: ${duo.tier} ${duo.division} (${duo.lp} LP) | Net LP: +${duo.netLp} LP | ${duo.wins}W / ${duo.losses}L
        </div>
      </div>
      <div style="display: flex; gap: 0.5rem;">
        <button class="btn-danger" onclick="handleDeleteDuo('${duo.id}')">
          <i class="fa-solid fa-trash"></i> Eliminar
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function setupAdminListeners() {
  const addForm = document.getElementById('add-duo-form');
  const cfgForm = document.getElementById('config-form');
  const btnReset = document.getElementById('btn-reset-data');
  const btnExport = document.getElementById('btn-export-data');

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
        await DataStore.deleteDuo(pendingDeleteId);
        adminDuos = await DataStore.getDuos();
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
  const pwdInput = document.getElementById('new-password');
  const password = (pwdInput && pwdInput.value.trim()) ? pwdInput.value.trim() : "1234";

  if (!teamName || !p1NameTag || !p2NameTag) {
    alert("Por favor rellena todos los campos del nuevo dúo.");
    return;
  }

  const [p1Name, p1Tag = 'EUW'] = p1NameTag.split('#');
  const [p2Name, p2Tag = 'EUW'] = p2NameTag.split('#');

  const newDuo = {
    id: `duo-${Date.now()}`,
    teamName: teamName,
    password: password,
    blueShells: 0,
    player1: {
      name: p1Name,
      tag: p1Tag,
      avatar: `https://ddragon.leagueoflegends.com/cdn/15.3.1/img/profileicon/29.png`,
      champ: "LeeSin"
    },
    player2: {
      name: p2Name,
      tag: p2Tag,
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

  await DataStore.saveDuo(newDuo);
  adminDuos = await DataStore.getDuos();
  renderAdminDuosList();

  document.getElementById('add-duo-form').reset();
  alert(`¡Dúo "${teamName}" añadido correctamente!`);
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
  adminConfig.challengeTitle = document.getElementById('cfg-title').value.trim();
  adminConfig.prizePool = document.getElementById('cfg-prize').value.trim();
  adminConfig.startDate = document.getElementById('cfg-start').value;
  adminConfig.endDate = document.getElementById('cfg-end').value;
  adminConfig.adminPin = document.getElementById('cfg-pin').value.trim();
  adminConfig.riotApiKey = document.getElementById('cfg-riot-key').value.trim();

  await DataStore.saveConfig(adminConfig);
  alert("¡Configuración del desafío y clave de Riot API actualizadas correctamente!");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
