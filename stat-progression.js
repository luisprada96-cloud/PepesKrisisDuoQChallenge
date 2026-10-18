/* Cumulative participant progression. All three metrics share one confirmed read. */
(() => {
  'use strict';
  const metrics = {kills: {label: 'Kills', unit: 'kills'}, assists: {label: 'Asistencias', unit: 'asistencias'}, deaths: {label: 'Muertes', unit: 'muertes'}};
  const colors = ['#00e5ff','#ffc947','#ff6fa5','#8ee38b','#b49bff','#ff9c63','#65b6ff','#f58ee1','#b8df5d','#54dec4','#e6b8ff','#ff777b','#ffe184','#6fe4a3','#92a9ff','#e8ac72','#d5dbe8','#d192d9'];
  const W = 1100, H = 420, pad = {left: 72, right: 26, top: 24, bottom: 62};
  const state = {metric: 'kills', payload: null, signature: '', activeId: null, activeGame: null, pinned: false, loading: false, initialized: false};
  const el = id => document.getElementById(`stat-progression-${id}`);
  const escape = value => escapeHtml(String(value ?? ''));
  const format = value => value.toLocaleString('es-ES');
  let scale = null;

  function normalize(payload) {
    if (!payload || !Array.isArray(payload.players)) return null;
    const seen = new Set();
    const players = payload.players.filter(p => p && typeof p.id === 'string' && !seen.has(p.id) && seen.add(p.id)).map(p => {
      const points = Array.isArray(p.points) ? p.points.filter((point, i) => point?.game === i + 1 && ['kills','deaths','assists'].every(k => Number.isSafeInteger(point[k]) && point[k] >= 0)) : [];
      return {id: p.id, name: String(p.name || 'Integrante'), teamName: String(p.teamName || 'Equipo'), points, games: points.length};
    });
    const ordered = players.map(p => p.id).sort();
    for (const p of players) p.color = colors[ordered.indexOf(p.id) % colors.length];
    return {players, pendingMatches: Number.isFinite(payload.pendingMatches) ? Math.max(0, payload.pendingMatches) : 0};
  }

  function niceStep(value) {
    if (value <= 1) return 1;
    const power = 10 ** Math.floor(Math.log10(value));
    return [1, 2, 5, 10].find(v => v * power >= value) * power;
  }

  function pointAt(player, game) {
    return game > 0 ? player.points[Math.min(game, player.games) - 1] : {game: 0, kills: 0, deaths: 0, assists: 0};
  }

  function label(player, point) {
    return `${player.name} · ${player.teamName} · Partida ${point.game} · ${format(point[state.metric])} ${metrics[state.metric].unit} acumuladas`;
  }

  function clearSelection() {
    state.activeId = null; state.activeGame = null; state.pinned = false;
    highlight();
  }

  function highlight(clientPoint) {
    const players = state.payload?.players || [];
    const selected = players.find(p => p.id === state.activeId);
    for (const path of el('plot').querySelectorAll('[data-series-path]')) {
      const active = path.dataset.seriesId === selected?.id;
      path.style.opacity = !selected || active ? '1' : '.16';
      path.style.strokeWidth = active ? '3.8' : '2.1';
    }
    for (const button of el('legend').querySelectorAll('button')) {
      button.classList.toggle('is-highlighted', button.dataset.seriesId === selected?.id);
      button.classList.toggle('is-muted', !!selected && button.dataset.seriesId !== selected.id);
      button.setAttribute('aria-pressed', String(state.pinned && button.dataset.seriesId === selected?.id));
    }
    const marker = el('plot').querySelector('[data-progression-marker]');
    const tooltip = el('tooltip');
    if (!selected) {
      tooltip.hidden = true;
      if (marker) marker.setAttribute('visibility', 'hidden');
      el('detail').textContent = 'Pasa por una línea o selecciona un integrante para ver sus datos.';
      return;
    }
    if (!selected.games) {
      tooltip.hidden = true;
      el('detail').textContent = `${selected.name} · ${selected.teamName} · Sin partidas registradas todavía.`;
      if (marker) marker.setAttribute('visibility', 'hidden');
      return;
    }
    const point = pointAt(selected, Math.min(state.activeGame ?? selected.games, selected.games));
    const text = label(selected, point);
    el('detail').textContent = text;
    tooltip.innerHTML = `<strong>${escape(selected.name)}</strong><span>${escape(selected.teamName)}</span><b>Partida ${point.game} · ${format(point[state.metric])} ${metrics[state.metric].unit}</b>`;
    tooltip.hidden = false;
    tooltip.style.borderColor = selected.color;
    if (marker && scale) {
      marker.setAttribute('cx', scale.x(point.game));
      marker.setAttribute('cy', scale.y(point[state.metric]));
      marker.setAttribute('fill', selected.color);
      marker.setAttribute('visibility', 'visible');
    }
    const frame = el('frame').getBoundingClientRect();
    const left = clientPoint ? clientPoint.x - frame.left + 14 : frame.width - tooltip.offsetWidth - 14;
    const top = clientPoint ? clientPoint.y - frame.top - tooltip.offsetHeight - 14 : 12;
    tooltip.style.left = `${Math.max(8, Math.min(left, frame.width - tooltip.offsetWidth - 8))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(top, frame.height - tooltip.offsetHeight - 8))}px`;
  }

  function selectMetric(metric) {
    if (!metrics[metric]) return;
    state.metric = metric;
    render();
  }

  function render() {
    const metric = metrics[state.metric];
    for (const button of document.querySelectorAll('[data-progression-metric]')) {
      const active = button.dataset.progressionMetric === state.metric;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    }
    el('panel').setAttribute('aria-labelledby', `progression-tab-${state.metric}`);
    if (!state.payload) return;
    const players = state.payload.players;
    const focused = el('legend').contains(document.activeElement) ? document.activeElement.dataset.seriesId : null;
    el('status').textContent = `${players.length} integrantes · ${metric.label} acumuladas${state.payload.pendingMatches ? ' · Hay partidas pendientes de completar; se muestran los datos confirmados.' : ''}`;
    el('legend').innerHTML = players.map(p => `<button type="button" data-series-id="${escape(p.id)}" aria-pressed="false" style="--series-color:${p.color}" aria-label="${escape(`${p.name} · ${p.teamName} · ${p.games} partidas`)}"><i aria-hidden="true"></i><span><strong>${escape(p.name)}</strong><small>${escape(p.teamName)} · ${p.games} ${p.games === 1 ? 'partida' : 'partidas'}</small></span></button>`).join('');
    const maxGames = Math.max(0, ...players.map(p => p.games));
    if (!maxGames) {
      scale = null;
      el('plot').innerHTML = '<p class="stat-progression-empty">La gráfica aparecerá con las primeras partidas registradas.</p>';
      highlight();
      return;
    }
    const maxValue = Math.max(1, ...players.map(p => p.points.at(-1)?.[state.metric] || 0));
    const yStep = niceStep(maxValue / 5), yMax = Math.ceil(maxValue / yStep) * yStep;
    scale = {x: game => pad.left + game / maxGames * (W - pad.left - pad.right), y: value => H - pad.bottom - value / yMax * (H - pad.top - pad.bottom)};
    let grid = '';
    for (let value = 0; value <= yMax; value += yStep) grid += `<line class="progression-grid" x1="${pad.left}" x2="${W-pad.right}" y1="${scale.y(value)}" y2="${scale.y(value)}"/><text class="progression-tick" x="${pad.left-12}" y="${scale.y(value)+4}" text-anchor="end">${format(value)}</text>`;
    const xStep = niceStep(maxGames / 8);
    for (let game = 0; game <= maxGames; game += xStep) grid += `<text class="progression-tick" x="${scale.x(game)}" y="${H-pad.bottom+25}" text-anchor="middle">${game}</text>`;
    const lines = players.map(p => {
      const points = [{game: 0, kills: 0, deaths: 0, assists: 0}, ...p.points];
      const path = points.map((point, i) => `${i ? 'L' : 'M'}${scale.x(point.game).toFixed(2)},${scale.y(point[state.metric]).toFixed(2)}`).join(' ');
      return `<path data-series-path data-series-id="${escape(p.id)}" d="${path}" fill="none" stroke="${p.color}" stroke-width="2.1" stroke-linejoin="round" stroke-linecap="round"><title>${escape(p.name)} · ${escape(p.teamName)}</title></path>`;
    }).join('');
    el('plot').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="${metric.label} acumuladas por número de partidas de los ${players.length} integrantes"><g>${grid}</g><line class="progression-axis" x1="${pad.left}" x2="${W-pad.right}" y1="${H-pad.bottom}" y2="${H-pad.bottom}"/><line class="progression-axis" x1="${pad.left}" x2="${pad.left}" y1="${pad.top}" y2="${H-pad.bottom}"/><text class="progression-axis-label" x="${(W+pad.left-pad.right)/2}" y="${H-12}" text-anchor="middle">Número de partidas</text><text class="progression-axis-label" x="20" y="${(H+pad.top-pad.bottom)/2}" text-anchor="middle" transform="rotate(-90 20 ${(H+pad.top-pad.bottom)/2})">${metric.label} acumuladas</text><g class="progression-series">${lines}</g><circle data-progression-marker r="5.5" stroke="#0a0f1d" stroke-width="3" visibility="hidden" pointer-events="none"/></svg>`;
    highlight();
    if (focused) [...el('legend').querySelectorAll('button')].find(b => b.dataset.seriesId === focused)?.focus({preventScroll: true});
  }

  function nearest(event) {
    const svg = el('plot').querySelector('svg');
    if (!svg || !scale) return null;
    const rect = svg.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * W;
    const y = (event.clientY - rect.top) / rect.height * H;
    const game = (x - pad.left) / (W - pad.left - pad.right) * Math.max(...state.payload.players.map(p => p.games));
    if (x < pad.left || x > W-pad.right || y < pad.top || y > H-pad.bottom) return null;
    let best = null, distance = (event.pointerType === 'touch' ? 22 : 11) * W / rect.width;
    for (const player of state.payload.players) {
      if (!player.games || game > player.games + .04) continue;
      const index = Math.min(player.games - 1, Math.max(0, Math.floor(game)));
      const before = pointAt(player, index), after = pointAt(player, index + 1);
      const value = before[state.metric] + (after[state.metric] - before[state.metric]) * (game - index);
      const delta = Math.abs(y - scale.y(value));
      if (delta < distance) { distance = delta; best = {id: player.id, game: Math.max(0, Math.min(player.games, Math.round(game)))}; }
    }
    return best;
  }

  async function refresh() {
    if (!el('plot') || state.loading) return;
    state.loading = true;
    try {
      const payload = normalize(await DataStore.getStatProgression());
      if (!payload) {
        if (!state.payload) el('status').innerHTML = 'No se ha podido cargar la evolución. <button type="button" data-progression-retry>Reintentar</button>';
        return;
      }
      const signature = JSON.stringify(payload);
      if (signature !== state.signature) { state.payload = payload; state.signature = signature; render(); }
    } catch (_) {
      if (!state.payload) el('status').innerHTML = 'No se ha podido cargar la evolución. <button type="button" data-progression-retry>Reintentar</button>';
    } finally { state.loading = false; }
  }

  function init() {
    if (state.initialized || !el('plot')) return;
    state.initialized = true;
    el('panel').closest('section').addEventListener('click', event => {
      const metric = event.target.closest('[data-progression-metric]');
      if (metric) { selectMetric(metric.dataset.progressionMetric); return; }
      if (event.target.closest('[data-progression-retry]')) { refresh(); return; }
      const person = event.target.closest('#stat-progression-legend button');
      if (person) {
        if (state.activeId === person.dataset.seriesId && state.pinned) clearSelection();
        else { state.activeId = person.dataset.seriesId; state.activeGame = null; state.pinned = true; highlight(); }
      }
    });
    el('panel').closest('section').addEventListener('keydown', event => {
      if (event.key === 'Escape') clearSelection();
      const tab = event.target.closest('[data-progression-metric]');
      if (tab && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        event.preventDefault();
        const keys = ['kills','assists','deaths'];
        const index = keys.indexOf(state.metric);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
        selectMetric(keys[next]); document.getElementById(`progression-tab-${keys[next]}`).focus();
      }
    });
    for (const type of ['pointerover','focusin']) el('legend').addEventListener(type, event => {
      const button = event.target.closest('button');
      if (button && !state.pinned) { state.activeId = button.dataset.seriesId; state.activeGame = null; highlight(); }
    });
    el('legend').addEventListener('pointerleave', () => { if (!state.pinned) clearSelection(); });
    el('legend').addEventListener('focusout', event => { if (!state.pinned && !el('legend').contains(event.relatedTarget)) clearSelection(); });
    el('plot').addEventListener('pointermove', event => {
      if (state.pinned || event.pointerType === 'touch') return;
      const found = nearest(event);
      if (!found) { clearSelection(); return; }
      state.activeId = found.id; state.activeGame = found.game; highlight({x:event.clientX, y:event.clientY});
    });
    el('plot').addEventListener('pointerleave', () => { if (!state.pinned) clearSelection(); });
    el('plot').addEventListener('click', event => {
      const found = nearest(event);
      if (found) {
        const wasPinned = state.pinned && state.activeId === found.id;
        state.activeId = found.id; state.activeGame = found.game; state.pinned = !wasPinned;
        highlight({x:event.clientX,y:event.clientY});
      }
    });
    refresh();
  }
  window.StatProgression = {init, refresh};
})();
