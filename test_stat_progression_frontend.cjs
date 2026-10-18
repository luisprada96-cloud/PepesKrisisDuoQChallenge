// Browser interaction checks use synthetic participants and never contact Riot or production.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1100},hasTouch:true});
    const page = await context.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const players=Array.from({length:18},(_,i)=>{
      const totals={kills:0,deaths:0,assists:0};
      const points=Array.from({length:12+i},(_,n)=>{
        totals.kills+=(i%7)+1+(n*3+i)%5;
        totals.deaths+=1+(i+n)%4;
        totals.assists+=3+(i*2+n*7)%9;
        return {game:n+1,...totals};
      });
      return {id:`team${Math.floor(i/2)}:player${i%2+1}`,name:i===0?'Markel':i===1?'Guille':`Jugador ${String(i+1).padStart(2,'0')}`,teamName:i<2?'ATodoFlash':`Equipo ${Math.floor(i/2)+1}`,points,games:points.length,totals};
    });
    const duos=Array.from({length:9},(_,i)=>({id:`team${i}`,teamName:i===0?'ATodoFlash':`Equipo ${i+1}`,tier:'Gold',division:'IV',lp:20,wins:2,losses:1,blueShells:0,history:[],
      player1:{name:`Account${2*i}`,displayName:players[2*i].name},player2:{name:`Account${2*i+1}`,displayName:players[2*i+1].name}}));
    let payload={players,pendingMatches:0};
    let failed=false,chartReads=0,mutations=0;
    const files=new Set(['index.html','data.js','alerts.js','match-history.js','app.js','stat-progression.js','styles.css']);
    await context.route('**/*',route=>{
      const request=route.request(), url=new URL(request.url());
      if(url.origin!=='http://progression.test')return route.abort();
      if(url.pathname.startsWith('/api/')){
        if(request.method()!=='GET')mutations++;
        let data=[];
        if(url.pathname==='/api/stats/progression'){
          chartReads++;
          if(failed)return route.abort();
          data=payload;
        }else if(url.pathname==='/api/duos')data=duos;
        else if(url.pathname==='/api/config')data={startDate:'2026-10-15T00:00:00+02:00',endDate:'2030-11-15',challengeTitle:'Vista de prueba'};
        else if(url.pathname==='/api/sync/status')data={};
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
      }
      const filename=url.pathname==='/'?'index.html':url.pathname.slice(1);
      if(!files.has(filename))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,filename))});
    });
    await page.goto('http://progression.test/');
    const card=page.locator('.stat-progression-section');
    await card.locator('[data-series-path]').first().waitFor();
    assert.equal(await card.locator('[data-series-path]').count(),18);
    assert.equal(await card.locator('#stat-progression-legend button').count(),18);
    assert.equal(await page.evaluate(()=>{
      const stats=document.querySelector('.fun-stats-section'),graph=document.querySelector('.stat-progression-section'),best=document.querySelector('.best-matches-section');
      return !!(stats.compareDocumentPosition(graph)&Node.DOCUMENT_POSITION_FOLLOWING)&&!!(graph.compareDocumentPosition(best)&Node.DOCUMENT_POSITION_FOLLOWING);
    }),true);
    const first=card.locator('[data-series-path]').first();
    const killsPath=await first.getAttribute('d'),firstColor=await first.getAttribute('stroke');
    const beforeToggle=chartReads;
    await card.getByRole('tab',{name:'Asistencias',exact:true}).click();
    assert.notEqual(await first.getAttribute('d'),killsPath);
    assert.equal(await first.getAttribute('stroke'),firstColor);
    assert.match(await card.locator('svg').getAttribute('aria-label'),/Asistencias acumuladas/);
    await card.getByRole('tab',{name:'Muertes',exact:true}).click();
    assert.match(await card.locator('svg').getAttribute('aria-label'),/Muertes acumuladas/);
    assert.equal(await card.locator('[role="tab"][aria-selected="true"]').count(),1);
    assert.equal(chartReads,beforeToggle,'metric toggles reuse the same three-metric payload');
    await card.getByRole('tab',{name:'Kills',exact:true}).click();
    await card.scrollIntoViewIfNeeded();
    const target=card.locator('[data-series-path][data-series-id="team8:player2"]');
    const position=await target.evaluate(path=>{
      const point=path.getPointAtLength(path.getTotalLength()*.997),matrix=path.getScreenCTM();
      return {x:point.x*matrix.a+point.y*matrix.c+matrix.e,y:point.x*matrix.b+point.y*matrix.d+matrix.f};
    });
    await page.mouse.move(position.x,position.y);
    await card.locator('#stat-progression-tooltip').waitFor({state:'visible'});
    assert.match(await card.locator('#stat-progression-tooltip').textContent(),/Jugador 18.*Partida 29/);
    assert.equal(await target.evaluate(el=>el.style.strokeWidth),'3.8');
    assert.equal(await first.evaluate(el=>el.style.opacity),'0.16');
    const preview=path.join(__dirname,'preview');fs.mkdirSync(preview,{recursive:true});
    await card.screenshot({path:path.join(preview,'stat-progression-desktop.png')});
    await page.mouse.move(5,5);
    await card.screenshot({path:path.join(preview,'stat-progression-overview.png')});
    await card.getByRole('tab',{name:'Kills',exact:true}).focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await card.getByRole('tab',{name:'Asistencias',exact:true}).getAttribute('aria-selected'),'true');
    const legend=card.locator('#stat-progression-legend button').first();
    await legend.focus();
    assert.match(await card.locator('#stat-progression-detail').textContent(),/Markel.*Partida 12/);
    await legend.click();
    assert.equal(await legend.getAttribute('aria-pressed'),'true');
    await page.keyboard.press('Escape');
    assert.equal(await legend.getAttribute('aria-pressed'),'false');
    payload={players,pendingMatches:2};
    await page.evaluate(()=>StatProgression.refresh());
    assert.match(await card.locator('#stat-progression-status').textContent(),/pendientes de completar/);
    assert.equal(await card.getByRole('tab',{name:'Asistencias',exact:true}).getAttribute('aria-selected'),'true');
    failed=true;
    await page.evaluate(()=>StatProgression.refresh());
    assert.equal(await card.locator('[data-series-path]').count(),18,'a failed refresh retains the last confirmed curves');
    failed=false;
    await page.setViewportSize({width:390,height:844});
    await legend.tap();
    assert.equal(await legend.getAttribute('aria-pressed'),'true');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true);
    await card.screenshot({path:path.join(preview,'stat-progression-mobile.png')});
    const saved=payload;
    payload={players:players.map(p=>({...p,points:[],games:0})),pendingMatches:0};
    await page.evaluate(()=>StatProgression.refresh());
    assert.equal(await card.locator('svg').count(),0);
    assert.match(await card.locator('#stat-progression-plot').textContent(),/primeras partidas/);
    payload=saved;
    const escaped=structuredClone(saved);escaped.players[0].name='<img src=x onerror="window.chartInjected=true">';payload=escaped;
    await page.evaluate(()=>StatProgression.refresh());
    assert.equal(await card.locator('#stat-progression-legend img').count(),0);
    assert.equal(await page.evaluate(()=>window.chartInjected),undefined);
    failed=true;
    const retryPage=await context.newPage();retryPage.on('pageerror',e=>errors.push(e.message));
    await retryPage.goto('http://progression.test/');
    await retryPage.getByRole('button',{name:'Reintentar',exact:true}).waitFor();
    failed=false;payload=saved;
    await retryPage.getByRole('button',{name:'Reintentar',exact:true}).click();
    await retryPage.locator('[data-series-path]').first().waitFor();
    assert.equal(await retryPage.locator('[data-series-path]').count(),18);
    assert.equal(mutations,0,'the chart never starts Riot or changes tournament data');
    assert.deepEqual(errors,[]);
    console.log('Progression browser checks passed: 18 lines, totals, hover, toggles, stable colors, keyboard, touch, offline, retry, empty state and escaped labels.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
