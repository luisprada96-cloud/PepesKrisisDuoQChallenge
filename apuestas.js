/* Team gold markets. The server owns balances, receipts, timers and results. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const token = () => {try{return sessionStorage.getItem('pepes_player_token')||'';}catch(_){return '';}};
  const metrics = {kills:'kills',deaths:'muertes',assists:'asistencias'};
  const sides = {WIN:'WIN',LOSS:'LOSE',OVER:'Más de',UNDER:'Menos de'};
  const when = value => new Intl.DateTimeFormat('es-ES',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'}).format(new Date(value*1000));
  let state=null, busy=false, page=0, view='open', version=0, confirmation=null, lastAttempt=null;
  const dialog=$('bet-confirm');
  const team = id => state?.teams.find(d=>d.id===id);
  const lineLabel = market => (market.lineHalf/2).toFixed(1).replace('.',',');
  function title(market) {
    return market.metric==='result' ? `${market.teamName}: ¿WIN o LOSE en la próxima partida?`
      : `${market.playerName}: ${lineLabel(market)} ${metrics[market.metric]}`;
  }
  function fieldState() {
    const numerical=$('bet-metric').value!=='result';
    $('bet-player-fields').hidden=!numerical;$('bet-line-fields').hidden=!numerical;
    $('bet-player').required=numerical;$('bet-line').required=numerical;
    const selected=team($('bet-target').value),key=$('bet-player').value;
    const signature=JSON.stringify(selected?.players||[]);
    if($('bet-player').dataset.signature!==signature){
      $('bet-player').replaceChildren(new Option('Selecciona un integrante',''),...(selected?.players||[]).map(p=>new Option(p.name,p.key)));
      $('bet-player').dataset.signature=signature;
      if(selected?.players.some(p=>p.key===key))$('bet-player').value=key;
    }
    const player=selected?.players.find(p=>p.key===$('bet-player').value);
    const side=sides[$('bet-side').value],line=$('bet-line').value;
    $('bet-preview').textContent=numerical
      ? `${player?.name||'Elige un integrante'} · ${side} ${line||'…'} ${metrics[$('bet-metric').value]} · ${selected?.name||'Elige un equipo'}`
      : selected ? `Apuestas a WIN en la próxima partida de ${selected.name}.` : 'Elige un equipo para preparar tu apuesta a WIN.';
    $('bet-create').disabled=busy||!state?.wallet;
    $('bet-amount').max=String(state?.wallet?.balance||0);
    document.querySelectorAll('[data-bet-join]').forEach(button=>button.disabled=busy||!state?.wallet||state.wallet.balance<1||state.markets.find(m=>m.id===button.dataset.betJoin)?.status!=='OPEN');
    $('bets-previous').disabled=busy||page===0;
    $('bets-next').disabled=busy||(page+1)*12>=(state?.total||0);
    document.querySelectorAll('[data-bets-view]').forEach(button=>button.disabled=busy);
    $('bet-confirm-submit').disabled=busy;
    $('bet-confirm-cancel').disabled=busy;
  }
  function render() {
    if(!state)return;
    $('bets-login').hidden=!!state.wallet;
    $('bets-team-name').textContent=state.wallet?.teamName||'Inicia sesión para usar el oro de tu equipo';
    $('bets-balance').innerHTML=`${state.wallet?esc(state.wallet.balance):'—'} <small>oro disponible</small>`;
    $('bets-reserved').textContent=state.wallet?state.wallet.reserved:'—';
    const selected=$('bet-target').value;
    const signature=JSON.stringify(state.teams);
    if($('bet-target').dataset.signature!==signature){
      $('bet-target').replaceChildren(new Option('Selecciona un equipo',''),...state.teams.map(t=>new Option(t.name,t.id)));
      if(state.teams.some(t=>t.id===selected))$('bet-target').value=selected;
      $('bet-target').dataset.signature=signature;
    }
    $('bets-markets').innerHTML=state.markets.length ? state.markets.map(m=>{
      const labels=m.metric==='result'?['WIN','LOSS']:['OVER','UNDER'];
      const roundList=m.rounds||(m.lastRound?[m.lastRound]:[]);
      const resultMarkup=result=>`<p class="bet-result">${result.status==='REFUNDED' ? result.reason==='target_changed'?'Oro devuelto: cambió el equipo o el integrante.':'Oro devuelto: no había apuestas en ambos lados.' : `Resultado: ${esc(sides[result.winner])}${m.metric==='result'?'':` · ${result.value} ${metrics[m.metric]}`} · Bote repartido: ${result.pool} 🪙`}</p>${result.matchId?`<span class="bet-evidence">Partida ${esc(result.matchId)} · recibida ${esc(when(result.receivedAt))}</span>`:''}`;

      const mine=m.mine.length?`<details class="bet-mine" open><summary>Oro de mi equipo · ${m.mine.length} ${m.mine.length===1?'apuesta':'apuestas'}</summary>${m.mine.map(b=>`<p>${esc(sides[b.side])} · ${b.amount} 🪙 · ${b.status==='PENDING' ? b.waitingMatchId ? 'Esperando estadísticas de la partida asignada' : `Puede contar desde ${esc(when(b.eligibleAt))}` : `Resuelta · ${b.payout} 🪙 recibidos en el saldo${b.matchId?` · ${esc(b.matchId)}`:''}`}</p>`).join('')}</details>`:'';
      return `<article class="bet-card" data-market="${esc(m.id)}"><div class="bet-card-top"><span class="bet-card-badge">${m.status==='OPEN'?'Abierta':'Resuelta'}</span><span>${m.participants} equipos pendientes</span></div><h3>${esc(title(m))}</h3><p class="bet-card-target">${esc(m.teamName)} · Próxima partida recibida tras tu espera de 20 min</p><div class="bet-sides">${labels.map(side=>`<button type="button" class="bet-side" data-bet-join="${esc(m.id)}" data-side="${side}" ${m.status!=='OPEN'?'disabled':''}><span>${esc(sides[side])}${m.metric==='result'?'':` ${esc(lineLabel(m))}`}</span><b>${m.sides[side]} 🪙</b></button>`).join('')}</div>${roundList.length>1?`<details class="bet-mine"><summary>${roundList.length} partidas resueltas</summary>${roundList.map(resultMarkup).join('')}</details>`:roundList.map(resultMarkup).join('')}${mine}</article>`;
    }).join('') : `<p class="bets-empty">${view==='open'?'Todavía no hay apuestas abiertas. Crea la primera.':'Las apuestas resueltas aparecerán aquí, con su partida y resultado.'}</p>`;
    $('bets-page-info').textContent=`${state.total} ${state.total===1?'mercado':'mercados'} · Página ${page+1}`;
    fieldState();
  }
  async function request(body) {
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try {
      const session=token();
      const response=await fetch(`${API_BASE_URL}/bets${body?'':`?view=${view}&offset=${page*12}&limit=12`}`,{
        credentials:'same-origin',signal:controller.signal,
        headers:{...(session?{Authorization:`Bearer ${session}`} :{}),...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{method:'POST',body:JSON.stringify(body)}:{})});
      const result=await response.json();
      if(!response.ok){const error=new Error(result.error||'No se pudo completar la apuesta.');error.status=response.status;throw error;}
      return result;
    }finally{clearTimeout(timeout);}
  }
  async function refresh() {
    if(busy||dialog.open||document.hidden)return;
    const revision=++version;
    try {
      const result=await request();
      if(revision!==version||busy)return;
      if(!Array.isArray(result.markets)||!Array.isArray(result.teams))throw new Error('Respuesta inválida');
      state=result;render();
      $('bets-feedback').textContent='';
    }catch(_){$('bets-feedback').textContent='No se ha podido actualizar el mercado. Se conservan los últimos datos y se reintentará.';}
  }
  function amount(value) {
    if(!/^[1-9][0-9]*$/.test(value)||Number(value)>1000000)throw new Error('Introduce un número entero de monedas, como mínimo 1.');
    const number=Number(value);
    if(number>(state?.wallet?.balance||0))throw new Error('No tienes suficiente oro disponible.');
    return number;
  }
  function openConfirmation(body,description,creating) {
    confirmation={body,creating};
    $('bet-confirm-title').textContent=creating?'Crear apuesta':'Participar en la apuesta';
    $('bet-confirm-description').textContent=description;
    $('bet-join-amount').value=creating?String(body.amount):'';
    $('bet-join-amount').max=String(state.wallet.balance);
    $('bet-confirm-time').textContent='Tu oro quedará reservado. Se saltarán las partidas recibidas durante los 20 minutos posteriores a la confirmación. Si tu bote no tiene apuestas en ambos lados, se devuelve el oro.';
    $('bet-confirm-error').hidden=true;
    dialog.showModal();$('bet-join-amount').focus();
  }
  $('bets-form').addEventListener('submit',event=>{
    event.preventDefault();if(busy||!state?.wallet)return;
    $('bet-form-error').hidden=true;
    try {
      const metric=$('bet-metric').value,targetId=$('bet-target').value,selected=team(targetId);
      if(!selected)throw new Error('Selecciona un equipo.');
      const body={action:'create',metric,targetId,amount:amount($('bet-amount').value)};
      let description=`${selected.name} · Próxima partida · WIN`;
      if(metric!=='result'){
        const player=selected.players.find(p=>p.key===$('bet-player').value);
        if(!player)throw new Error('Selecciona un integrante.');
        const line=$('bet-line').value.replace('.',',');
        if(!/^(?:0|[1-9][0-9]?),5$/.test(line)||Number(line.replace(',','.'))>50)throw new Error('La línea debe terminar en ,5 y estar entre 0,5 y 49,5.');
        Object.assign(body,{playerKey:player.key,line,side:$('bet-side').value});
        description=`${selected.name} · ${player.name} · ${sides[body.side]} ${line} ${metrics[metric]}`;
      }
      openConfirmation(body,description,true);
    }catch(error){$('bet-form-error').textContent=error.message;$('bet-form-error').hidden=false;}
  });
  $('bets-markets').addEventListener('click',event=>{
    const button=event.target.closest('[data-bet-join]');
    if(!button||busy||!state?.wallet||button.disabled)return;
    const market=state.markets.find(m=>m.id===button.dataset.betJoin);
    if(!market)return;
    openConfirmation({action:'join',marketId:market.id,side:button.dataset.side},`${title(market)} · ${sides[button.dataset.side]}`,false);
  });
  $('bet-confirm-cancel').addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.querySelector('form').addEventListener('submit',event=>{event.preventDefault();$('bet-confirm-submit').click();});
  $('bet-confirm-submit').addEventListener('click',async()=>{
    if(busy||!confirmation)return;
    $('bet-confirm-error').hidden=true;
    try {
      const body={...confirmation.body,amount:amount($('bet-join-amount').value)};
      const signature=JSON.stringify(body);
      if(!lastAttempt||lastAttempt.signature!==signature)lastAttempt={signature,requestId:crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('')};
      body.requestId=lastAttempt.requestId;
      busy=true;++version;fieldState();
      const result=await request(body);
      lastAttempt=null;state=result;page=0;view='open';
      document.querySelectorAll('[data-bets-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.betsView===view));
      dialog.close();confirmation=null;render();
      $('bets-feedback').textContent='Apuesta confirmada. El oro está reservado; su hora mínima aparece en la tarjeta.';
    }catch(error){
      if(error.status>=400&&error.status<500)lastAttempt=null;
      $('bet-confirm-error').textContent=(!busy||error.status)?error.message:'No se ha podido confirmar el envío. Reintenta con los mismos datos: no se cobrará dos veces.';
      $('bet-confirm-error').hidden=false;
    }finally{busy=false;fieldState();}
  });
  for(const id of ['bet-metric','bet-target','bet-player','bet-side','bet-amount'])$(id).addEventListener('change',fieldState);
  $('bet-line').addEventListener('input',()=>{
    let value=$('bet-line').value.replace('.',',').replace(/[^0-9,]/g,'');
    const parts=value.split(',');value=parts[0].slice(0,2)+(parts.length>1?','+parts.slice(1).join('').slice(0,1):'');
    $('bet-line').value=value;fieldState();
  });
  document.querySelectorAll('[data-bets-view]').forEach(button=>button.addEventListener('click',()=>{
    if(busy)return;view=button.dataset.betsView;page=0;
    document.querySelectorAll('[data-bets-view]').forEach(b=>b.setAttribute('aria-pressed',b===button));refresh();
  }));
  $('bets-previous').addEventListener('click',()=>{if(!busy&&page>0){page--;refresh();}});
  $('bets-next').addEventListener('click',()=>{if(!busy){page++;refresh();}});
  document.addEventListener('player-session-changed',refresh);
  document.addEventListener('player-session-ended',()=>{if(state){state.wallet=null;render();}refresh();});
  window.addEventListener('focus',refresh);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  async function poll(){try{await refresh();}finally{setTimeout(poll,10000);}}
  fieldState();poll();
})();
