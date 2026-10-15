/* Final standings predictions. Drafts are local; publication and scores belong to the server. */
(() => {
  const $ = id => document.getElementById(id);
  const PAGE_SIZE = 6, DRAFT_KEY = 'pepes_final_prediction_draft_v1';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const token = () => { try { return sessionStorage.getItem('pepes_player_token') || ''; } catch (_) { return ''; } };
  let state = null, order = [], page = 1, busy = false, view = 'gallery', version = 0, pointerDrag = null;
  const team = id => state.items.find(item => item.id === id);
  const date = value => new Date(value * 1000).toLocaleString('es-ES', {timeZone:'Europe/Madrid', dateStyle:'medium', timeStyle:'short'}) + ' (Madrid)';
  const icon = name => `<i class="fa-solid fa-${name}" aria-hidden="true"></i>`;
  const error = message => { $('porra-form-error').textContent = message; $('porra-form-error').hidden = !message; };
  function picture(id) {
    const item = team(id);
    return item.image ? `<img class="rp-photo" src="${escape(item.image)}" alt="" width="60" height="60" draggable="false" loading="lazy">`
      : `<span class="rp-photo porra-initials" aria-hidden="true">${escape(item.name.slice(0,2).toUpperCase())}</span>`;
  }
  async function request(body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const session = token();
      const response = await fetch(`${API_BASE_URL}/final-predictions${body ? '' : `?offset=${(page-1)*PAGE_SIZE}&limit=${PAGE_SIZE}`}`, {
        credentials:'same-origin', signal:controller.signal,
        headers:{...(session ? {Authorization:`Bearer ${session}`} : {}), ...(body ? {'Content-Type':'application/json'} : {})},
        ...(body ? {method:'POST', body:JSON.stringify(body)} : {})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'No se pudo completar la acción.');
      return result;
    } finally { clearTimeout(timeout); }
  }
  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({order, author:$('porra-author').value})); } catch (_) {}
  }
  function restoreDraft() {
    let draft;
    try { draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (_) {}
    const ids = state.items.map(item => item.id);
    order = [...new Set((Array.isArray(draft?.order) ? draft.order : []).filter(id => ids.includes(id)))];
    order.push(...ids.filter(id => !order.includes(id)));
    if (typeof draft?.author === 'string') $('porra-author').value = draft.author.slice(0,60);
  }
  function controls() {
    $('porra-publish').disabled = busy || !state?.publishing.canPublish || order.length < 2;
    $('porra-publish').innerHTML = busy ? 'Publicando…' : `${icon('paper-plane')} Publicar mi pronóstico`;
    $('porra-author').disabled = busy;
    $('porra-publishing-status').textContent = state?.publishing.message || 'Inicia sesión con tu equipo para publicar.';
    $('porra-login').hidden = !!state?.publishing.teamId;
    document.querySelectorAll('[data-porra-shift]').forEach(button => {
      const index = order.indexOf(button.dataset.team), delta = Number(button.dataset.porraShift);
      button.disabled = busy || index + delta < 0 || index + delta >= order.length;
    });
    for (const id of ['porra-refresh','porra-previous','porra-next']) $(id).disabled = busy || (id === 'porra-previous' ? page <= 1 : id === 'porra-next' ? page*PAGE_SIZE >= (state?.total || 0) : false);
  }
  function arrows(id,index) {
    return `<div class="rp-arrows"><button type="button" data-porra-shift="-1" data-team="${escape(id)}" aria-label="Subir a ${escape(team(id).name)}"${index === 0 ? ' disabled' : ''}>${icon('chevron-up')}</button><button type="button" data-porra-shift="1" data-team="${escape(id)}" aria-label="Bajar a ${escape(team(id).name)}"${index === order.length-1 ? ' disabled' : ''}>${icon('chevron-down')}</button></div>`;
  }
  function card(ids,index,podium,editable) {
    const id = ids[index], item = team(id);
    const subtitle = index === 0 ? 'Mi campeón' : index === 1 ? 'A un paso de la gloria' : index === 2 ? 'Cierra el podio' : index === ids.length-1 ? 'El farolillo rojo' : '';
    const attrs = editable ? ` data-porra-team="${escape(id)}" data-position="${index}"` : '';
    if (podium) return `<article class="rp-team ${index === 0 ? 'rp-first' : ''}"${attrs} aria-label="Puesto ${index+1}: ${escape(item.name)}"><div class="rp-medal">${icon(index === 0 ? 'crown' : 'medal')}${index+1}.º</div>${picture(id)}<div class="rp-name">${escape(item.name)}</div><span class="rp-tagline">${subtitle}</span>${editable ? arrows(id,index) : ''}</article>`;
    return `<article class="rp-team"${attrs} aria-label="Puesto ${index+1}: ${escape(item.name)}">${editable ? `<span class="rp-grip">${icon('grip-vertical')}</span>` : ''}<span class="rp-number">${index+1}</span>${picture(id)}<div class="rp-grow"><div class="rp-name">${escape(item.name)}</div>${subtitle ? `<span class="rp-tagline">${subtitle}</span>` : ''}</div>${editable ? arrows(id,index) : ''}</article>`;
  }
  function board(ids,editable=false) {
    if (!ids.length) return '<p class="rp-help">Aún no hay equipos registrados.</p>';
    const podium = ids.length >= 3 ? `<div class="rp-podium">${[1,0,2].map(i => card(ids,i,true,editable)).join('')}</div>` : '';
    return podium + `<div class="rp-rest">${ids.map((_,i) => i < 3 && podium ? '' : card(ids,i,false,editable)).join('')}</div>`;
  }
  function editor() {
    $('porra-team-count').textContent = `${order.length} equipos · ${order.length} puestos`;
    $('porra-board').innerHTML = board(order,true);
    controls();
  }
  function gallery() {
    $('porra-count').textContent = `${state.total} ${state.total === 1 ? 'pronóstico publicado' : 'pronósticos publicados'}`;
    $('porra-result-status').textContent = state.result ? 'Torneo finalizado. Ya puedes comparar los puestos y ver los aciertos de cada pronóstico.' : 'Los aciertos se comprobarán con la clasificación oficial al terminar el torneo. Puedes publicar en cualquier momento; la fecha queda visible.';
    $('porra-feed').innerHTML = state.posts.length ? state.posts.map(post => {
      const c = post.comparison;
      const badge = c?.status === 'SETTLED' ? `${c.exact} / ${c.total} aciertos` : c ? 'No comparable' : 'Pronóstico';
      return `<article class="rp-post" data-porra-post="${escape(post.id)}"><div class="rp-post-heading"><div><h2>${escape(post.author || post.teamName)}</h2><p class="rp-post-meta">${escape(post.teamName)}</p><time class="rp-post-meta" datetime="${new Date(post.createdAt*1000).toISOString()}">Publicado el ${escape(date(post.createdAt))}</time></div><span class="rp-badge">${badge}</span></div>${post.order.map((id,i) => `<div class="rp-mini-row"><span class="rp-mini-number">${i+1}.</span>${picture(id)}<span class="rp-name">${escape(team(id).name)}</span></div>`).join('')}<button type="button" class="rp-compare-button" data-porra-expand="${escape(post.id)}">${c ? 'Ver aciertos y comparación' : 'Ver pronóstico'} →</button></article>`;
    }).join('') : '<div class="porra-empty"><h2>¿Quién se atreve a predecir el final?</h2><p>Ordena a los equipos y publica el primer pronóstico.</p><button type="button" class="rp-primary" data-porra-view="editor">Crear mi pronóstico</button></div>';
    const pages = Math.max(1,Math.ceil(state.total/PAGE_SIZE));
    $('porra-pagination').hidden = pages <= 1;
    $('porra-page-info').textContent = `Página ${page} de ${pages}`;
    controls();
  }
  function apply(result) {
    const previous = state?.items.map(i=>i.id).join('|');
    state = result;
    if (previous !== state.items.map(i=>i.id).join('|')) { restoreDraft(); editor(); }
    gallery();
  }
  async function load() {
    if (busy || pointerDrag) return;
    const current = ++version;
    try {
      const result = await request();
      if (current !== version) return;
      if (page > 1 && result.total <= (page-1)*PAGE_SIZE) { page = Math.max(1,Math.ceil(result.total/PAGE_SIZE)); return load(); }
      apply(result);
    } catch (_) { if (current === version) $('porra-feedback').textContent = 'No se pudieron cargar los pronósticos. Pulsa Actualizar para volver a intentarlo.'; }
  }
  function showView(next) {
    view = next;
    $('porra-editor').hidden = view !== 'editor'; $('porra-gallery').hidden = view !== 'gallery';
    document.querySelectorAll('.rp-switch [data-porra-view]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.porraView === view)));
    history.replaceState(null,'',view === 'editor' ? '#crear' : '#publicadas');
  }
  function move(id,target,delta) {
    const from = order.indexOf(id);
    if (busy || from < 0 || target < 0 || target >= order.length || target === from) return;
    order.splice(from,1); order.splice(target,0,id); saveDraft(); editor(); error('');
    $('porra-feedback').textContent = `${team(id).name} pasa al puesto ${target+1}.`;
    if (delta) {
      const buttons = [...document.querySelectorAll('[data-porra-shift]')].filter(b => b.dataset.team === id && !b.disabled);
      const button = buttons.find(b => Number(b.dataset.porraShift) === delta) || buttons[0];
      button?.focus({preventScroll:true});
    }
  }
  function detail(post) {
    $('porra-detail-title').textContent = `Pronóstico de ${post.author || post.teamName}`;
    $('porra-detail-meta').textContent = `${post.teamName} · Publicado el ${date(post.createdAt)}`;
    const c = post.comparison;
    $('porra-detail-body').innerHTML = c?.status === 'SETTLED'
      ? `<div class="rp-result-heading"><div><h2>La hora de la verdad</h2><p class="rp-help">Según los puestos de la clasificación oficial final.</p></div><div><strong class="rp-score">${c.exact} / ${c.total}</strong><p class="rp-help">posiciones exactas</p></div></div><div class="rp-result-list"><div class="rp-result-row rp-result-labels"><span>Tu puesto</span><span>Equipo</span><span>Final</span><span>Resultado</span></div>${c.positions.map(p => `<div class="rp-result-row"><strong>${p.predicted}.º</strong><div class="rp-result-team">${picture(p.teamId)}<span class="rp-name">${escape(team(p.teamId).name)}</span></div><strong>${p.actual}.º</strong><span class="${p.correct ? 'rp-exact' : 'rp-miss'}">${p.correct ? '✓ Exacto' : '—'}</span></div>`).join('')}</div>`
      : `${c ? '<p class="rp-help">Los equipos de este pronóstico no coinciden con la clasificación final. No se calculan aciertos.</p>' : '<p class="rp-help">Los aciertos aparecerán al terminar el torneo.</p>'}${board(post.order)}`;
    $('porra-detail').showModal();
  }
  document.querySelector('.porra-page').addEventListener('click', event => {
    const viewButton = event.target.closest('[data-porra-view]');
    if (viewButton) return showView(viewButton.dataset.porraView);
    const shift = event.target.closest('[data-porra-shift]');
    if (shift) return move(shift.dataset.team,order.indexOf(shift.dataset.team)+Number(shift.dataset.porraShift),Number(shift.dataset.porraShift));
    const expand = event.target.closest('[data-porra-expand]');
    const post = state?.posts.find(p => p.id === expand?.dataset.porraExpand);
    if (post) detail(post);
  });
  const editorRoot = $('porra-board');
  editorRoot.addEventListener('dragstart',event => event.preventDefault());
  editorRoot.addEventListener('pointerdown',event => {
    const row = event.target.closest('[data-porra-team]');
    if (busy || !row || event.target.closest('button') || event.button !== 0 || event.pointerType === 'touch') return;
    event.preventDefault();
    pointerDrag = {id:row.dataset.porraTeam,x:event.clientX,y:event.clientY,target:null,moved:false};
    editorRoot.setPointerCapture(event.pointerId);
  });
  editorRoot.addEventListener('pointermove',event => {
    if (!pointerDrag || Math.hypot(event.clientX-pointerDrag.x,event.clientY-pointerDrag.y)<6) return;
    pointerDrag.moved = true;
    editorRoot.querySelectorAll('.rp-drag-over').forEach(el => el.classList.remove('rp-drag-over'));
    const row = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-porra-team]');
    pointerDrag.target = row && editorRoot.contains(row) ? Number(row.dataset.position) : null;
    row?.classList.add('rp-drag-over');
  });
  function finishPointer(event,cancel=false) {
    const drag = pointerDrag; if (!drag) return;
    pointerDrag = null;
    if (editorRoot.hasPointerCapture(event.pointerId)) editorRoot.releasePointerCapture(event.pointerId);
    editorRoot.querySelectorAll('.rp-drag-over').forEach(el => el.classList.remove('rp-drag-over'));
    if (!cancel && drag.moved && drag.target !== null) move(drag.id,drag.target);
  }
  editorRoot.addEventListener('pointerup',event => finishPointer(event));
  editorRoot.addEventListener('pointercancel',event => finishPointer(event,true));
  $('porra-author').addEventListener('input',saveDraft);
  $('porra-detail-close').addEventListener('click',()=>$('porra-detail').close());
  $('porra-refresh').addEventListener('click',()=>{ $('porra-feedback').textContent=''; load(); });
  $('porra-previous').addEventListener('click',()=>{if(page>1){page--;load();}});
  $('porra-next').addEventListener('click',()=>{if(state&&page*PAGE_SIZE<state.total){page++;load();}});
  $('porra-form').addEventListener('submit',async event => {
    event.preventDefault();
    if (busy || !state?.publishing.canPublish || order.length < 2) return;
    busy = true; version++; controls(); error('');
    try {
      const result = await request({order:[...order],author:$('porra-author').value.trim()});
      page = 1; apply(result); showView('gallery');
      $('porra-feedback').textContent = 'Tu pronóstico ya está publicado. ¡Que empiece el debate!';
    } catch (failure) {
      error(failure.name === 'AbortError' ? 'No se pudo confirmar la publicación. Consulta las predicciones publicadas antes de intentarlo otra vez.' : failure.message);
    } finally {busy=false;controls();load();}
  });
  for (const name of ['player-session-changed','player-session-ended']) document.addEventListener(name,load);
  window.addEventListener('focus',load);
  setInterval(()=>{if(!document.hidden&&view==='gallery')load();},60000);
  showView(location.hash === '#crear' ? 'editor' : 'gallery');
  load();
})();
