/* Read-only champion album. No Riot calls, prizes, or mutations. */
(() => {
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('es');
  let board = null, selected = '', timer, revision = 0, controller, disconnected = false;
  const detail = champion => `${champion.name} · ${champion.games === 1 ? '1 aparición' : `${champion.games} apariciones`} en el torneo.`;
  function renderPanel(champion) {
    $('champion-modal-title').textContent = champion.name;
    const players = champion.players || [];
    const totals = players.reduce((total, player) => {
      if (player.statsGames > 0 && Number.isFinite(player.kda)) {
        total.games += player.statsGames;
        total.kills += player.kills;
        total.deaths += player.deaths;
        total.assists += player.assists;
      }
      return total;
    }, {games:0,kills:0,deaths:0,assists:0});
    const generalKda = totals.games ? ((totals.kills + totals.assists) / Math.max(1,totals.deaths)).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}) : champion.games ? 'pendiente' : '—';
    const partial = totals.games > 0 && totals.games < champion.games ? ` (parcial: ${totals.games} de ${champion.games} apariciones)` : '';
    $('champion-modal-summary').textContent = `${detail(champion)} · KDA general: ${generalKda}${partial}`;
    $('champion-modal-players').innerHTML = players.length ? `<div class="champion-players-table-wrap"><table class="champion-players-table"><thead><tr><th scope="col">Jugador / dúo</th><th scope="col">Partidas</th><th scope="col">KDA</th><th scope="col">K / D / A</th></tr></thead><tbody>${players.map(player => {
      const known = player.statsGames > 0 && Number.isFinite(player.kda);
      const partial = known && player.statsGames < player.games;
      return `<tr><td><strong>${escape(player.name)}</strong><span class="champion-player-team">${escape(player.teamName)}</span></td><td>${escape(player.games)}</td><td><strong class="champion-player-kda">${known ? player.kda.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'}</strong>${!known ? '<small>Estadísticas pendientes</small>' : partial ? `<small>Parcial: ${escape(player.statsGames)} de ${escape(player.games)} partidas</small>` : ''}</td><td>${known ? `${escape(player.kills)} / ${escape(player.deaths)} / ${escape(player.assists)}` : '—'}</td></tr>`;
    }).join('')}</tbody></table></div>` : `<p class="champion-players-empty">${champion.games ? 'El detalle de jugadores todavía no está disponible.' : 'Ningún participante ha jugado este campeón en el torneo todavía.'}</p>`;
  }
  function render() {
    if (!board) return;
    const query = key($('champions-search').value.trim());
    const rows = board.champions.filter(champion => key(champion.name).includes(query) || key(champion.id).includes(query));
    $('champions-progress').textContent = `${board.playedChampions} / ${board.totalChampions}`;
    $('champions-picks').textContent = String(board.totalPicks);
    $('champions-progress-bar').max = Math.max(1,board.totalChampions);
    $('champions-progress-bar').value = board.playedChampions;
    $('champions-progress-label').textContent = `${board.totalChampions - board.playedChampions} campeones aún por estrenar`;
    $('champions-warning').hidden = !board.pendingMatches;
    $('champions-warning').textContent = `Hay ${board.pendingMatches} ${board.pendingMatches === 1 ? 'partida con datos pendientes de completar. El recuento puede aumentar cuando se recupere.' : 'partidas con datos pendientes de completar. Los recuentos pueden aumentar cuando se recuperen.'}`;
    const focused = document.activeElement?.closest('[data-champion-id]')?.dataset.championId;
    $('champions-grid').innerHTML = rows.map(champion => {
      const tooltip = champion.games ? `${champion.games} ${champion.games === 1 ? 'aparición' : 'apariciones'}` : 'Aún sin jugar';
      return `<button type="button" class="champion-tile${champion.played ? ' is-played' : ''}${champion.id === selected ? ' is-selected' : ''}" data-champion-id="${escape(champion.id)}" aria-label="${escape(champion.name)}" aria-haspopup="dialog" aria-controls="champion-modal" aria-describedby="champion-tooltip-${escape(champion.id)}"><span class="champion-art"><span class="champion-placeholder" aria-hidden="true" hidden>${escape(champion.name.slice(0,2))}</span><img src="https://ddragon.leagueoflegends.com/cdn/${encodeURIComponent(board.catalogVersion)}/img/champion/${encodeURIComponent(champion.id)}.png" alt="" loading="lazy" width="120" height="120"></span>${champion.played ? '<span class="champion-check" aria-hidden="true">✓</span>' : ''}<span class="champion-name">${escape(champion.name)}</span><span class="champion-tooltip" role="tooltip" id="champion-tooltip-${escape(champion.id)}">${tooltip}</span></button>`;
    }).join('');
    if (focused) [...$('champions-grid').querySelectorAll('[data-champion-id]')].find(tile => tile.dataset.championId === focused)?.focus({preventScroll:true});
    $('champions-empty').hidden = !!rows.length;
    $('champions-status').textContent = disconnected ? 'Conexión interrumpida. Conservamos el último recuento confirmado; reintentaremos automáticamente.' : `${rows.length} campeones · Más jugados primero · ${board.totalMatches} ${board.totalMatches === 1 ? 'partida' : 'partidas'} del torneo`;
    $('champions-status').classList.toggle('is-error',disconnected);
    const current = board.champions.find(champion => champion.id === selected);
    if (current) $('champions-detail').textContent = detail(current);
    if (current && $('champion-modal').open) renderPanel(current);
  }
  async function refresh() {
    clearTimeout(timer); controller?.abort();
    const ownRevision = ++revision;
    controller = new AbortController();
    const current = controller;
    const timeout = setTimeout(() => current.abort(),15000);
    $('champions-refresh').disabled = true;
    try {
      const response = await fetch(`${API_BASE_URL}/champions`,{signal:current.signal,cache:'no-store'});
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.champions)) throw new Error('No se pudo consultar el álbum.');
      if (ownRevision !== revision) return;
      board = data; disconnected = false; render();
    } catch (_) {
      if (ownRevision !== revision) return;
      disconnected = true;
      $('champions-status').textContent = board ? 'Conexión interrumpida. Conservamos el último recuento confirmado; reintentaremos automáticamente.' : 'No se pudo cargar el álbum. Reintentaremos automáticamente o puedes pulsar Actualizar.';
      $('champions-status').classList.add('is-error');
    } finally {
      clearTimeout(timeout);
      if (ownRevision === revision) {
        $('champions-refresh').disabled = false;
        if (!document.hidden) timer = setTimeout(refresh,30000);
      }
    }
  }
  document.addEventListener('DOMContentLoaded',() => {
    $('champions-search').addEventListener('input',render);
    $('champions-refresh').addEventListener('click',refresh);
    const modal = $('champion-modal');
    $('champion-modal-close').addEventListener('click', () => modal.close());
    modal.addEventListener('click', event => {
      const rect = modal.getBoundingClientRect();
      if (event.target === modal && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) modal.close();
    });
    modal.addEventListener('close', () => {
      [...$('champions-grid').querySelectorAll('[data-champion-id]')].find(tile => tile.dataset.championId === selected)?.focus({preventScroll:true});
    });
    $('champions-grid').addEventListener('click',event => {
      const tile = event.target.closest('[data-champion-id]');
      if (!tile || !board) return;
      selected = tile.dataset.championId;
      $('champions-grid').querySelectorAll('.is-selected').forEach(item => item.classList.remove('is-selected'));
      tile.classList.add('is-selected');
      const champion = board.champions.find(champion => champion.id === selected);
      if (!champion) return;
      $('champions-detail').textContent = detail(champion);
      renderPanel(champion); modal.showModal();
    });
    $('champions-grid').addEventListener('error',event => {
      if (event.target.tagName !== 'IMG') return;
      event.target.hidden = true;
      event.target.parentElement.querySelector('.champion-placeholder').hidden = false;
    },true);
    refresh();
  });
  document.addEventListener('visibilitychange',() => {if (document.hidden) clearTimeout(timer); else refresh();});
  window.addEventListener('pagehide',() => {clearTimeout(timer); controller?.abort();});
})();
