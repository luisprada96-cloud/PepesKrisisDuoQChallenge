/* Match history presentation. Riot statistics stay in the shared database;
   static names/icons are cached here per Data Dragon patch, independently. */
(() => {
  const CDN = 'https://ddragon.leagueoflegends.com';
  const FALLBACK_VERSION = '16.19.1';
  const assets = new Map();
  const roles = {TOP:'Top', JUNGLE:'Jungla', MIDDLE:'Mid', BOTTOM:'ADC', UTILITY:'Support'};
  const spellFallbacks = {1:['SummonerBoost','Limpiar'],3:['SummonerExhaust','Extenuación'],4:['SummonerFlash','Destello'],6:['SummonerHaste','Fantasmal'],7:['SummonerHeal','Curar'],11:['SummonerSmite','Aplastar'],12:['SummonerTeleport','Teleportar'],14:['SummonerDot','Prender'],21:['SummonerBarrier','Barrera'],32:['SummonerSnowball','Marca']};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const number = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value) : null;
  const formatted = value => number(value) === null ? '—' : number(value).toLocaleString('es-ES');
  function staticJson(path) {
    if (!assets.has(path)) {
      assets.set(path, fetch(`${CDN}/${path}`).then(response => {
        if (!response.ok) throw new Error('Static assets unavailable');
        return response.json();
      }).catch(error => { assets.delete(path); throw error; }));
    }
    return assets.get(path);
  }
  async function versionFor(match) {
    const prefix = String(match.gameVersion || '').match(/^(\d+\.\d+)\./)?.[1];
    try {
      const versions = await staticJson('api/versions.json');
      return (prefix && versions.find(v => v.startsWith(`${prefix}.`))) || versions[0] || FALLBACK_VERSION;
    } catch (_) { return FALLBACK_VERSION; }
  }
  function championImage(champion) {
    if (!/^[a-zA-Z0-9_]+$/.test(champion || '') || champion === 'Unknown') return '<span class="match-champion-placeholder" aria-label="Campeón no disponible">?</span>';
    return `<img class="match-champion-image" data-dd-champion="${escape(champion)}" alt="${escape(championDisplayName(champion))}" src="${CDN}/cdn/${FALLBACK_VERSION}/img/champion/${escape(champion)}.png" loading="lazy">`;
  }
  function statsFor(match, key) {
    const stats = match[`${key}Stats`];
    if (stats) return stats;
    if (match.participantsChecked?.[key]) return null;
    const index = key === 'player1' ? 1 : 2;
    const championName = match[`championP${index}`];
    const parts = String(match[`kda${index}`] || '').match(/^(\d+)\/(\d+)\/(\d+)$/);
    if (!championName && !parts) return null;
    return {championName, ...(parts ? {kills:Number(parts[1]),deaths:Number(parts[2]),assists:Number(parts[3])} : {})};
  }
  function kdaText(stats) {
    if (!stats || ['kills','deaths','assists'].some(k => number(stats[k]) === null)) return '—';
    return `${formatted(stats.kills)}/${formatted(stats.deaths)}/${formatted(stats.assists)}`;
  }
  function itemsMarkup(stats) {
    if (!Array.isArray(stats.itemIds) || stats.itemIds.every(id => number(id) === null)) return '<span class="match-missing-data">Objetos no disponibles</span>';
    return stats.itemIds.slice(0,7).map((item, slot) => {
      const id = number(item);
      if (!id) return `<span class="match-item-slot empty ${slot===6?'trinket':''}" aria-label="${slot===6?'Trinket':'Objeto'}: ${id===0?'hueco vacío':'no disponible'}"></span>`;
      return `<button type="button" class="match-item-slot ${slot===6?'trinket':''}" data-dd-item="${id}" aria-label="Objeto ${id}" title="Objeto ${id}"><img alt="" loading="lazy" src="${CDN}/cdn/${FALLBACK_VERSION}/img/item/${id}.png"><span class="match-item-tooltip" role="tooltip">Objeto ${id}</span></button>`;
    }).join('');
  }
  function playerMarkup(match, duo, key) {
    const stats = statsFor(match, key);
    const player = duo[key] || {};
    const name = stats?.riotIdGameName || player.name || player.displayName || (key==='player1'?'Integrante 1':'Integrante 2');
    const tag = stats?.riotIdTagline || player.tag || '';
    if (!stats) return `<section class="match-player match-player-unavailable"><strong>${escape(name)}</strong><span class="match-missing-data">${match.participantsChecked?.[key] ? 'No participó en esta partida' : 'Datos no disponibles'}</span></section>`;
    const completeKda = ['kills','deaths','assists'].every(k => number(stats[k]) !== null);
    const kda = completeKda ? (Number(stats.deaths)===0 ? 'Perfecto' : ((Number(stats.kills)+Number(stats.assists))/Number(stats.deaths)).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' KDA') : '— KDA';
    const kp = completeKda && number(stats.teamKills)>0 ? Math.round((Number(stats.kills)+Number(stats.assists))/Number(stats.teamKills)*100)+'%' : '—';
    const cs = number(stats.cs);
    const csPerMinute = cs!==null && number(match.durationSeconds)>0 ? (cs/(Number(match.durationSeconds)/60)).toLocaleString('es-ES',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
    const spells = (stats.summonerSpellIds || []).slice(0,2).map(value => {
      const id = number(value);
      if (!id) return '';
      const known = spellFallbacks[id];
      return `<span class="match-spell" data-dd-spell="${id}" title="${escape(known?.[1] || `Hechizo ${id}`)}">${known ? `<img src="${CDN}/cdn/${FALLBACK_VERSION}/img/spell/${known[0]}.png" alt="${escape(known[1])}" loading="lazy">` : `<span>?</span>`}</span>`;
    }).join('');
    return `<section class="match-player"><div class="match-player-top"><div class="match-player-identity"><div class="match-portrait">${championImage(stats.championName)}${number(stats.champLevel)!==null ? `<span class="match-level">${formatted(stats.champLevel)}</span>` : ''}</div><div class="match-player-name-block"><strong class="match-player-name" title="${escape(name+(tag?'#'+tag:''))}">${escape(name)}</strong><span class="match-secondary">${escape(championDisplayName(stats.championName) || 'Campeón desconocido')} · ${escape(roles[stats.position] || 'Rol no disponible')}</span></div><div class="match-spells">${spells}</div></div><div class="match-score"><strong class="match-kda">${formatted(stats.kills)} / <span class="deaths">${formatted(stats.deaths)}</span> / <span class="assists">${formatted(stats.assists)}</span></strong><span class="match-secondary">${kda} · ${kp} participación</span></div></div><div class="match-player-bottom"><div class="match-metrics"><div><strong>${formatted(stats.cs)} CS</strong><span>${csPerMinute} por minuto</span></div><div><strong>${formatted(stats.goldEarned)}</strong><span>Oro</span></div><div><strong>${formatted(stats.visionScore)}</strong><span>Visión</span></div></div><div class="match-items" role="group" aria-label="Objetos finales de ${escape(name)}">${itemsMarkup(stats)}</div></div></section>`;
  }
  function matchMarkup(match, duo, index) {
    const stats = ['player1','player2'].map(key=>statsFor(match,key));
    const duration = number(match.durationSeconds)!==null ? `${Math.floor(Number(match.durationSeconds)/60)}:${String(Number(match.durationSeconds)%60).padStart(2,'0')}` : escape(match.duration || '—');
    return `<details class="history-match ${match.result==='LOSS'?'defeat':''}" ${index===0?'open':''}><summary class="history-match-summary"><div class="match-result"><strong class="match-result-label">${match.result==='WIN'?'VICTORIA':match.result==='LOSS'?'DERROTA':'PARTIDA'}</strong><span class="match-secondary">${duration} · Solo/Duo</span></div><div class="match-summary-middle"><div class="match-summary-portraits">${stats.filter(s=>s?.championName).map(s=>championImage(s.championName)).join('')}</div><div><div class="match-summary-kda">${stats.filter(Boolean).map(kdaText).map(escape).join('<span class="match-summary-separator"> · </span>') || '—'}${match.pentaKill?'<span class="match-penta">PENTAKILL</span>':''}</div><span class="match-secondary">${escape(match.date || '')}</span></div></div><span class="match-expand-indicator"><span class="match-show">Detalles</span><span class="match-hide">Menos</span><i class="fa-solid fa-chevron-down" aria-hidden="true"></i></span></summary><div class="match-detail-body">${['player1','player2'].map(key=>playerMarkup(match,duo,key)).join('')}</div></details>`;
  }
  function hydrateImages(element, version) {
    element.querySelectorAll('[data-dd-champion]').forEach(img=>{ img.src=`${CDN}/cdn/${version}/img/champion/${img.dataset.ddChampion}.png`; });
    element.querySelectorAll('[data-dd-item] img').forEach(img=>{ img.src=`${CDN}/cdn/${version}/img/item/${img.parentElement.dataset.ddItem}.png`; });
  }
  async function hydrateDetails(element, version) {
    const results = await Promise.allSettled([staticJson(`cdn/${version}/data/es_ES/item.json`),staticJson(`cdn/${version}/data/es_ES/summoner.json`)]);
    if (!element.isConnected) return;
    const items = results[0].status==='fulfilled' ? results[0].value.data || {} : {};
    const spells = results[1].status==='fulfilled' ? Object.values(results[1].value.data || {}) : [];
    element.querySelectorAll('[data-dd-item]').forEach(button=>{
      const item = items[button.dataset.ddItem];
      const name = item?.name || `Objeto ${button.dataset.ddItem}`;
      button.title=name; button.setAttribute('aria-label',name); button.querySelector('.match-item-tooltip').textContent=name;
      if (/^[a-zA-Z0-9_.-]+$/.test(item?.image?.full || '')) button.querySelector('img').src=`${CDN}/cdn/${version}/img/item/${item.image.full}`;
    });
    element.querySelectorAll('[data-dd-spell]').forEach(slot=>{
      const spell = spells.find(s=>String(s.key)===slot.dataset.ddSpell);
      if (!spell || !/^[a-zA-Z0-9_.-]+$/.test(spell.image?.full || '')) return;
      slot.title=spell.name; const img=document.createElement('img'); img.alt=spell.name;img.loading='lazy';img.src=`${CDN}/cdn/${version}/img/spell/${spell.image.full}`;slot.replaceChildren(img);
    });
  }
  function mount(container, duo, matches) {
    container.innerHTML = matches.length ? matches.map((match,index)=>matchMarkup(match,duo,index)).join('') : '<p class="match-missing-data">Sin partidas clasificatorias recientes.</p>';
    container.querySelectorAll('.history-match').forEach((element,index)=>{
      const version = versionFor(matches[index]);
      let loading = false;
      let loaded = false;
      async function onOpen() {
        if (!element.open || loading || loaded) return;
        loading=true;
        await hydrateDetails(element,await version);
        loading=false;loaded=true;
      }
      version.then(value=>{ if(element.isConnected) hydrateImages(element,value); });
      element.addEventListener('toggle',onOpen);
      onOpen();
    });
  }
  window.MatchHistory = {mount};
})();
