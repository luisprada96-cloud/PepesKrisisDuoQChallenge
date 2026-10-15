/* Public weekly archive; reports use stored games and observed ranks. */
(() => {
  const params = new URLSearchParams(location.search);
  let selectedWeek = params.get('week') || '';
  let selectedTeam = params.get('team') || '';
  let view = selectedTeam ? 'team' : 'general';
  let followLatest = !selectedWeek;
  let summary = null;
  let requestVersion = 0;
  let signature = '';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const date = (seconds, time = false) => new Date(seconds * 1000).toLocaleString('es-ES', {
    timeZone:'Europe/Madrid', day:'2-digit', month:'short', ...(time ? {hour:'2-digit', minute:'2-digit'} : {year:'numeric'})});
  const period = report => `${date(report.startsAt)} — ${date(report.endsAt - 1)}`;
  const kda = (totals, value) => value == null ? '—' : totals.deaths === 0 ? 'Perfecto' : Number(value).toFixed(2);
  const rank = point => point ? `${point.tier || 'Sin rango'} ${point.division || ''} · ${point.lp ?? '—'} LP` : 'Sin registro';
  const metric = (label, value) => `<div><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`;
  const card = (label, name, detail) => `<article class="weekly-card"><span>${escape(label)}</span><h3>${escape(name)}</h3><p>${escape(detail)}</p></article>`;

  function updateUrl() {
    const query = new URLSearchParams();
    if (selectedWeek) query.set('week', selectedWeek);
    if (view === 'team' && selectedTeam) query.set('team', selectedTeam);
    history.replaceState(null, '', `${location.pathname}?${query}`);
  }

  function winnerHtml() {
    const clips = summary.clips;
    const winner = clips.winner;
    if (winner?.status === 'AWARDED') {
      let url = '';
      try {
        const parsed = new URL(winner.url);
        if (parsed.protocol === 'https:' && parsed.hostname === 'clips.twitch.tv' && !parsed.username && !parsed.password && !parsed.port && /^\/[A-Za-z0-9_-]{1,200}$/.test(parsed.pathname)) url = parsed.href;
      } catch (_) {}
      return `<article class="weekly-card weekly-clip">
        ${url ? `<button type="button" class="weekly-play-clip" data-weekly-clip="${escape(url)}"><i class="fa-brands fa-twitch" aria-hidden="true"></i><br>Ver clip ganador</button>` : ''}
        <div class="weekly-clip-body"><span>CLIP DE LA SEMANA</span><h3>${escape(winner.title)}</h3><p>${escape(winner.teamName)} · ${escape(winner.votes)} likes</p><p><span class="weekly-badge">Premio: +${escape(winner.shells)} pepazos</span></p>
        ${url ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">Ver en Twitch ↗</a>` : ''}</div></article><div id="weekly-clip-embed"></div>`;
    }
    const message = summary.status === 'CURRENT' ? 'El clip ganador se decide el domingo a las 23:59.' : clips.available ? 'Esta semana no hubo un clip con votos que pudiera recibir el premio.' : 'No hay registro de los clips de esta semana.';
    return `<article class="weekly-card"><span>🎬 Clips de la semana</span><p>${escape(message)}</p></article>`;
  }

  function generalHtml() {
    const h = summary.highlights;
    const highlights = [];
    if (h.rising) highlights.push(card('🚀 La subida de la semana', h.rising.name, `+${h.rising.elo.delta} LP observados · ${h.rising.teamName}`));
    if (h.falling) highlights.push(card('📉 Semana para olvidar', h.falling.name, `${h.falling.elo.delta} LP observados · ${h.falling.teamName}`));
    if (h.attacker) highlights.push(card('🐢 El más peligroso', h.attacker.name, `${h.attacker.shells.launched} lanzados · ${h.attacker.shells.returned} devueltos`));
    if (h.completed) highlights.push(card('⚡ Misión cumplida', h.completed.name, `${h.completed.penaltiesCompleted} castigos individuales cumplidos · ${h.completed.teamName}`));
    return `<div class="weekly-metrics">${metric('Partidas registradas', summary.totals.games)}${metric('Pepazos lanzados', summary.totals.shellsLaunched)}${metric('Castigos cumplidos', summary.totals.penaltiesCompleted)}</div>
      ${summary.totals.penaltiesManual ? `<p class="weekly-coverage">Además, ${summary.totals.penaltiesManual} castigos marcados como cumplidos por administración.</p>` : ''}
      ${highlights.length ? `<div class="weekly-highlights">${highlights.join('')}</div>` : '<p class="weekly-empty">Todavía no hay actividad suficiente para elegir los destacados de esta semana.</p>'}
      ${winnerHtml()}${summary.clips.available ? `<p class="weekly-coverage">${summary.clips.posts} clips publicados · ${summary.clips.votes} likes en total.</p>` : ''}`;
  }

  function teamHtml() {
    const team = summary.teams.find(t => t.id === selectedTeam);
    if (!team) return '<p class="weekly-empty">No hay equipos registrados en este resumen.</p>';
    const roles = {TOP:'Top',JUNGLE:'Jungla',MIDDLE:'Mid',BOTTOM:'ADC',UTILITY:'Support'};
    const players = team.players.map(player => {
      const elo = player.elo;
      const delta = elo.delta == null ? 'Sin datos suficientes para comparar' : `${elo.delta > 0 ? '+' : ''}${elo.delta} LP observados${elo.partial ? ' · Registro parcial' : ''}`;
      return `<article class="weekly-card"><h3>${escape(player.name)}</h3><p>${escape(player.riotId)}</p>
        <p>Inicio: ${escape(rank(elo.start))}</p><p>Final: ${escape(rank(elo.end))}</p>
        <p class="weekly-delta ${elo.delta < 0 ? 'is-negative' : ''}">${escape(delta)}</p>
        <p>${elo.start ? `Inicio observado: ${escape(date(elo.start.observedAt, true))}` : ''}${elo.end ? `<br>Final observado: ${escape(date(elo.end.observedAt, true))}` : ''}</p>
        <p>KDA: ${escape(kda(player.totals, player.kda))} · ${player.games} partidas con estadísticas</p>
        <p>Rol principal: ${escape(roles[player.mainRole] || 'Sin configurar')}<br>Más jugado: ${escape(player.favorite ? `${championDisplayName(player.favorite.name)} (${player.favorite.games})` : '—')}</p></article>`;
    }).join('');
    const p = team.penalties, s = team.shells;
    const best = team.bestMatch;
    return `<div class="weekly-metrics">${metric('Partidas del equipo', team.games)}${metric('Victorias / derrotas', `${team.wins} / ${team.losses}`)}${metric('KDA combinado', kda(team.totals, team.kda))}</div>
      <p class="weekly-coverage">Winrate: ${team.winrate ?? '—'}% · Mejor racha de la semana: ${team.bestStreak} victorias.<br>Estadísticas de ambos disponibles en ${team.detailGames} de ${team.games} partidas.</p>
      <div class="weekly-players">${players}</div><div class="weekly-team-details">
      <article class="weekly-card"><span>⚡ Castigos</span><ul><li>${p.received} recibidos esta semana</li><li>${p.completed} cumplidos automáticamente</li><li>${p.manual} marcados por administración</li><li>${p.pending} pendientes ${summary.status === 'CURRENT' ? 'actualmente' : 'al cierre'}</li></ul></article>
      <article class="weekly-card"><span>🐢 Pepazos</span><ul><li>${s.launched} lanzados · ${s.received} recibidos · ${s.returned} devueltos</li><li>${s.achievements} logros por partidas</li>${s.creditUnknown ? '' : `<li>${s.credited} añadidos al inventario · ${s.blocked} sin sumar por el límite</li>`}<li>+${s.clipPrize} por el premio de clips</li></ul></article>
      </div>${best ? `<article class="weekly-card" style="margin-top:1rem"><span>🏅 Mejor partida del dúo</span><h3>${best.totals.kills} / ${best.totals.deaths} / ${best.totals.assists} · KDA ${escape(kda(best.totals, best.kda))}</h3><p>${escape(best.champions.map(championDisplayName).join(' + '))} · ${escape(date(best.at, true))}</p></article>` : ''}`;
  }

  function renderContent() {
    if (!summary) return;
    document.querySelectorAll('[data-weekly-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.weeklyView === view)));
    document.getElementById('weekly-team-label').hidden = view !== 'team';
    document.getElementById('weekly-content').innerHTML = view === 'team' ? teamHtml() : generalHtml();
  }

  function render(payload) {
    summary = payload.summary;
    selectedWeek = summary.week;
    const weekSelect = document.getElementById('weekly-week');
    weekSelect.replaceChildren(...payload.weeks.map(week => {
      const monday = new Date(`${week}T12:00:00Z`).getTime() / 1000;
      return new Option(`${date(monday)}${week === (payload.currentWeek || payload.weeks[0]) ? ' · En curso' : week > (payload.currentWeek || payload.weeks[0]) ? ' · Próximamente' : ''}`, week);
    }));
    weekSelect.value = selectedWeek;
    weekSelect.disabled = false;
    const teamSelect = document.getElementById('weekly-team');
    teamSelect.replaceChildren(...summary.teams.map(team => new Option(team.name, team.id)));
    if (!summary.teams.some(t => t.id === selectedTeam)) selectedTeam = summary.teams[0]?.id || '';
    teamSelect.value = selectedTeam;
    document.getElementById('weekly-period').textContent = period(summary);
    document.getElementById('weekly-state').textContent = summary.status === 'CURRENT' ? 'Semana en curso' : summary.status === 'UPCOMING' ? 'Próximamente' : 'Semana cerrada';
    document.getElementById('weekly-footer').textContent = summary.status === 'CURRENT'
      ? 'De lunes a domingo · Horario de Madrid. Nuevo resumen cada lunes.'
      : summary.status === 'UPCOMING' ? 'El resumen comenzará con el torneo · Horario de Madrid.'
      : 'Resumen de una semana anterior · Horario de Madrid.';
    document.getElementById('weekly-report').hidden = false;
    renderContent();
    updateUrl();
  }

  async function load() {
    const version = ++requestVersion;
    const status = document.getElementById('weekly-status');
    try {
      let payload;
      try {payload = await DataStore.getWeeklySummary(selectedWeek);}
      catch (error) {
        if (error.status !== 404 || !selectedWeek) throw error;
        payload = await DataStore.getWeeklySummary();
        followLatest = true;
      }
      if (followLatest && payload.weeks.length > 1 && payload.summary.week !== payload.weeks[1]) payload = await DataStore.getWeeklySummary(payload.weeks[1]);
      if (version !== requestVersion) return;
      const next = JSON.stringify(payload);
      if (signature !== next) {signature = next; render(payload);}
      status.textContent = '';
      status.classList.remove('is-error');
    } catch (_) {
      if (version !== requestVersion) return;
      status.textContent = 'No se pudo cargar el resumen. Volveremos a intentarlo; puedes refrescar la página.';
      status.classList.add('is-error');
      if (summary) document.getElementById('weekly-week').value = summary.week;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('weekly-week').addEventListener('change', event => {selectedWeek = event.target.value; followLatest = false; load();});
    document.getElementById('weekly-team').addEventListener('change', event => {selectedTeam = event.target.value; renderContent(); updateUrl();});
    document.querySelectorAll('[data-weekly-view]').forEach(button => button.addEventListener('click', () => {view = button.dataset.weeklyView; renderContent(); updateUrl();}));
    document.getElementById('weekly-content').addEventListener('click', event => {
      const button = event.target.closest('[data-weekly-clip]');
      if (!button) return;
      const frame = document.createElement('iframe');
      const embed = new URL('https://clips.twitch.tv/embed');
      embed.searchParams.set('clip', new URL(button.dataset.weeklyClip).pathname.slice(1));
      embed.searchParams.set('parent', location.hostname);
      embed.searchParams.set('autoplay', 'false');
      frame.src = embed.href;
      frame.title = 'Clip ganador de la semana';
      frame.className = 'weekly-embed';
      frame.allowFullscreen = true;
      document.getElementById('weekly-clip-embed').replaceChildren(frame);
      button.disabled = true;
    });
    load();
    async function poll() {try {if (!document.hidden) await load();} finally {setTimeout(poll, 60000);}}
    setTimeout(poll, 60000);
  });
})();
