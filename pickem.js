/* Weekly Pick'em. Answers, browser quotas and rewards are always server-owned. */
(() => {
  const $=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let state=null, week='', currentCategory='', busy=false, version=0;
  const token=()=>{try{return sessionStorage.getItem('pepes_player_token')||'';}catch(_){return '';}};
  const closed=()=>!state || state.closed || Date.now()/1000>=state.closesAt;
  const category=()=>state?.categories.find(c=>c.id===currentCategory);
  const optionLabel=(c,id)=>c.options.find(o=>o.id===id)?.label || 'Sin respuesta';
  const isDuel=c=>c?.kind==='duel'||c?.sharedWithTeam===true;
  const allowedAnswer=(c,value)=>!isDuel(c)||(!c.teamAnswerConflict&&(!c.teamAnswer||c.teamAnswer===value));
  const duelRule=c=>c.teamAnswerConflict?'Respuestas anteriores en conflicto. Consulta a la administración.':c.teamAnswer?`Elección del equipo: ${optionLabel(c,c.teamAnswer)}. Ambos debéis elegir esta opción.`:'Una elección por equipo: la primera respuesta fija la opción para ambos integrantes.';
  const resultSummary=c=>c.result.summary || (c.result.status==='SETTLED'?`${c.result.value} campeones distintos`:'Sin datos válidos. Esta categoría no suma un acierto.');
  const rewardText=()=>`🐢 ${state.rewardRule.shells} caparazón por quiniela con al menos ${state.rewardRule.minCorrect} aciertos.`;
  const date=timestamp=>new Date(timestamp*1000).toLocaleString('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  function weekLabel(key) {
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
    $('pickem-author').disabled=busy||closed()||!!state.myBallot;
    $('pickem-week').disabled=busy;
    $('pickem-closing').textContent=closed()?`Apuestas cerradas · ${date(state.closesAt)} (Madrid)`:`Cierre: domingo a las 23:59 · ${date(state.closesAt)} (Madrid)`;
  }
  function modal(preserve=false) {
    const c=category();if(!c)return;
    const existing=$('pickem-answer').value;
    $('pickem-dialog-title').textContent=c.title;
    $('pickem-dialog-description').textContent=c.description+(isDuel(c)?` ${duelRule(c)}`:'');
    $('pickem-answer').innerHTML=`<option value="">${escape(c.options.some(o=>!o.disabled)?c.placeholder||'Selecciona una opción':'Sin participantes disponibles')}</option>`+c.options.map(o=>`<option value="${escape(o.id)}"${o.disabled||!allowedAnswer(c,o.id)?' disabled':''}>${escape(o.label)}</option>`).join('');
    $('pickem-answer').value=c.myAnswer||(isDuel(c)?c.teamAnswer:null)||(preserve?existing:'');
    if(!preserve||state.myBallot)$('pickem-author').value=state.myBallot?.author||'';
    $('pickem-modal-login').hidden=!!state.participation.teamId;
    $('pickem-modal-status').textContent=isDuel(c)&&c.teamAnswerConflict?duelRule(c):c.myAnswer?'Tu respuesta para esta categoría ya está guardada.':isDuel(c)&&c.teamAnswer?'Confirma la elección del equipo para añadirla a tu quiniela.':state.participation.message;
    $('pickem-answer-summary').textContent=c.result ? `${resultSummary(c)}${c.result.optionLabel?' · '+c.result.optionLabel:''}` : rewardText();
    controls();
  }
  function render() {
    if(!state)return;
    $('pickem-week').innerHTML=state.weeks.map(key=>`<option value="${key}">${escape(weekLabel(key))}</option>`).join('');
    $('pickem-week').value=state.week;
    $('pickem-entries').textContent=`${state.entries} ${state.entries===1?'quiniela enviada':'quinielas enviadas'}`;
    $('pickem-participation').textContent=state.participation.message;
    $('pickem-reward-rule').textContent=rewardText()+' Puede superar el límite de 5. Cierre los domingos a las 23:59.';
    $('pickem-login').hidden=!!state.participation.teamId;
    $('pickem-categories').innerHTML=state.categories.map(c=>{
      const result=c.result ? `<div class="pickem-card-result"><strong>${escape(resultSummary(c))}</strong>${c.result.optionLabel?`<br>Resultado: ${escape(c.result.optionLabel)}`:''}</div>` : closed()?'<div class="pickem-card-result">Comprobando los resultados de la semana…</div>':'';
      return `<article class="pickem-card"><div class="pickem-card-art" aria-hidden="true"><span class="pickem-question-mark">${escape(c.icon||'?')}</span><span class="pickem-event">${escape(c.eventLabel||'EVENTO SEMANAL')}</span></div><h2>${escape(c.title)}</h2><p class="pickem-card-description">${escape(c.description)}</p>${isDuel(c)?`<p class="pickem-duel-rule">${escape(duelRule(c))}</p>`:''}<span class="pickem-reward">Objetivo: ${state.rewardRule.minCorrect} aciertos</span><button type="button" class="pickem-primary" data-pickem-category="${escape(c.id)}">${closed()?'Ver predicción y resultado':c.myAnswer?'Ver mi predicción':isDuel(c)&&c.teamAnswer?'Confirmar elección del equipo':'Rellenar la quiniela'}</button>${c.myAnswer?`<p class="pickem-card-answer">Tu pronóstico: <strong>${escape(optionLabel(c,c.myAnswer))}</strong></p>`:''}${result}</article>`;
    }).join('');
    $('pickem-results').hidden=!closed();
    $('pickem-result-list').innerHTML=state.predictions.length?state.predictions.map(b=>{
      const awarded=b.reward?.status==='AWARDED';
      const verdict=awarded?`✓ +${b.reward.shells} caparazón`:b.pending?'Pendiente de resultados':'Sin premio';
      const summary=`<div class="pickem-ballot-summary"><div><strong>${escape(b.author||b.teamName)}</strong><small>${escape(b.teamName)}</small></div><strong>${b.correct} aciertos${b.pending?` · ${b.pending} pendientes`:''}</strong><strong class="${awarded?'pickem-win':b.pending?'pickem-wait':''}">${escape(verdict)}</strong></div>`;
      const answers=state.categories.map(c=>{
        const answer=b.answers[c.id];if(answer===undefined)return '';
        const result=c.result,correct=result?.status==='SETTLED'&&result.optionIds.includes(answer);
        const label=!result?'Pendiente de resultado':result.status!=='SETTLED'?'Sin datos válidos':correct?'✓ Acierto':'No acertó';
        return `<article class="pickem-result-entry"><div>${escape(c.title)}</div><div>${escape(optionLabel(c,answer))}</div><strong class="${correct?'pickem-win':!result?'pickem-wait':''}">${escape(label)}</strong></article>`;
      }).join('');
      return `<section class="pickem-ballot">${summary}${answers}</section>`;
    }).join(''):'<p>Nadie envió una quiniela esta semana.</p>';
    if($('pickem-dialog').open)modal(true);
    controls();
  }
  async function load() {
    if(busy)return;
    const revision=++version;
    try {const result=await request();if(revision===version){state=result;week=state.week;render();}}
    catch(error){if(revision===version)$('pickem-feedback').textContent='No se pudo cargar el Pick’em. Vuelve a intentarlo al actualizar la página.';}
  }
  $('pickem-categories').addEventListener('click',event=>{
    const button=event.target.closest('[data-pickem-category]');if(!button||!state)return;
    currentCategory=button.dataset.pickemCategory;$('pickem-form-error').hidden=true;modal();$('pickem-dialog').showModal();
  });
  $('pickem-close').addEventListener('click',()=>{if(!busy)$('pickem-dialog').close();});
  $('pickem-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  $('pickem-answer').addEventListener('change',controls);
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
