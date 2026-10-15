/* Weekly Pick'em. Answers, browser quotas and rewards are always server-owned. */
(() => {
  const $=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let state=null, week='', currentCategory='', busy=false, version=0;
  let championMatches=[], championActive=-1;
  const token=()=>{try{return sessionStorage.getItem('pepes_player_token')||'';}catch(_){return '';}};
  const closed=()=>!state || state.closed || Date.now()/1000>=state.closesAt;
  const category=()=>state?.categories.find(c=>c.id===currentCategory);
  const isChampion=c=>c?.kind==='champion';
  const optionLabel=(c,id)=>c.options.find(o=>o.id===id)?.label || 'Sin respuesta';
  const isDuel=c=>c?.kind==='duel'||c?.sharedWithTeam===true;
  const allowedAnswer=(c,value)=>!isDuel(c)||(!c.teamAnswerConflict&&(!c.teamAnswer||c.teamAnswer===value));
  const duelRule=c=>c.teamAnswerConflict?'Respuestas anteriores en conflicto. Consulta a la administración.':c.teamAnswer?`Elección del equipo: ${optionLabel(c,c.teamAnswer)}. Ambos debéis elegir esta opción.`:'Una elección por equipo: la primera respuesta fija la opción para ambos integrantes.';
  const resultSummary=c=>c.result.summary || (c.result.status==='SETTLED'?`${c.result.value} campeones distintos`:'Sin datos válidos. Esta categoría no suma un acierto.');
  const rewardText=()=>`🐢 ${(state.rewardRule.tiers||[state.rewardRule]).map(tier=>`${tier.shells} ${tier.shells===1?'pepazo':'pepazos'} con al menos ${tier.minCorrect} aciertos`).join(' · ')}. Premio total por quiniela.`;
  const date=timestamp=>new Date(timestamp*1000).toLocaleString('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  const championSearchKey=value=>String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]/g,'');
  function closeChampionOptions() {
    $('pickem-champion-options').hidden=true;
    $('pickem-champion-search').setAttribute('aria-expanded','false');
    $('pickem-champion-search').removeAttribute('aria-activedescendant');
    championActive=-1;
  }
  function renderChampionOptions() {
    const c=category(), input=$('pickem-champion-search');
    if(!isChampion(c)||input.disabled)return closeChampionOptions();
    const query=championSearchKey(input.value);
    championMatches=c.options.filter(o=>!o.disabled&&[o.label,o.id].some(value=>championSearchKey(value).includes(query)));
    championActive=-1;
    const list=$('pickem-champion-options');
    list.innerHTML=championMatches.length?championMatches.map((o,index)=>`<div class="pickem-champion-option" id="pickem-champion-option-${index}" role="option" aria-selected="${o.id===$('pickem-answer').value}" data-champion-id="${escape(o.id)}">${escape(o.label)}</div>`).join(''):'<p class="pickem-champion-empty">No se encontró ningún campeón.</p>';
    list.hidden=false;
    input.setAttribute('aria-expanded','true');
    input.removeAttribute('aria-activedescendant');
    $('pickem-champion-status').textContent=`${championMatches.length} ${championMatches.length===1?'campeón disponible':'campeones disponibles'}.`;
  }
  function chooseChampion(id) {
    const option=category()?.options.find(o=>o.id===id&&!o.disabled);
    if(!option||$('pickem-champion-search').disabled)return;
    $('pickem-answer').value=option.id;
    $('pickem-champion-search').value=option.label;
    $('pickem-champion-status').textContent=`Campeón seleccionado: ${option.label}.`;
    closeChampionOptions();
    controls();
  }
  function weekLabel(key) {
    const period=state?.periods?.[key];
    if(period) {
      const format=timestamp=>new Date(timestamp*1000).toLocaleDateString('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'short'});
      return `${format(period.startsAt)} — ${format(period.endsAt-1)}`;
    }
    const start=new Date(key+'T12:00:00Z'),end=new Date(start.getTime()+6*86400000);
    const format=d=>d.toLocaleDateString('es-ES',{timeZone:'UTC',day:'numeric',month:'short'});
    return `${format(start)} — ${format(end)}`;
  }
  async function request(body) {
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try {
      const session=token();
      const response=await fetch(`${API_BASE_URL}/pickem${body?'':week?`?week=${encodeURIComponent(week)}`:''}`,{
        credentials:'same-origin',signal:controller.signal,
        headers:{...(session?{Authorization:`Bearer ${session}`} :{}),...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{method:'POST',body:JSON.stringify(body)}:{})
      });
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'No se pudo completar la acción.');
      return result;
    } finally {clearTimeout(timeout);}
  }
  function controls() {
    if(!state)return;
    const c=category();
    $('pickem-submit').disabled=busy||closed()||!state.participation.canAnswer||!!c?.myAnswer||!$('pickem-answer').value||!allowedAnswer(c,$('pickem-answer').value);
    $('pickem-submit').textContent=busy?'Guardando…':c?.myAnswer?'Predicción guardada':isDuel(c)&&c.teamAnswer?'Confirmar elección del equipo':'Guardar predicción';
    $('pickem-answer').disabled=busy||closed()||!!c?.myAnswer||(isDuel(c)&&!!(c.teamAnswer||c.teamAnswerConflict));
    $('pickem-champion-search').disabled=$('pickem-answer').disabled;
    if($('pickem-champion-search').disabled)closeChampionOptions();
    $('pickem-author').disabled=busy||closed()||!!state.myBallot;
    $('pickem-week').disabled=busy;
    $('pickem-closing').textContent=`${closed()?'Predicciones cerradas':'Responde hasta'}: ${date(state.closesAt-1)} · Partidas hasta ${date(state.endsAt-1)} (Madrid)`;
    document.querySelectorAll('[data-pickem-category]').forEach(button=>{
      const item=state.categories.find(item=>item.id===button.dataset.pickemCategory);
      button.disabled=busy||(closed()&&!item?.myAnswer);
      if(closed())button.textContent=item?.myAnswer?'Ver mi predicción':'Plazo cerrado';
    });
  }
  function modal(preserve=false) {
    const c=category();if(!c)return;
    const existing=$('pickem-answer').value;
    $('pickem-dialog-title').textContent=c.title;
    $('pickem-dialog-description').textContent=c.description+(isDuel(c)?` ${duelRule(c)}`:'');
    $('pickem-answer').innerHTML=`<option value="">${escape(c.options.some(o=>!o.disabled)?c.placeholder||'Selecciona una opción':'Sin participantes disponibles')}</option>`+c.options.map(o=>`<option value="${escape(o.id)}"${o.disabled||!allowedAnswer(c,o.id)?' disabled':''}>${escape(o.label)}</option>`).join('');
    $('pickem-answer').value=c.myAnswer||(isDuel(c)?c.teamAnswer:null)||(preserve?existing:'');
    $('pickem-answer').hidden=isChampion(c);
    $('pickem-champion-picker').hidden=!isChampion(c);
    $('pickem-answer-label').htmlFor=isChampion(c)?'pickem-champion-search':'pickem-answer';
    if(!preserve||c.myAnswer) {
      $('pickem-champion-search').value=$('pickem-answer').value?optionLabel(c,$('pickem-answer').value):'';
      $('pickem-champion-status').textContent='';
      closeChampionOptions();
    }
    if(!preserve||state.myBallot)$('pickem-author').value=state.myBallot?.author||'';
    $('pickem-modal-login').hidden=!!state.participation.teamId;
    $('pickem-modal-status').textContent=isDuel(c)&&c.teamAnswerConflict?duelRule(c):c.myAnswer?'Tu respuesta para esta categoría ya está guardada.':isDuel(c)&&c.teamAnswer?'Confirma la elección del equipo para añadirla a tu quiniela.':state.participation.message;
    $('pickem-answer-summary').textContent=c.result ? `${resultSummary(c)}${c.result.optionLabel?' · '+c.result.optionLabel:''}` : rewardText();
    controls();
    if(isChampion(c)&&!$('pickem-champion-options').hidden)renderChampionOptions();
  }
  function render() {
    if(!state)return;
    $('pickem-week').innerHTML=state.weeks.map(key=>`<option value="${key}">${escape(weekLabel(key))}</option>`).join('');
    $('pickem-week').value=state.week;
    $('pickem-entries').textContent=`${state.entries} ${state.entries===1?'quiniela enviada':'quinielas enviadas'}`;
    $('pickem-participation').textContent=state.participation.message;
    $('pickem-reward-rule').textContent=rewardText()+` Puede superar el límite de 5. Los resultados se calculan al terminar el periodo: ${date(state.endsAt-1)} (Madrid), tras completar la sincronización de partidas.`;
    $('pickem-login').hidden=!!state.participation.teamId;
    $('pickem-categories').innerHTML=state.categories.map(c=>{
      const result=c.result ? `<div class="pickem-card-result"><strong>${escape(resultSummary(c))}</strong>${c.result.optionLabel?`<br>Resultado: ${escape(c.result.optionLabel)}`:''}</div>` : closed()?`<div class="pickem-card-result">${Date.now()/1000<state.endsAt?'Predicciones cerradas. El periodo de juego sigue en curso.':'Comprobando los resultados de la semana…'}</div>`:'';
      return `<article class="pickem-card"><div class="pickem-card-art" aria-hidden="true"><span class="pickem-question-mark">${escape(c.icon||'?')}</span><span class="pickem-event">${escape(c.eventLabel||'EVENTO SEMANAL')}</span></div><h2>${escape(c.title)}</h2><p class="pickem-card-description">${escape(c.description)}</p>${isDuel(c)?`<p class="pickem-duel-rule">${escape(duelRule(c))}</p>`:''}<span class="pickem-reward">Objetivo: ${(state.rewardRule.tiers||[state.rewardRule]).map(tier=>tier.minCorrect).join(' / ')} aciertos</span><button type="button" class="pickem-primary" data-pickem-category="${escape(c.id)}">${closed()?'Ver predicción y resultado':c.myAnswer?'Ver mi predicción':isDuel(c)&&c.teamAnswer?'Confirmar elección del equipo':'Rellenar la quiniela'}</button>${c.myAnswer?`<p class="pickem-card-answer">Tu pronóstico: <strong>${escape(optionLabel(c,c.myAnswer))}</strong></p>`:''}${result}</article>`;
    }).join('');
    $('pickem-results').hidden=!(state.resultsVisible??closed());
    $('pickem-result-list').innerHTML=renderBallots(state.predictions, 'Nadie envió una quiniela esta semana.');
    $('pickem-team-picks').hidden=!state.participation.teamId;
    $('pickem-team-pick-list').innerHTML=renderBallots(state.teamBallots||[], 'Tu equipo todavía no ha enviado ninguna quiniela en este periodo.');
    if($('pickem-dialog').open)modal(true);
    controls();
  }
  function renderBallots(ballots, empty) {
    return ballots.length?ballots.map((b,index)=>{
      const awarded=b.reward?.status==='AWARDED';
      const verdict=awarded?`✓ +${b.reward.shells} ${b.reward.shells===1?'pepazo':'pepazos'}`:b.pending?'Pendiente de resultados':'Sin premio';
      const summary=`<div class="pickem-ballot-summary"><div><strong>${escape(b.author||`Quiniela ${index+1}`)}</strong><small>${escape(b.teamName)}${b.createdAt?` · ${escape(date(b.createdAt))} (Madrid)`:''}</small></div><strong>${b.correct} aciertos${b.pending?` · ${b.pending} pendientes`:''}</strong><strong class="${awarded?'pickem-win':b.pending?'pickem-wait':''}">${escape(verdict)}</strong></div>`;
      const answers=state.categories.map(c=>{
        const answer=b.answers[c.id];
        const result=c.result,correct=result?.status==='SETTLED'&&result.optionIds.includes(answer);
        const label=answer===undefined?'Sin responder':!result?'Pendiente de resultado':result.status!=='SETTLED'?'Sin datos válidos':correct?'✓ Acierto':'No acertó';
        return `<article class="pickem-result-entry"><div>${escape(c.title)}</div><div>${escape(optionLabel(c,answer))}</div><strong class="${correct?'pickem-win':!result?'pickem-wait':''}">${escape(label)}</strong></article>`;
      }).join('');
      return `<section class="pickem-ballot">${summary}${answers}</section>`;
    }).join(''):`<p>${escape(empty)}</p>`;
  }
  async function load() {
    if(busy)return;
    const revision=++version;
    try {const result=await request();if(revision===version){state=result;week=state.week;render();}}
    catch(error){if(revision===version)$('pickem-feedback').textContent='No se pudo cargar el Pick’em. Vuelve a intentarlo al actualizar la página.';}
  }
  $('pickem-categories').addEventListener('click',event=>{
    const button=event.target.closest('[data-pickem-category]');if(!button||button.disabled||!state)return;
    currentCategory=button.dataset.pickemCategory;$('pickem-form-error').hidden=true;modal();$('pickem-dialog').showModal();
  });
  $('pickem-close').addEventListener('click',()=>{if(!busy)$('pickem-dialog').close();});
  $('pickem-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  $('pickem-answer').addEventListener('change',controls);
  $('pickem-champion-search').addEventListener('focus',renderChampionOptions);
  $('pickem-champion-search').addEventListener('click',renderChampionOptions);
  $('pickem-champion-search').addEventListener('input',()=>{
    $('pickem-answer').value='';
    renderChampionOptions();
    controls();
  });
  $('pickem-champion-search').addEventListener('keydown',event=>{
    const list=$('pickem-champion-options');
    if(event.key==='Escape'&&!list.hidden) {
      event.preventDefault();event.stopPropagation();closeChampionOptions();return;
    }
    if(event.key==='ArrowDown'||event.key==='ArrowUp') {
      event.preventDefault();
      if(list.hidden)renderChampionOptions();
      if(!championMatches.length)return;
      championActive=championActive<0?(event.key==='ArrowDown'?0:championMatches.length-1):(championActive+(event.key==='ArrowDown'?1:-1)+championMatches.length)%championMatches.length;
      Array.from(list.children).forEach((option,index)=>option.classList.toggle('is-active',index===championActive));
      const option=list.children[championActive];
      $('pickem-champion-search').setAttribute('aria-activedescendant',option.id);
      option.scrollIntoView({block:'nearest'});
    } else if(event.key==='Enter'&&!list.hidden) {
      event.preventDefault();
      if(championMatches.length)chooseChampion(championMatches[Math.max(0,championActive)].id);
    } else if(event.key==='Tab')closeChampionOptions();
  });
  $('pickem-champion-options').addEventListener('pointerdown',event=>event.preventDefault());
  $('pickem-champion-options').addEventListener('click',event=>{
    const option=event.target.closest('[data-champion-id]');
    if(option)chooseChampion(option.dataset.championId);
  });
  $('pickem-dialog').addEventListener('click',event=>{
    if(!event.target.closest('#pickem-champion-picker'))closeChampionOptions();
  });
  $('pickem-week').addEventListener('change',()=>{week=$('pickem-week').value;$('pickem-dialog').close();currentCategory='';load();});
  $('pickem-form').addEventListener('submit',async event=>{
    event.preventDefault();const c=category();
    if(!state||!c||busy||closed()||!state.participation.canAnswer||c.myAnswer||!$('pickem-answer').value||!allowedAnswer(c,$('pickem-answer').value))return;
    const body={week:state.week,categoryId:c.id,optionId:$('pickem-answer').value,author:$('pickem-author').value.trim()};
    busy=true;version++;controls();$('pickem-form-error').hidden=true;
    try {state=await request(body);week=state.week;render();$('pickem-dialog').close();$('pickem-feedback').textContent='Predicción guardada. ¡Suerte con la quiniela!';}
    catch(error){$('pickem-form-error').textContent=error.name==='AbortError'?'No se pudo confirmar el envío. Actualiza para comprobar si tu predicción quedó guardada.':error.message;$('pickem-form-error').hidden=false;}
    finally{busy=false;controls();load();}
  });
  for(const name of ['player-session-changed','player-session-ended'])document.addEventListener(name,load);
  window.addEventListener('focus',load);
  setInterval(()=>{if(!document.hidden)load();},30000);
  setInterval(controls,1000);
  load();
})();
