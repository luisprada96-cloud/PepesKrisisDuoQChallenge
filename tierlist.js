/* Permanent public tierlists; drafts are local, publication limits are server-owned. */
(() => {
  const TIERS = ['S', 'A', 'B', 'C', 'D'];
  const PAGE_SIZE = 6;
  let kind = new URLSearchParams(location.search).get('tipo') === 'integrantes' ? 'players' : 'teams';
  const draftKey = () => kind === 'teams' ? 'pepes_tierlist_draft_v1' : 'pepes_tierlist_players_draft_v1';
  const noun = () => kind === 'players' ? 'integrante' : 'equipo';
  let items = [], posts = [], total = 0, page = 1, selected = '', ready = false, busy = false, view = 'gallery', loadVersion = 0;
  let publishing = {canPublish: false, message: 'Inicia sesión con tu equipo para publicar.'};
  let tiers = Object.fromEntries(TIERS.map(tier => [tier, []]));
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const token = () => { try { return sessionStorage.getItem('pepes_player_token') || ''; } catch (_) { return ''; } };
  const placed = () => TIERS.flatMap(tier => tiers[tier]);
  const pool = () => items.map(item => item.id).filter(id => !placed().includes(id));
  const itemFor = id => items.find(item => item.id === id);
  const feedback = message => { $('tierlist-feedback').textContent = message; };
  const error = message => { $('tierlist-form-error').textContent = message; $('tierlist-form-error').hidden = !message; };

  async function request(offset = 0, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const session = token();
      const response = await fetch(`${API_BASE_URL}/tierlists?kind=${kind}${body ? '' : `&offset=${offset}&limit=${PAGE_SIZE}`}`, {
        credentials: 'same-origin', signal: controller.signal,
        headers: {...(session ? {Authorization: `Bearer ${session}`} : {}), ...(body ? {'Content-Type':'application/json'} : {})},
        ...(body ? {method:'POST', body:JSON.stringify(body)} : {})
      });
      const result = await response.json();
      if (!response.ok) { const failure = new Error(result.error || 'No se pudo completar la acción.'); failure.status = response.status; throw failure; }
      return result;
    } finally { clearTimeout(timeout); }
  }

  function saveDraft() {
    try { localStorage.setItem(draftKey(), JSON.stringify({tiers, author: $('tierlist-author').value})); } catch (_) {}
  }
  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey()) || 'null');
      const used = new Set();
      for (const tier of TIERS) tiers[tier] = (Array.isArray(draft?.tiers?.[tier]) ? draft.tiers[tier] : []).filter(id => {
        if (!itemFor(id) || used.has(id)) return false;
        used.add(id); return true;
      });
      if (typeof draft?.author === 'string') $('tierlist-author').value = draft.author.slice(0,60);
    } catch (_) {}
  }

  function card(id, editable = false) {
    const item = itemFor(id);
    if (!item) return '';
    const content = `<img src="${escape(item.image)}" alt="${escape(item.name)}" width="400" height="400" draggable="false" loading="lazy">`;
    return editable
      ? `<button type="button" class="tier-item${selected === id ? ' is-selected' : ''}" data-tierlist-item="${escape(id)}" draggable="true" aria-pressed="${selected === id}" title="${escape(item.teamName ? `${item.name} · ${item.teamName}` : item.name)}">${content}</button>`
      : `<span class="tier-item" title="${escape(item.teamName ? `${item.name} · ${item.teamName}` : item.name)}">${content}</span>`;
  }
  function board(arrangement, editable = false) {
    return TIERS.map(tier => `<div class="tier-row">${editable ? `<button type="button" class="tier-label tier-${tier}" data-place="${tier}" aria-label="Colocar ${noun()} seleccionado en ${tier}">${tier}</button>` : `<span class="tier-label tier-${tier}">${tier}</span>`}<div class="tier-items"${editable ? ` data-place="${tier}" aria-label="Fila ${tier}"` : ''}>${(arrangement[tier] || []).map(id => card(id, editable)).join('')}${editable && !arrangement[tier].length ? `<span class="tier-row-empty">Coloca aquí un ${noun()}</span>` : ''}</div></div>`).join('');
  }
  function updateControls() {
    const remaining = pool().length;
    $('tierlist-remaining').textContent = `${remaining} ${remaining === 1 ? `${noun()} pendiente` : `${noun()}s pendientes`}`;
    $('tierlist-publish').disabled = !ready || busy || !publishing.canPublish || remaining !== 0;
    $('tierlist-publish').textContent = busy ? 'Publicando…' : 'Publicar tierlist';
    $('tierlist-publishing-status').textContent = publishing.message;
    $('tierlist-login').hidden = !!publishing.teamId;
    $('tierlist-selected').textContent = selected && itemFor(selected) ? `${itemFor(selected).name} seleccionado` : `Selecciona un ${noun()} para moverlo.`;
    document.querySelectorAll('[data-tierlist-shift], #tierlist-unplace').forEach(button => { button.disabled = busy || !selected || !placed().includes(selected); });
    $('tierlist-reset').disabled = busy || !ready;
    $('tierlist-author').disabled = busy;
    document.querySelectorAll('[data-tierlist-kind]').forEach(button => {button.disabled = busy;});
    document.querySelectorAll('#tierlist-editor [data-tierlist-item], #tierlist-board button.tier-label').forEach(button => { button.disabled = busy; });
  }
  function drawEditor(focus = false) {
    $('tierlist-board').innerHTML = board(tiers, true);
    $('tierlist-pool').innerHTML = pool().map(id => card(id, true)).join('');
    updateControls();
    if (focus && selected) document.querySelector(`[data-tierlist-item="${selected}"]`)?.focus({preventScroll:true});
  }
  function select(id) {
    if (busy || !itemFor(id)) return;
    selected = id;
    document.querySelectorAll('[data-tierlist-item]').forEach(button => {
      const active = button.dataset.tierlistItem === selected;
      button.classList.toggle('is-selected', active); button.setAttribute('aria-pressed', String(active));
    });
    updateControls();
  }
  function place(id, tier, anchor = '', after = false) {
    if (busy || !itemFor(id) || ![...TIERS,'pool'].includes(tier) || id === anchor) return;
    for (const key of TIERS) tiers[key] = tiers[key].filter(value => value !== id);
    if (tier !== 'pool') {
      const index = tiers[tier].indexOf(anchor);
      tiers[tier].splice(index < 0 ? tiers[tier].length : index + Number(after), 0, id);
    }
    selected = id; saveDraft(); drawEditor(true); error('');
  }
  function shift(direction) {
    const tier = TIERS.find(key => tiers[key].includes(selected));
    if (!tier || busy) return;
    const index = tiers[tier].indexOf(selected), target = index + direction;
    if (target < 0 || target >= tiers[tier].length) return;
    [tiers[tier][index], tiers[tier][target]] = [tiers[tier][target], tiers[tier][index]];
    saveDraft(); drawEditor(true);
  }

  function drawGallery() {
    $('tierlist-count').textContent = `${total} ${total === 1 ? 'tierlist publicada' : 'tierlists publicadas'}`;
    $('tierlist-feed').innerHTML = posts.length ? posts.map(post => {
      const title = `Tierlist de ${post.author || post.teamName}`;
      const date = new Date(post.createdAt * 1000).toLocaleString('es-ES', {timeZone:'Europe/Madrid',dateStyle:'medium',timeStyle:'short'});
      return `<article class="tierlist-post" data-tierlist-post="${escape(post.id)}"><div class="tierlist-post-header"><div><h2>${escape(title)}</h2><p class="tierlist-post-meta">${escape(post.teamName)} · ${escape(date)}</p></div><button type="button" class="tierlist-secondary" data-tierlist-expand="${escape(post.id)}" aria-label="Ampliar ${escape(title)}">Ampliar ↗</button></div><div class="tier-board" aria-label="${escape(title)}">${board(post.tiers)}</div></article>`;
    }).join('') : '<p class="tierlist-empty">Todavía no hay tierlists publicadas. ¿Quién se atreve con la primera?</p>';
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    $('tierlist-pagination').hidden = pages <= 1;
    $('tierlist-previous').disabled = page <= 1;
    $('tierlist-next').disabled = page >= pages;
    $('tierlist-page-info').textContent = `Página ${page} de ${pages}`;
  }
  function apply(result) {
    const first = !ready;
    items = result.items; posts = result.posts; total = result.total; publishing = result.publishing; ready = true;
    if (first) { restoreDraft(); drawEditor(); }
    drawGallery(); updateControls();
  }
  async function load() {
    if (busy) return;
    const version = ++loadVersion;
    try {
      const result = await request((page - 1) * PAGE_SIZE);
      if (version !== loadVersion) return;
      if (page > 1 && result.total <= (page - 1) * PAGE_SIZE) { page = Math.max(1, Math.ceil(result.total / PAGE_SIZE)); return load(); }
      apply(result);
    } catch (_) { if (version === loadVersion) feedback('No se pudieron cargar las tierlists. Pulsa Actualizar para intentarlo de nuevo.'); }
  }
  function showView(value) {
    view = value;
    updateUrl();
    $('tierlist-gallery').hidden = view !== 'gallery'; $('tierlist-editor').hidden = view !== 'editor';
    document.querySelectorAll('[data-tierlist-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.tierlistView === view)));
  }

  function updateUrl() {
    const query = kind === 'players' ? '?tipo=integrantes' : '';
    history.replaceState(null, '', `${location.pathname}${query}${view === 'editor' ? '#crear' : '#publicadas'}`);
  }
  function updateKindCopy() {
    const players = kind === 'players';
    document.querySelector('.tierlist-page').dataset.kind = kind;
    document.querySelectorAll('[data-tierlist-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.tierlistKind === kind)));
    $('tierlist-description').textContent = players ? 'Ordena a los 18 integrantes por habilidad y comparte tu veredicto.' : 'Coloca a los equipos y comparte tu pronóstico.';
    $('tierlist-editor-title').textContent = players ? '¿Quién tiene más manos?' : '¿Quién está para ganar?';
    $('tierlist-help').textContent = players ? 'Arrastra los integrantes a una fila. También puedes seleccionar un integrante y pulsar la letra de su fila.' : 'Arrastra los equipos a una fila. También puedes seleccionar un equipo y pulsar la letra de su fila.';
    $('tierlist-pool-title').textContent = players ? 'Integrantes por colocar' : 'Equipos por colocar';
    $('tierlist-pool').setAttribute('aria-label', $('tierlist-pool-title').textContent);
    document.querySelectorAll('[data-tierlist-shift]').forEach(button => button.setAttribute('aria-label', `Mover el ${noun()} seleccionado a la ${button.dataset.tierlistShift === '-1' ? 'izquierda' : 'derecha'}`));
  }
  function changeKind(value) {
    if (busy || kind === value || !['teams','players'].includes(value)) return;
    if (ready) saveDraft();
    kind = value; loadVersion++; page = 1; selected = ''; ready = false;
    items = []; posts = []; total = 0;
    tiers = Object.fromEntries(TIERS.map(tier => [tier, []]));
    publishing = {canPublish:false,message:'Cargando…'};
    $('tierlist-author').value = '';
    $('tierlist-detail').close();
    error(''); feedback(''); updateKindCopy(); drawEditor(); drawGallery();
    $('tierlist-count').textContent = 'Cargando tierlists…';
    updateUrl(); load();
  }
  document.querySelectorAll('[data-tierlist-kind]').forEach(button => button.addEventListener('click', () => changeKind(button.dataset.tierlistKind)));

  document.querySelectorAll('[data-tierlist-view]').forEach(button => button.addEventListener('click', () => { showView(button.dataset.tierlistView); }));
  $('tierlist-editor').addEventListener('click', event => {
    const tile = event.target.closest('[data-tierlist-item]');
    if (tile) return select(tile.dataset.tierlistItem);
    const row = event.target.closest('[data-place]');
    if (row && selected) place(selected, row.dataset.place);
  });
  $('tierlist-editor').addEventListener('keydown', event => {
    const tile = event.target.closest('[data-tierlist-item]');
    if (!tile || busy) return;
    if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
      event.preventDefault(); select(tile.dataset.tierlistItem);
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') shift(event.key === 'ArrowLeft' ? -1 : 1);
      else {
        const current = TIERS.find(key => tiers[key].includes(selected));
        const index = current ? TIERS.indexOf(current) : TIERS.length;
        const next = index + (event.key === 'ArrowUp' ? -1 : 1);
        if (next >= 0 && next <= TIERS.length) place(selected, TIERS[next] || 'pool');
      }
    }
  });
  $('tierlist-editor').addEventListener('dragstart', event => {
    const tile = event.target.closest('[data-tierlist-item]');
    if (!tile || busy) return event.preventDefault();
    selected = tile.dataset.tierlistItem; event.dataTransfer.setData('text/plain', selected); event.dataTransfer.effectAllowed = 'move'; tile.classList.add('is-dragging');
  });
  $('tierlist-editor').addEventListener('dragover', event => {
    const row = event.target.closest('[data-place]');
    if (!row || busy) return;
    event.preventDefault(); event.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.is-drop-target').forEach(el => el.classList.remove('is-drop-target')); row.classList.add('is-drop-target');
  });
  $('tierlist-editor').addEventListener('drop', event => {
    const row = event.target.closest('[data-place]');
    if (!row || busy) return;
    event.preventDefault();
    const tile = event.target.closest('[data-tierlist-item]');
    const after = tile && event.clientX > tile.getBoundingClientRect().left + tile.getBoundingClientRect().width / 2;
    place(event.dataTransfer.getData('text/plain'), row.dataset.place, tile?.dataset.tierlistItem || '', after);
  });
  $('tierlist-editor').addEventListener('dragend', () => document.querySelectorAll('.is-dragging, .is-drop-target').forEach(el => el.classList.remove('is-dragging','is-drop-target')));
  document.querySelectorAll('[data-tierlist-shift]').forEach(button => button.addEventListener('click', () => shift(Number(button.dataset.tierlistShift))));
  $('tierlist-unplace').addEventListener('click', () => place(selected,'pool'));
  $('tierlist-author').addEventListener('input', saveDraft);
  $('tierlist-reset').addEventListener('click', () => { tiers = Object.fromEntries(TIERS.map(key => [key,[]])); selected = ''; saveDraft(); drawEditor(); error(''); });
  $('tierlist-refresh').addEventListener('click', () => { feedback(''); load(); });
  $('tierlist-previous').addEventListener('click', () => { if (page > 1) { page--; load(); } });
  $('tierlist-next').addEventListener('click', () => { if (page * PAGE_SIZE < total) { page++; load(); } });
  $('tierlist-feed').addEventListener('click', event => {
    const button = event.target.closest('[data-tierlist-expand]');
    const post = posts.find(post => post.id === button?.dataset.tierlistExpand);
    if (!post) return;
    $('tierlist-detail-title').textContent = `Tierlist de ${post.author || post.teamName}`;
    $('tierlist-detail-meta').textContent = post.teamName;
    $('tierlist-detail-board').innerHTML = board(post.tiers);
    $('tierlist-detail').showModal();
  });
  $('tierlist-detail-close').addEventListener('click', () => $('tierlist-detail').close());
  $('tierlist-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!ready || busy || !publishing.canPublish || pool().length) return;
    busy = true; loadVersion++; updateControls(); error('');
    const body = {kind, author: $('tierlist-author').value.trim(), tiers: JSON.parse(JSON.stringify(tiers))};
    try {
      const result = await request(0, body);
      page = 1; apply(result);
      try { localStorage.removeItem(draftKey()); } catch (_) {}
      feedback('Tu tierlist ya está publicada. ¡Que empiece el debate!'); showView('gallery');
    } catch (failure) {
      error(failure.name === 'AbortError' ? 'No se pudo confirmar la publicación. Consulta las tierlists publicadas antes de intentarlo otra vez.' : failure.message);
    } finally { busy = false; updateControls(); load(); }
  });
  for (const name of ['player-session-changed','player-session-ended']) document.addEventListener(name, load);
  window.addEventListener('focus', load);
  setInterval(() => { if (!document.hidden && view === 'gallery') load(); }, 60000);
  updateKindCopy();
  showView(location.hash === '#crear' ? 'editor' : 'gallery');
  load();
})();
