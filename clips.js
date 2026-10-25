/* Shared weekly clips and votes; watched selections stay in this browser. */
(() => {
  let clips = [];
  const opened = new Set();
  let ready = false;
  let busy = false;
  let requestVersion = 0;
  let sort = 'votes';
  let teamFilter = '';
  let searchText = '';
  let clipOrder = [];
  const PAGE_SIZE = 15;
  const SEEN_KEY = 'pepes_clips_seen';
  let currentPage = 1;
  let currentWeek = '';
  let selectedWeek = new URLSearchParams(location.search).get('week') || '';
  let loadingWeek = false;
  let latestWeek = '';
  const weekSelect = document.getElementById('clips-week-select');
  let weekClosed = false;
  let availableTeams = [];
  let voting = null;
  let seen = new Set();
  const commentStates = new Map();
  let moderationPin = '';
  const moderationForm = document.getElementById('clips-moderation');
  if (moderationForm) moderationForm.hidden = new URLSearchParams(location.search).get('moderate') !== '1';

  function commentState(id, week = currentWeek) {
    const key = `${week}:${id}`;
    if (!commentStates.has(key)) commentStates.set(key, {open:false, loaded:false, loading:false, sending:false,
      comments:[], total:0, hasMore:false, name:'', text:'', error:'', notice:''});
    return commentStates.get(key);
  }

  function sessionToken() {
    try { return sessionStorage.getItem('pepes_player_token') || ''; }
    catch (_) { return ''; }
  }

  function readSeen(week) {
    try {
      const saved = JSON.parse(localStorage.getItem(SEEN_KEY) || 'null');
      const ids = saved?.byWeek?.[week] || (saved?.week === week ? saved.ids : []);
      return new Set(Array.isArray(ids) ? ids.filter(id => typeof id === 'string') : []);
    } catch (_) { return new Set(); }
  }

  function saveSeen() {
    try {
      const saved = JSON.parse(localStorage.getItem(SEEN_KEY) || 'null');
      const byWeek = {...saved?.byWeek};
      if (saved?.week && Array.isArray(saved.ids)) byWeek[saved.week] = saved.ids;
      byWeek[currentWeek] = [...seen];
      localStorage.setItem(SEEN_KEY, JSON.stringify({week: currentWeek, ids: [...seen], byWeek}));
      return true;
    } catch (_) { return false; }
  }
  const feed = document.getElementById('clips-feed');
  const form = document.getElementById('clips-form');
  const publish = document.getElementById('clips-publish');
  const feedback = document.getElementById('clips-feedback');
  const error = document.getElementById('clips-form-error');
  const searchInput = document.getElementById('clips-search');
  const teamSelect = document.getElementById('clips-team-filter');
  const clearFilters = document.getElementById('clips-clear-filters');
  const escape = value => String(value).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[ch]));

  const searchable = value => String(value ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('es').trim();

  function clipTeamKey(clip) {
    if (clip.teamId) return `id:${clip.teamId}`;
    // Older clips may only store the name, including teams no longer in the roster.
    const name = searchable(clip.team || 'Comunidad');
    const team = availableTeams.find(item => searchable(item.name) === name);
    return team ? `id:${team.id}` : `name:${name}`;
  }

  function renderTeamFilter() {
    const options = new Map(availableTeams.map(team => [`id:${team.id}`, team.name]));
    for (const clip of clips) {
      const key = clipTeamKey(clip);
      if (!options.has(key)) options.set(key, clip.team || 'Comunidad');
    }
    // Preserve an explicit filter when moving to a week without clips from that team.
    if (teamFilter && !options.has(teamFilter)) options.set(teamFilter, teamSelect.selectedOptions[0]?.textContent || 'Equipo seleccionado');
    const choices = [...options].sort((a, b) => a[1].localeCompare(b[1], 'es'));
    const signature = JSON.stringify(choices);
    if (teamSelect.dataset.signature !== signature) {
      teamSelect.replaceChildren(new Option('Todos los equipos', ''), ...choices.map(([id, name]) => new Option(name, id)));
      teamSelect.dataset.signature = signature;
    }
    teamSelect.value = teamFilter;
  }

  function resetFilters() {
    teamFilter = '';
    searchText = '';
    teamSelect.value = '';
    searchInput.value = '';
    currentPage = 1;
  }

  function parseClip(value) {
    try {
      const url = new URL(value.trim());
      if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
      const host = url.hostname.toLowerCase();
      const parts = url.pathname.split('/').filter(Boolean);
      let slug = '';
      if (host === 'clips.twitch.tv' && parts.length === 1) slug = parts[0];
      else if (['twitch.tv', 'www.twitch.tv'].includes(host) && parts.length === 3 && parts[1] === 'clip') slug = parts[2];
      if (!/^[A-Za-z0-9_-]+$/.test(slug) || slug === 'embed') return null;
      return {slug, url: `https://clips.twitch.tv/${slug}`};
    } catch (_) { return null; }
  }

  function age(timestamp) {
    const minutes = Math.max(0, Math.floor((Date.now() / 1000 - timestamp) / 60));
    if (minutes < 1) return 'ahora';
    if (minutes < 60) return `hace ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `hace ${hours} ${hours === 1 ? 'hora' : 'horas'}`;
    const days = Math.floor(hours / 24);
    return `hace ${days} ${days === 1 ? 'día' : 'días'}`;
  }

  function updateOrder(reset = false) {
    const ranked = [...clips].sort((a, b) =>
      (sort === 'votes' ? b.votes - a.votes : 0) || b.createdAt - a.createdAt || a.id.localeCompare(b.id));
    const ids = new Set(ranked.map(clip => clip.id));
    if (reset) {
      clipOrder = ranked.map(clip => clip.id);
    } else {
      // Counts can change while watching. Keep existing positions and append arrivals.
      clipOrder = clipOrder.filter(id => ids.has(id));
      const known = new Set(clipOrder);
      clipOrder.push(...ranked.filter(clip => !known.has(clip.id)).map(clip => clip.id));
    }
  }

  function render() {
    const byId = new Map(clips.map(clip => [clip.id, clip]));
    const terms = searchable(searchText).split(/\s+/).filter(Boolean);
    const filtering = !!teamFilter || terms.length > 0;
    const matching = clipOrder.map(id => byId.get(id)).filter(clip => clip &&
      (!teamFilter || clipTeamKey(clip) === teamFilter) &&
      terms.every(term => searchable(`${clip.title} ${clip.team || 'Comunidad'}`).includes(term)));
    const ordered = matching.filter(clip => sort !== 'unseen' || !seen.has(clip.id));
    const pages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
    currentPage = Math.max(1, Math.min(currentPage, pages));
    const offset = (currentPage - 1) * PAGE_SIZE;
    const visible = ordered.slice(offset, offset + PAGE_SIZE);
    document.querySelectorAll('[data-clips-pagination]').forEach(nav => {
      nav.hidden = pages <= 1;
      nav.querySelector('[data-clips-page="previous"]').disabled = currentPage === 1;
      nav.querySelector('[data-clips-page="next"]').disabled = currentPage === pages;
      nav.querySelector('[data-clips-page-info]').textContent = `Página ${currentPage} de ${pages} · ${offset + 1}–${Math.min(offset + PAGE_SIZE, ordered.length)} de ${ordered.length}`;
    });
    const existing = new Map([...feed.querySelectorAll('.clip-post')].map(post => [post.dataset.clipId, post]));
    if (!ordered.length) {
      const message = !clips.length ? 'Todavía no hay clips esta semana. ¡Comparte el primero!'
        : sort === 'unseen' && matching.length ? filtering ? '¡Estás al día! No quedan clips sin ver con estos filtros.' : '¡Estás al día! Ya has marcado todos los clips como vistos.'
        : 'No hay clips que coincidan con estos filtros. Prueba otra búsqueda o limpia los filtros.';
      feed.innerHTML = `<p class="clips-empty">${message}</p>`;
      opened.clear();
    } else {
      feed.querySelector('.clips-empty')?.remove();
      visible.forEach((clip, index) => {
        let post = existing.get(clip.id);
        if (!post) {
          post = document.createElement('article');
          post.className = 'clip-post';
          post.dataset.clipId = clip.id;
          post.innerHTML = `<div class="clip-vote"><button type="button" data-vote="${escape(clip.id)}"><i class="fa-solid fa-thumbs-up" aria-hidden="true"></i></button><strong></strong></div>
            <div class="clip-body"><div class="clip-header"><h2 class="clip-title">${escape(clip.title)}</h2><button type="button" class="clip-seen" data-seen="${escape(clip.id)}"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button></div><div class="clip-meta"><span class="clip-avatar">${escape(clip.initials)}</span><span class="clip-team">${escape(clip.team)}</span><span class="clip-age"></span></div>
            <div class="clip-media clip-scene-${clip.scene}" data-media="${escape(clip.id)}"><button type="button" class="clip-poster" data-play="${escape(clip.id)}" aria-label="${clip.slug ? 'Reproducir' : 'Ver disponibilidad de'} ${escape(clip.title)}"><span class="clip-terrain"></span><span class="clip-characters"></span>${clip.slug ? '<span class="clip-example-badge">CLIP DE TWITCH</span>' : ''}<span class="clip-play"><i class="fa-solid fa-play" aria-hidden="true"></i></span>${clip.duration ? `<span class="clip-duration">${clip.duration}</span>` : ''}</button></div>
            <div class="clip-footer"><span class="clip-source"><i class="fa-brands fa-twitch" aria-hidden="true"></i> Twitch</span>${clip.url ? `<a class="clip-open" href="${escape(clip.url)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i> Abrir clip</a>` : ''}${clip.example ? '' : `<button type="button" class="clip-comments-toggle" data-comments-toggle="${escape(clip.id)}" aria-expanded="false" aria-controls="clip-comments-${escape(clip.id)}"><i class="fa-regular fa-comment" aria-hidden="true"></i><span></span></button>`}</div>
            ${clip.example ? '' : `<section class="clip-comments" id="clip-comments-${escape(clip.id)}" aria-label="Comentarios de ${escape(clip.title)}" hidden>
              <h3>Comentarios</h3><ol class="clip-comments-list" data-comment-list></ol>
              <button type="button" class="clips-secondary clip-comments-more" data-comments-more="${escape(clip.id)}" hidden>Ver más comentarios</button>
              <form class="clip-comment-form" data-comment-form="${escape(clip.id)}">
                <label for="comment-name-${escape(clip.id)}">Nombre <span>(opcional)</span></label>
                <input id="comment-name-${escape(clip.id)}" name="name" type="text" maxlength="15" autocomplete="nickname" placeholder="Anónimo" aria-describedby="comment-name-note-${escape(clip.id)}">
                <small id="comment-name-note-${escape(clip.id)}">Máximo 15 caracteres · Nombre sin verificar</small>
                <label for="comment-text-${escape(clip.id)}">Tu comentario</label>
                <textarea id="comment-text-${escape(clip.id)}" name="text" maxlength="200" rows="3" required placeholder="¿Qué te ha parecido la jugada?" aria-describedby="comment-counter-${escape(clip.id)}"></textarea>
                <div class="clip-comment-actions"><small id="comment-counter-${escape(clip.id)}" data-comment-counter>0/200</small><button type="submit" class="clips-publish">Comentar</button></div>
              </form><p class="clip-comment-feedback" data-comment-feedback role="status" aria-live="polite"></p>
            </section>`}</div>`;
        }
        const viewed = seen.has(clip.id);
        let seenLabel = post.querySelector('.clip-seen-label');
        if (!seenLabel) {
          seenLabel = document.createElement('span');
          seenLabel.className = 'clip-seen-label';
          seenLabel.textContent = '✓ Visto';
          post.querySelector('.clip-meta').append(seenLabel);
        }
        seenLabel.hidden = !viewed;
        let deleteButton = post.querySelector('[data-delete-clip]');
        if (clip.canDelete && !deleteButton) {
          deleteButton = document.createElement('button');
          deleteButton.type = 'button';
          deleteButton.className = 'clip-delete';
          deleteButton.dataset.deleteClip = clip.id;
          deleteButton.textContent = '🗑 Borrar';
          post.querySelector('.clip-footer').append(deleteButton);
        }
        if (deleteButton) {
          deleteButton.hidden = !clip.canDelete;
          deleteButton.disabled = busy || loadingWeek;
          deleteButton.setAttribute('aria-label', `Borrar clip: ${clip.title}`);
        }
        const seenButton = post.querySelector('[data-seen]');
        seenButton.setAttribute('aria-pressed', viewed);
        seenButton.setAttribute('aria-label', `${viewed ? 'Marcar como no visto' : 'Marcar como visto'}: ${clip.title}`);
        seenButton.title = viewed ? 'Visto · pulsa para marcar como no visto' : 'Marcar como visto';
        const vote = post.querySelector('[data-vote]');
        vote.setAttribute('aria-pressed', clip.liked);
        vote.setAttribute('aria-label', `${clip.liked ? 'Retirar like de' : 'Dar like a'} ${clip.title}`);
        vote.title = weekClosed ? 'Semana cerrada: solo consulta' : !voting ? 'Inicia sesión con tu equipo para votar' : clip.liked ? 'Retirar mi like' : 'Dar like';
        vote.disabled = busy || loadingWeek || weekClosed || !voting;
        post.querySelector('.clip-vote strong').textContent = clip.votes;
        post.querySelector('.clip-age').textContent = `· ${age(clip.createdAt)}`;
        renderComments(post, clip);
        if (feed.children[index] !== post) feed.insertBefore(post, feed.children[index] || null);
        existing.delete(clip.id);
      });
      for (const [id, post] of existing) { post.remove(); opened.delete(id); }
    }
    const count = filtering ? `${matching.length} de ${clips.length} clips` : `${clips.length} clips`;
    document.getElementById('clips-count').textContent = sort === 'unseen' ? `${ordered.length} no vistos · ${count}` : count;
    searchInput.disabled = teamSelect.disabled = !ready || loadingWeek;
    clearFilters.hidden = !teamFilter && !searchText;
    clearFilters.disabled = !ready || loadingWeek;
    weekSelect.disabled = !ready || busy || loadingWeek;
    publish.disabled = !ready || busy || weekClosed || loadingWeek || !availableTeams.length;
    form.querySelector('button[type="submit"]').disabled = !ready || busy || weekClosed || !availableTeams.length;
    if (moderationForm) {
      moderationForm.querySelector('[type="submit"]').disabled = busy || loadingWeek;
      document.getElementById('clips-moderation-end').disabled = busy || loadingWeek;
    }
  }

  async function request(path, data) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const token = sessionToken();
      const response = await fetch(`${API_BASE_URL}${path}`, {
        credentials: 'same-origin', signal: controller.signal,
        headers: {...(token ? {Authorization: `Bearer ${token}`} : {}), ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
        ...(data === undefined ? {} : {method: 'POST', body: JSON.stringify(data)})
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401 && path === '/clips/like') { setVoting(null); render(); }
        throw new Error(result.error || 'No se pudo guardar el cambio.');
      }
      return result;
    } finally { clearTimeout(timeout); }
  }

  function renderComments(post, clip) {
    const toggle = post.querySelector('[data-comments-toggle]');
    if (!toggle) return;
    const state = commentState(clip.id);
    toggle.querySelector('span').textContent = `Comentarios (${Math.max(Number(clip.commentCount) || 0, state.total)})`;
    toggle.setAttribute('aria-expanded', String(state.open));
    const section = post.querySelector('.clip-comments');
    section.hidden = !state.open;
    const list = section.querySelector('[data-comment-list]');
    const signature = JSON.stringify([state.comments, state.loaded, state.loading]);
    if (list.dataset.signature !== signature) {
      list.innerHTML = state.comments.length ? state.comments.map(c => `<li class="clip-comment"><header><strong>${escape(c.name || 'Anónimo')}</strong><time>${escape(age(c.createdAt))}</time></header><p>${escape(c.text)}</p></li>`).join('')
        : `<li class="clip-comments-empty">${state.loading ? 'Cargando comentarios…' : state.loaded ? 'Aún no hay comentarios. ¡Escribe el primero!' : 'Abre los comentarios para cargarlos.'}</li>`;
      list.dataset.signature = signature;
    }
    const more = section.querySelector('[data-comments-more]');
    more.hidden = !state.hasMore;
    more.disabled = state.loading;
    const commentForm = section.querySelector('[data-comment-form]');
    if (commentForm.elements.name.value !== state.name) commentForm.elements.name.value = state.name;
    if (commentForm.elements.text.value !== state.text) commentForm.elements.text.value = state.text;
    for (const field of commentForm.elements) field.disabled = state.sending || loadingWeek;
    commentForm.querySelector('[type="submit"]').textContent = state.sending ? 'Enviando…' : 'Comentar';
    section.querySelector('[data-comment-counter]').textContent = `${Array.from(state.text).length}/200`;
    const message = section.querySelector('[data-comment-feedback]');
    message.textContent = state.error || state.notice;
    message.classList.toggle('is-error', !!state.error);
  }

  async function loadComments(id, more = false) {
    const week = currentWeek;
    const state = commentState(id, week);
    if (state.loading || state.sending) return;
    const version = state.version = (state.version || 0) + 1;
    state.loading = true;
    state.error = '';
    render();
    try {
      const query = new URLSearchParams({week,clipId:id,offset:String(more ? state.comments.length : 0),limit:'10'});
      const result = await request(`/clips/comments?${query}`);
      if (version !== state.version) return;
      if (result.week !== week || result.clipId !== id || !Array.isArray(result.comments)) throw new Error('Respuesta de comentarios inválida.');
      state.comments = more ? [...new Map([...state.comments,...result.comments].map(c=>[c.id,c])).values()] : result.comments;
      state.total = result.total;
      state.hasMore = result.hasMore;
      state.loaded = true;
      if (currentWeek === week) {
        const clip = clips.find(c=>c.id===id);
        if (clip) clip.commentCount = result.total;
      }
    } catch (failure) {
      if (version === state.version) state.error = ['AbortError','TypeError'].includes(failure.name)
        ? 'No se pudieron cargar los comentarios. Cierra y abre el apartado para reintentar.' : failure.message;
    }
    finally { if (version === state.version) { state.loading = false; if (currentWeek === week) render(); } }
  }

  function setVoting(value) {
    voting = value?.teamId ? value : null;
    document.getElementById('clips-voting-status').textContent = voting
      ? `Votando como ${voting.teamName}.`
      : 'Inicia sesión con tu equipo para dar likes. Puedes ver clips y marcarlos como vistos sin entrar.';
    document.getElementById('clips-login').hidden = !!voting;
  }

  function apply(result, reorder = false) {
    if (!Array.isArray(result.clips) || !/^\d{4}-\d{2}-\d{2}$/.test(result.week)) throw new Error('Respuesta de clips inválida.');
    reorder = reorder || !ready || currentWeek !== result.week;
    clips = result.clips.map(clip => ({...clip, slug: clip.slug || parseClip(clip.url || '')?.slug || ''}));
    setVoting(result.voting);
    weekClosed = result.archived === true || result.weeklyReward?.closed === true;
    const formatDate = value => new Intl.DateTimeFormat('es-ES', {day:'numeric',month:'short',timeZone:'Europe/Madrid'}).format(new Date(value * 1000));
    const weeks = Array.isArray(result.weeks) ? result.weeks : [{week:result.week}];
    const signature = JSON.stringify(weeks);
    if (weekSelect.dataset.signature !== signature) {
      weekSelect.replaceChildren(...weeks.map(item => new Option(
        item.startsAt && item.endsAt ? `${formatDate(item.startsAt)} — ${formatDate(item.endsAt - 1)}${item.archived ? ' · Archivada' : ' · Actual'}` : item.week,
        item.week)));
      weekSelect.dataset.signature = signature;
    }
    latestWeek = result.currentWeek || result.week;
    weekSelect.value = result.week;
    document.getElementById('clips-archive-status').textContent = result.archived
      ? 'Semana archivada: puedes ver los clips y sus likes finales. No admite votos ni publicaciones y no participa en el premio actual.'
      : 'Ronda actual: los clips y sus likes participan hasta el cierre.';
    if (weekClosed) { form.hidden = true; publish.setAttribute('aria-expanded','false'); }
    const closesAt = result.weeklyReward?.closesAt;
    document.getElementById('clips-close-label').textContent = closesAt
      ? new Intl.DateTimeFormat('es-ES',{weekday:'long',day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'}).format(new Date(closesAt * 1000))
      : 'domingo a las 23:59';
    const teams = Array.isArray(result.teams) ? result.teams : [];
    if (JSON.stringify(availableTeams) !== JSON.stringify(teams)) {
      availableTeams = teams;
      const select = document.getElementById('clip-team');
      const selected = select.value;
      select.replaceChildren(new Option('Selecciona un equipo', ''), ...teams.map(team => new Option(team.name, team.id)));
      if (teams.some(team => team.id === selected)) select.value = selected;
    }
    renderTeamFilter();
    const award = result.weeklyReward?.award;
    document.getElementById('clips-reward-status').textContent = weekClosed
      ? award?.status === 'AWARDED' ? `🏆 ${award.teamName} ha ganado +${award.shells} ${award.shells === 1 ? 'pepazo' : 'pepazos'} por «${award.title}» (${award.votes} likes).`
        : 'Votación cerrada. Esta semana no hay un clip con likes y equipo válido para recibir el premio.'
      : 'La votación está abierta. El premio se entrega automáticamente al cerrar.';
    const previous = result.weeklyReward?.previousAward;
    const previousMessage = document.getElementById('clips-previous-reward');
    previousMessage.hidden = !previous;
    previousMessage.textContent = previous ? previous.status === 'AWARDED'
      ? `Último ganador: ${previous.teamName} · «${previous.title}» · +${previous.shells} ${previous.shells === 1 ? 'pepazo' : 'pepazos'}.`
      : 'La semana anterior terminó sin premio.' : '';
    if (currentWeek !== result.week) {
      currentWeek = result.week;
      currentPage = 1;
      seen = readSeen(currentWeek);
    }
    // Only keep marks for clips still in the current weekly board.
    const currentIds = new Set(clips.map(clip => clip.id));
    const pruned = new Set([...seen].filter(id => currentIds.has(id)));
    if (pruned.size !== seen.size) { seen = pruned; saveSeen(); }
    updateOrder(reorder);
    ready = true;
    const start = result.startsAt || new Date(`${result.week}T12:00:00Z`).getTime()/1000;
    const end = result.endsAt || start + 7*86400;
    document.getElementById('clips-week').textContent = `${formatDate(start)} — ${formatDate(end - 1)}`;
    document.getElementById('clips-year').textContent = `${new Date(start*1000).getFullYear()} · Hora de Madrid`;
    document.querySelector('.clips-preview-note span').textContent = 'Clips y likes compartidos.';
    render();
    for (const clip of clips) {
      const state = commentStates.get(`${currentWeek}:${clip.id}`);
      if (state?.open && state.loaded && !state.loading && !state.sending && !state.error && Number(clip.commentCount) > state.total) void loadComments(clip.id);
    }
  }

  async function refresh(forWeekChange = false) {
    if (document.hidden || busy || (loadingWeek && forWeekChange !== true)) return false;
    const version = ++requestVersion;
    try {
      const result = moderationPin
        ? await request('/clips/moderate', {authPin: moderationPin, ...(selectedWeek ? {week: selectedWeek} : {})})
        : await request(`/clips${selectedWeek ? '?week=' + encodeURIComponent(selectedWeek) : ''}`);
      if (version !== requestVersion || busy) return false;
      apply(result);
      return true;
    } catch (failure) {
      if (version === requestVersion) {
        feedback.textContent = failure.message.includes('Semana de clips no encontrada') ? 'La semana solicitada no está disponible. Se muestra la actual.' : 'No se pudieron actualizar los clips. Se reintentará en unos segundos.';
        if (failure.message.includes('Semana de clips no encontrada')) selectedWeek = '';
      }
      return false;
    }
  }

  function openMedia(clip) {
    const media = feed.querySelector(`[data-media="${clip.id}"]`);
    if (clip.slug) {
      if (media.clientWidth < 400) {
        media.innerHTML = `<div class="clip-mobile-player"><strong>Ver el clip en Twitch</strong><span>El reproductor necesita más espacio.</span><a href="${escape(clip.url)}" target="_blank" rel="noopener noreferrer">Abrir clip ↗</a></div>`;
        return;
      }
      const frame = document.createElement('iframe');
      const source = new URL('https://clips.twitch.tv/embed');
      source.searchParams.set('clip', clip.slug);
      source.searchParams.set('parent', window.location.hostname);
      source.searchParams.set('autoplay', 'false');
      frame.src = source.href;
      frame.className = 'clip-twitch-frame';
      frame.title = clip.title;
      frame.allowFullscreen = true;
      media.classList.add('has-twitch');
      media.replaceChildren(frame);
    } else {
      media.innerHTML = `<button type="button" class="clip-poster" data-play="${clip.id}" aria-label="Volver al clip"><span class="clip-example-player"><i class="fa-brands fa-twitch" aria-hidden="true"></i><strong>Clip no disponible</strong><span>Esta publicación no tiene un enlace de Twitch. Pulsa para volver.</span></span></button>`;
    }
  }

  function toggleForm(show) {
    form.hidden = !show;
    publish.setAttribute('aria-expanded', show);
    if (show) document.getElementById('clip-url').focus();
    else publish.focus();
  }
  publish.addEventListener('click', () => toggleForm(form.hidden));
  document.getElementById('clips-cancel').addEventListener('click', () => toggleForm(false));
  searchInput.addEventListener('input', () => {
    searchText = searchInput.value;
    currentPage = 1;
    render();
  });
  teamSelect.addEventListener('change', () => {
    teamFilter = teamSelect.value;
    currentPage = 1;
    render();
  });
  clearFilters.addEventListener('click', () => {
    resetFilters();
    render();
    searchInput.focus({preventScroll: true});
  });
  document.querySelectorAll('[data-clips-sort]').forEach(button => button.addEventListener('click', () => {
    sort = button.dataset.clipsSort;
    currentPage = 1;
    updateOrder(true);
    document.querySelectorAll('[data-clips-sort]').forEach(item => item.setAttribute('aria-pressed', item === button));
    render();
  }));
  document.querySelectorAll('[data-clips-page]').forEach(button => button.addEventListener('click', () => {
    currentPage += button.dataset.clipsPage === 'next' ? 1 : -1;
    render();
    document.querySelector('.clips-toolbar').scrollIntoView({block: 'start'});
    const equivalent = document.querySelector(`[data-clips-pagination] [data-clips-page="${button.dataset.clipsPage}"]`);
    if (equivalent && !equivalent.disabled) equivalent.focus({preventScroll: true});
    else document.querySelector('[data-clips-page-info]').focus({preventScroll: true});
  }));
  window.addEventListener('storage', event => {
    if ((event.key === SEEN_KEY || event.key === null) && ready) {
      seen = readSeen(currentWeek);
      render();
    }
  });
  feed.addEventListener('click', async event => {
    const deleteButton = event.target.closest('[data-delete-clip]');
    if (deleteButton) {
      if (busy || loadingWeek) return;
      const id = deleteButton.dataset.deleteClip;
      const clip = clips.find(item => item.id === id);
      if (!clip?.canDelete || !window.confirm(`¿Borrar «${clip.title}»? Se retirarán también sus comentarios y likes. Los premios ya concedidos no cambian.`)) return;
      busy = true;
      ++requestVersion;
      render();
      try {
        const result = await request('/clips/delete', {clipId: id, week: currentWeek, ...(moderationPin ? {authPin: moderationPin} : {})});
        opened.delete(id);
        commentStates.delete(`${currentWeek}:${id}`);
        apply(result);
        feedback.textContent = 'Clip eliminado del listado.';
        document.querySelector('[data-clips-sort]')?.focus({preventScroll: true});
      } catch (failure) {
        feedback.textContent = failure.message;
      } finally { busy = false; render(); }
      return;
    }
    const commentsToggle = event.target.closest('[data-comments-toggle]');
    if (commentsToggle) {
      const id = commentsToggle.dataset.commentsToggle;
      const state = commentState(id);
      state.open = !state.open;
      render();
      if (state.open) await loadComments(id);
      return;
    }
    const commentsMore = event.target.closest('[data-comments-more]');
    if (commentsMore) { await loadComments(commentsMore.dataset.commentsMore, true); return; }
    const seenButton = event.target.closest('[data-seen]');
    if (seenButton) {
      const id = seenButton.dataset.seen;
      if (!clips.some(clip => clip.id === id)) return;
      if (seen.has(id)) seen.delete(id);
      else seen.add(id);
      const saved = saveSeen();
      feedback.textContent = saved ? (seen.has(id) ? 'Clip marcado como visto en este navegador.' : 'Clip marcado como no visto.')
        : 'Marca actualizada en esta pestaña. El navegador no permite guardarla para próximas visitas.';
      const index = [...feed.querySelectorAll('[data-seen]')].indexOf(seenButton);
      render();
      const remaining = [...feed.querySelectorAll('[data-seen]')];
      (feed.querySelector(`[data-seen="${id}"]`) || remaining[Math.min(index, remaining.length - 1)] || document.querySelector('[data-clips-sort="unseen"]')).focus({preventScroll: true});
      return;
    }
    const vote = event.target.closest('[data-vote]');
    if (vote) {
      if (busy || loadingWeek || weekClosed || !voting) return;
      const id = vote.dataset.vote;
      const clip = clips.find(item => item.id === id);
      if (!clip) return;
      const liked = !clip.liked;
      busy = true;
      ++requestVersion;
      render();
      try {
        const result = await request('/clips/like', {clipId: id, liked, week: currentWeek});
        apply(result);
        feedback.textContent = liked ? 'Like guardado.' : 'Like retirado.';
      } catch (failure) {
        feedback.textContent = failure.message;
      } finally {
        busy = false;
        render();
        const target = feed.querySelector(`[data-vote="${id}"]`);
        if (voting && target && !target.disabled) target.focus({preventScroll: true});
      }
      return;
    }
    const play = event.target.closest('[data-play]');
    if (play) {
      const clip = clips.find(item => item.id === play.dataset.play);
      if (!clip) return;
      if (opened.has(clip.id)) {
        opened.delete(clip.id);
        const post = play.closest('.clip-post');
        post.remove();
        render();
      } else {
        opened.add(clip.id);
        openMedia(clip);
      }
    }
  });
  feed.addEventListener('input', event => {
    const commentForm = event.target.closest('[data-comment-form]');
    if (!commentForm) return;
    const state = commentState(commentForm.dataset.commentForm);
    state.name = commentForm.elements.name.value;
    state.text = commentForm.elements.text.value;
    commentForm.querySelector('[data-comment-counter]').textContent = `${Array.from(state.text).length}/200`;
  });
  feed.addEventListener('submit', async event => {
    const commentForm = event.target.closest('[data-comment-form]');
    if (!commentForm) return;
    event.preventDefault();
    const id = commentForm.dataset.commentForm, week = currentWeek;
    const state = commentState(id, week);
    if (state.sending || loadingWeek) return;
    const name = commentForm.elements.name.value.trim(), text = commentForm.elements.text.value.trim();
    state.name = commentForm.elements.name.value;
    state.text = commentForm.elements.text.value;
    state.error = ''; state.notice = '';
    if (Array.from(name).length > 15 || !text || Array.from(text).length > 200) {
      state.error = 'Nombre opcional: máximo 15 caracteres. Comentario: entre 1 y 200 caracteres.';
      render(); return;
    }
    const signature = JSON.stringify([name,text]);
    if (state.retrySignature !== signature) {
      state.requestId = window.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
      state.retrySignature = signature;
    }
    state.version = (state.version || 0) + 1;
    state.loading = false;
    state.sending = true;
    render();
    try {
      const result = await request('/clips/comments', {week,clipId:id,name,text,requestId:state.requestId});
      if (result.week !== week || result.clipId !== id || !Array.isArray(result.comments)) throw new Error('No se pudo confirmar el comentario. Vuelve a intentarlo.');
      state.comments = result.comments; state.total = result.total; state.hasMore = result.hasMore; state.loaded = true;
      state.text = ''; state.retrySignature = null; state.notice = 'Comentario publicado.';
      if (currentWeek === week) {
        const clip = clips.find(c=>c.id===id);
        if (clip) clip.commentCount = result.total;
      }
    } catch (failure) {
      state.error = ['AbortError','TypeError'].includes(failure.name)
        ? 'No se pudo confirmar el envío. Puedes reintentar sin perder el comentario.' : failure.message;
    }
    finally {
      state.sending = false;
      if (currentWeek === week) {
        render();
        if (commentForm.isConnected && state.open) commentForm.elements.text.focus({preventScroll:true});
      }
    }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || loadingWeek || !ready || weekClosed) return;
    error.hidden = true;
    const parsed = parseClip(document.getElementById('clip-url').value);
    const title = document.getElementById('clip-title').value.trim();
    const teamId = document.getElementById('clip-team').value;
    if (!parsed || !title || !availableTeams.some(team => team.id === teamId)) {
      error.textContent = 'Introduce un título, un enlace de Twitch válido y el equipo al que representa el clip.';
      error.hidden = false;
      return;
    }
    busy = true;
    ++requestVersion;
    render();
    try {
      const result = await request('/clips', {title, url: parsed.url, teamId, week: currentWeek});
      sort = 'recent';
      resetFilters();
      document.querySelectorAll('[data-clips-sort]').forEach(button => button.setAttribute('aria-pressed', button.dataset.clipsSort === sort));
      apply(result, true);
      const clip = clips.find(item => item.slug === parsed.slug);
      if (clip) { opened.add(clip.id); openMedia(clip); }
      form.reset();
      toggleForm(false);
      feedback.textContent = 'Clip publicado. Ya pueden verlo los demás visitantes.';
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally { busy = false; render(); }
  });

  weekSelect.addEventListener('change', async () => {
    const previousSelection = selectedWeek;
    selectedWeek = weekSelect.value === latestWeek ? '' : weekSelect.value;
    ++requestVersion;
    loadingWeek = true;
    render();
    feedback.textContent = 'Cargando semana…';
    try {
      if (!await refresh(true)) {
        selectedWeek = previousSelection;
        weekSelect.value = currentWeek;
        return;
      }
      const url = new URL(location.href);
      if (selectedWeek) url.searchParams.set('week', selectedWeek); else url.searchParams.delete('week');
      history.replaceState(null, '', url);
      feedback.textContent = '';
    } finally { loadingWeek = false; render(); }
  });

  publish.disabled = true;
  moderationForm?.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || loadingWeek) return;
    const input = document.getElementById('clips-admin-pin');
    const pin = input.value.trim();
    const status = document.getElementById('clips-moderation-status');
    busy = true;
    ++requestVersion;
    render();
    try {
      const result = await request('/clips/moderate', {authPin: pin, ...(selectedWeek ? {week: selectedWeek} : {})});
      moderationPin = pin; // In memory only; never in storage or URLs.
      input.value = '';
      apply(result);
      status.textContent = 'Moderación activa: puedes borrar cualquier clip, incluidos los antiguos.';
      document.getElementById('clips-moderation-end').hidden = false;
    } catch (failure) { status.textContent = failure.message; }
    finally { busy = false; render(); }
  });
  document.getElementById('clips-moderation-end')?.addEventListener('click', () => {
    moderationPin = '';
    ++requestVersion;
    for (const clip of clips) clip.canDelete = false;
    render();
    document.getElementById('clips-moderation-status').textContent = 'Moderación desactivada.';
    document.getElementById('clips-moderation-end').hidden = true;
    refresh();
  });
  form.querySelector('button[type="submit"]').disabled = true;
  feed.innerHTML = '<p class="clips-empty">Cargando clips…</p>';
  async function poll() {
    try { await refresh(); } finally { setTimeout(poll, 5000); }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
  document.addEventListener('player-session-changed', refresh);
  document.addEventListener('player-session-ended', () => { setVoting(null); render(); });
  poll();
})();
