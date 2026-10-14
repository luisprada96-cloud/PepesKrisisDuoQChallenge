document.addEventListener('DOMContentLoaded', () => {
  async function refresh() {
    try { if (!document.hidden) await renderTrophies(); }
    finally { setTimeout(refresh, 15000); }
  }
  refresh();
});

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;'}[ch]));
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
