document.addEventListener('DOMContentLoaded', () => {
  async function refresh() {
    try {
      if (!document.hidden) await Promise.all([refreshRouletteRules(), renderTrophies()]);
    } finally { setTimeout(refresh, 15000); }
  }
  refresh();
});

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;'}[ch]));
}

let rouletteRulesSignature = '';

async function refreshRouletteRules() {
  renderRouletteRules(await DataStore.getConfig());
}

function renderShellRewardRules(config) {
  const body = document.getElementById('shell-rewards-body');
  if (!body) return;
  const rewards = config.shellRewardRules;
  if (!rewards || !Array.isArray(rewards.rules)) {
    body.innerHTML = '<tr><td colspan="3">No se han podido cargar los requisitos. Se reintentará en la próxima actualización.</td></tr>';
    return;
  }
  body.innerHTML = rewards.rules.map(rule => `<tr><td>${escapeHtml(rule.name)}</td><td>${escapeHtml(rule.requirement)}</td><td>+1 🐢</td></tr>`).join('');
  document.getElementById('shell-rewards-limits').textContent = `Máximo ${rewards.inventoryLimit} caparazones en el inventario y ${rewards.perMatchLimit} obtenidos por equipo y partida, incluida la racha. Con el inventario lleno, los premios adicionales se pierden y no se recuperan después.`;
}

function renderRouletteRules(config) {
  renderShellRewardRules(config);
  const container = document.getElementById('roulette-rules-list');
  if (!container) return;
  const catalog = Array.isArray(config.penaltyCatalog) ? config.penaltyCatalog : [];
  const weights = config.penaltyWeights || {};
  const signature = JSON.stringify([catalog, weights]);
  if (signature === rouletteRulesSignature) return;
  rouletteRulesSignature = signature;
  container.replaceChildren();
  if (!catalog.length) {
    const message = document.createElement('p');
    message.className = 'roulette-rules-empty';
    message.textContent = 'No se han podido cargar los castigos. Se volverá a intentar en la próxima actualización.';
    container.append(message);
    return;
  }
  for (const penalty of catalog) {
    const value = weights[penalty.id];
    const percentage = value == null ? NaN : Number(value);
    const available = Number.isFinite(percentage) && percentage >= 0;
    const disabled = available && percentage === 0;
    const card = document.createElement('article');
    card.className = 'roulette-rule' + (disabled ? ' is-disabled' : '');
    const heading = document.createElement('div');
    heading.className = 'roulette-rule-heading';
    const title = document.createElement('h3');
    const icon = document.createElement('span');
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = penalty.icon || '🎲';
    title.append(icon, document.createTextNode(' ' + penalty.name));
    const chance = document.createElement('span');
    chance.className = 'roulette-rule-chance';
    chance.textContent = available ? `${percentage}%${disabled ? ' · Desactivado' : ''}` : 'Sin datos';
    heading.append(title, chance);
    const description = document.createElement('p');
    description.textContent = penalty.desc || '';
    card.append(heading, description);
    container.append(card);
  }
}

async function renderTrophies() {
  const grid = document.getElementById('trophies-grid');
  if (!grid) return;
  const data = await DataStore.getTrophies();
  if (!Array.isArray(data.cards) || !data.cards.length) {
    document.getElementById('trophies-status').textContent = 'No se han podido cargar los trofeos. Se volverá a intentar.';
    return;
  }
  const awarded = data.status === 'awarded';
  document.getElementById('trophies-status').textContent = awarded ? 'Torneo cerrado · Premios adjudicados salvo empates pendientes' : 'Clasificación provisional · Se entregan al finalizar';
  document.getElementById('trophies-note').textContent = `KDA acumulado: (kills + asistencias) / máximo de 1 y muertes. Cada jugador compite solo en su rol principal configurado. Solo cuentan las partidas jugadas en ese rol; los cambios de rol por castigo y las partidas sin rol identificado quedan excluidos. Sin mínimo de partidas. Los trofeos se conceden al finalizar el torneo.`;
  grid.innerHTML = data.cards.map(card => {
    const entries = card.entries || [];
    return `<article class="trophy-card ${card.id === 'dishonor' ? 'trophy-dishonor' : ''}">
      <header><span class="trophy-icon" aria-hidden="true">${escapeHtml(card.icon)}</span><h3>${escapeHtml(card.title)}</h3></header>
      <p class="trophy-description">${escapeHtml(card.description)}</p>
      ${entries.length ? `<div class="trophy-leader"><small>${entries[0].tied ? 'Empate pendiente de resolver' : awarded ? 'Premiado' : 'Líder provisional'}</small><strong>${escapeHtml(entries[0].name)}</strong><span>${escapeHtml(entries[0].value)}</span></div>
      <ol class="trophy-list">${entries.map(entry => `<li><div><strong>${escapeHtml(entry.name)}</strong><small>${escapeHtml(entry.teamName)}${entry.games ? ' · ' + entry.games + ' partidas' : ''}${entry.tied ? ' · Empatado' : ''}</small></div><b>${escapeHtml(entry.value)}</b></li>`).join('')}</ol>` : '<p class="fun-stats-empty">Sin participantes con datos para este trofeo.</p>'}
    </article>`;
  }).join('');
}
