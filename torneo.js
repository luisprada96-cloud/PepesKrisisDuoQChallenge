document.addEventListener('DOMContentLoaded', () => {
  if (location.hash === '#trophies') { location.replace('premios.html#trophies'); return; }
  async function refresh() {
    try {
      if (!document.hidden) await refreshRouletteRules();
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
