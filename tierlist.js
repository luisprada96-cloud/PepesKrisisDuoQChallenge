/* Permanent public tierlists; drafts are local, publication limits are server-owned. */
(() => {
  const TIERS = ['S', 'A', 'B', 'C', 'D'];
  const ROLE_TIERS = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY'];
  const ROLE_LABELS = {
    TOP: { label: 'TOP', icon: 'fa-shield-halved', colorClass: 'role-TOP', short: 'TOP' },
    JUNGLE: { label: 'JUNGLA', icon: 'fa-tree', colorClass: 'role-JUNGLE', short: 'JGL' },
    MIDDLE: { label: 'MEDIO', icon: 'fa-wand-magic-sparkles', colorClass: 'role-MIDDLE', short: 'MID' },
    BOTTOM: { label: 'ADC', icon: 'fa-crosshairs', colorClass: 'role-BOTTOM', short: 'ADC' },
    UTILITY: { label: 'SUPP', icon: 'fa-heart', colorClass: 'role-UTILITY', short: 'SUP' }
  };
  const PAGE_SIZE = 6;
  const kindParam = new URLSearchParams(location.search).get('tipo');
  let kind = kindParam === 'roles' ? 'roles' : (kindParam === 'integrantes' ? 'players' : 'teams');
  const currentTiers = (boardKind = kind) => boardKind === 'roles' ? ROLE_TIERS : TIERS;
  const draftKey = () => kind === 'roles' ? 'pepes_tierlist_roles_draft_v1' : (kind === 'players' ? 'pepes_tierlist_players_draft_v1' : 'pepes_tierlist_draft_v1');
  const noun = () => kind === 'teams' ? 'equipo' : 'integrante';
  let items = [], posts = [], total = 0, page = 1, selected = '', ready = false, busy = false, view = 'gallery', loadVersion = 0;
  let publishing = {canPublish: false, message: 'Inicia sesión con tu equipo para publicar.'};
  let tiers = Object.fromEntries(currentTiers().map(tier => [tier, []]));
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const token = () => { try { return sessionStorage.getItem('pepes_player_token') || ''; } catch (_) { return ''; } };
  const placed = () => currentTiers().flatMap(tier => tiers[tier] || []);
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
      const list = currentTiers();
      tiers = Object.fromEntries(list.map(tier => [tier, []]));
      for (const tier of list) tiers[tier] = (Array.isArray(draft?.tiers?.[tier]) ? draft.tiers[tier] : []).filter(id => {
        if (!itemFor(id) || used.has(id)) return false;
        if (kind === 'roles' && itemFor(id)?.role !== tier) return false;
        used.add(id); return true;
      });
      if (typeof draft?.author === 'string') $('tierlist-author').value = draft.author.slice(0,60);
    } catch (_) {}
  }

  function card(id, editable = false, pos = 0, boardKind = kind) {
    const item = itemFor(id);
    if (!item) return '';
    const isRoles = boardKind === 'roles';
    const posBadge = isRoles && pos > 0
      ? `<span class="role-pos-badge ${pos === 1 ? 'rank-pos-gold' : pos === 2 ? 'rank-pos-silver' : pos === 3 ? 'rank-pos-bronze' : 'rank-pos-neutral'}">${pos}º</span>`
      : '';
    const roleBadge = isRoles && !pos && item.role
      ? `<span class="pool-role-badge role-${escape(item.role)}">${escape(ROLE_LABELS[item.role]?.short || item.role)}</span>`
      : '';
    const content = `<div class="tier-item-inner">${posBadge}${roleBadge}<img src="${escape(item.image)}" alt="${escape(item.name)}" width="400" height="400" draggable="false" loading="lazy"></div>`;
    return editable
      ? `<button type="button" class="tier-item${selected === id ? ' is-selected' : ''}" data-tierlist-item="${escape(id)}" draggable="true" aria-pressed="${selected === id}" title="${escape(item.teamName ? `${item.name} · ${item.teamName}` : item.name)}">${content}</button>`
      : `<span class="tier-item" title="${escape(item.teamName ? `${item.name} · ${item.teamName}` : item.name)}">${content}</span>`;
  }
  function board(arrangement, editable = false, boardKind = kind) {
    const tierList = currentTiers(boardKind);
    const isRoles = boardKind === 'roles';
    return tierList.map(tier => {
      const labelObj = ROLE_LABELS[tier];
      const isRoleRow = isRoles && labelObj;
      const labelContent = isRoleRow
        ? `<i class="fa-solid ${labelObj.icon}" aria-hidden="true"></i><span class="role-name">${labelObj.label}</span>`
        : tier;
      const labelClass = isRoleRow ? `tier-label tier-role-header ${labelObj.colorClass}` : `tier-label tier-${tier}`;
      const headerAria = `Colocar ${noun()} seleccionado en ${isRoleRow ? labelObj.label : tier}`;
      const headerHtml = editable
        ? `<button type="button" class="${labelClass}" data-place="${tier}" aria-label="${headerAria}">${labelContent}</button>`
        : `<span class="${labelClass}">${labelContent}</span>`;
      const placedCards = (arrangement[tier] || []).map((id, idx) => card(id, editable, idx + 1, boardKind)).join('');
      const emptyNote = editable && !(arrangement[tier] || []).length
        ? `<span class="tier-row-empty">Coloca aquí los integrantes de ${isRoleRow ? labelObj.label : tier}</span>`
        : '';
      return `<div class="tier-row${isRoleRow ? ' tier-row-role' : ''}">${headerHtml}<div class="tier-items"${editable ? ` data-place="${tier}" aria-label="Fila ${isRoleRow ? labelObj.label : tier}"` : ''}>${placedCards}${emptyNote}</div></div>`;
    }).join('');
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
    $('tierlist-board').innerHTML = board(tiers, true, kind);
    $('tierlist-pool').innerHTML = pool().map(id => card(id, true, 0, kind)).join('');
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
    const validTiers = [...currentTiers(), 'pool'];
    if (busy || !itemFor(id) || !validTiers.includes(tier) || id === anchor) return;

    if (kind === 'roles' && tier !== 'pool') {
      const itemRole = itemFor(id)?.role;
      if (itemRole && itemRole !== tier) {
        error(`${itemFor(id).name} tiene rol principal ${ROLE_LABELS[itemRole]?.label || itemRole}. Solo puede colocarse en esa fila.`);
        return;
      }
    }

    const list = currentTiers();
    for (const key of list) tiers[key] = (tiers[key] || []).filter(value => value !== id);
    if (tier !== 'pool') {
      if (!Array.isArray(tiers[tier])) tiers[tier] = [];
      const index = tiers[tier].indexOf(anchor);
      tiers[tier].splice(index < 0 ? tiers[tier].length : index + Number(after), 0, id);
    }
    selected = id; saveDraft(); drawEditor(true); error('');
  }
  function shift(direction) {
    const list = currentTiers();
    const tier = list.find(key => (tiers[key] || []).includes(selected));
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
      const postKind = post.kind || kind;
      return `<article class="tierlist-post" data-tierlist-post="${escape(post.id)}"><div class="tierlist-post-header"><div><h2>${escape(title)}</h2><p class="tierlist-post-meta">${escape(post.teamName)} · ${escape(date)}</p></div><button type="button" class="tierlist-secondary" data-tierlist-expand="${escape(post.id)}" aria-label="Ampliar ${escape(title)}">Ampliar ↗</button></div><div class="tier-board" aria-label="${escape(title)}">${board(post.tiers, false, postKind)}</div></article>`;
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
    const query = kind === 'roles' ? '?tipo=roles' : (kind === 'players' ? '?tipo=integrantes' : '');
    history.replaceState(null, '', `${location.pathname}${query}${view === 'editor' ? '#crear' : '#publicadas'}`);
  }
  function updateKindCopy() {
    const isRoles = kind === 'roles';
    const isPlayers = kind === 'players';
    document.querySelector('.tierlist-page').dataset.kind = kind;
    document.querySelectorAll('[data-tierlist-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.tierlistKind === kind)));
    
    if (isRoles) {
      $('tierlist-description').textContent = 'Ordena a los integrantes en sus 5 posiciones principales y comparte tu veredicto.';
      $('tierlist-editor-title').textContent = '¿Quién domina cada línea?';
      $('tierlist-help').textContent = 'Arrastra los integrantes a la fila de su posición (Top, Jungla, Medio, ADC, Supp) y ordénalos de mejor a peor.';
      $('tierlist-pool-title').textContent = 'Integrantes por colocar';
    } else if (isPlayers) {
      $('tierlist-description').textContent = 'Ordena a los 18 integrantes por habilidad y comparte tu veredicto.';
      $('tierlist-editor-title').textContent = '¿Quién tiene más manos?';
      $('tierlist-help').textContent = 'Arrastra los integrantes a una fila. También puedes seleccionar un integrante y pulsar la letra de su fila.';
      $('tierlist-pool-title').textContent = 'Integrantes por colocar';
    } else {
      $('tierlist-description').textContent = 'Coloca a los equipos y comparte tu pronóstico.';
      $('tierlist-editor-title').textContent = '¿Quién está para ganar?';
      $('tierlist-help').textContent = 'Arrastra los equipos a una fila. También puedes seleccionar un equipo y pulsar la letra de su fila.';
      $('tierlist-pool-title').textContent = 'Equipos por colocar';
    }

    $('tierlist-pool').setAttribute('aria-label', $('tierlist-pool-title').textContent);
    document.querySelectorAll('[data-tierlist-shift]').forEach(button => button.setAttribute('aria-label', `Mover el ${noun()} seleccionado a la ${button.dataset.tierlistShift === '-1' ? 'izquierda' : 'derecha'}`));
  }
  function changeKind(value) {
    if (busy || kind === value || !['teams','players','roles'].includes(value)) return;
    if (ready) saveDraft();
    kind = value; loadVersion++; page = 1; selected = ''; ready = false;
    items = []; posts = []; total = 0;
    tiers = Object.fromEntries(currentTiers(value).map(tier => [tier, []]));
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
    const list = currentTiers();
    if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
      event.preventDefault(); select(tile.dataset.tierlistItem);
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') shift(event.key === 'ArrowLeft' ? -1 : 1);
      else {
        const current = list.find(key => (tiers[key] || []).includes(selected));
        const index = current ? list.indexOf(current) : list.length;
        const next = index + (event.key === 'ArrowUp' ? -1 : 1);
        if (next >= 0 && next <= list.length) place(selected, list[next] || 'pool');
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
  $('tierlist-reset').addEventListener('click', () => { tiers = Object.fromEntries(currentTiers().map(key => [key,[]])); selected = ''; saveDraft(); drawEditor(); error(''); });
  $('tierlist-refresh').addEventListener('click', () => { feedback(''); load(); });
  $('tierlist-previous').addEventListener('click', () => { if (page > 1) { page--; load(); } });
  $('tierlist-next').addEventListener('click', () => { if (page * PAGE_SIZE < total) { page++; load(); } });
  $('tierlist-feed').addEventListener('click', event => {
    const button = event.target.closest('[data-tierlist-expand]');
    const post = posts.find(post => post.id === button?.dataset.tierlistExpand);
    if (!post) return;
    $('tierlist-detail-title').textContent = `Tierlist de ${post.author || post.teamName}`;
    $('tierlist-detail-meta').textContent = post.teamName;
    $('tierlist-detail-board').innerHTML = board(post.tiers, false, post.kind || kind);
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
