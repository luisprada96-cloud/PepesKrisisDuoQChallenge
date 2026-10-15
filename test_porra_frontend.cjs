// Final porra UI with isolated APIs, no production accounts or publications.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1500}});
    const names=['ATodoFlash','LosELOgidos','Marx&Mises','NocturnidadYGunthervosia','Pat@rrota','Supersalidos','TILTanic','TriperosGAP','VaporesEnElC2'];
    const images=['atodoflash','loselogidos','marx-mises','nocturnidad','patarrota','supersalidos','tiltanic','triperosgap','vapores'];
    const items=names.map((name,i)=>({id:'team-'+i,name,image:'/assets/tierlist/'+images[i]+'.png'}));
    const ids=items.map(i=>i.id);
    let posts=Array.from({length:13},(_,i)=>({id:'post-'+i,teamId:'team-'+(i%9),teamName:names[i%9],author:i?'Participante '+i:'<img src=x onerror="window.injected=true">',createdAt:1792000000-i,order:[...ids]}));
    let published=false,fail=false,finished=false,requests=[];
    const errors=[];
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname==='/api/final-predictions'){
        const logged=req.headers().authorization==='Bearer team-session';
        let offset=Number(url.searchParams.get('offset')||0);
        if(req.method()==='POST'){
          if(fail)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudo guardar el pronóstico.'})});
          assert.ok(logged&&!published);
          const body=req.postDataJSON();requests.push(body);published=true;offset=0;
          assert.equal(body.order.length,9);assert.equal(new Set(body.order).size,9);
          posts.unshift({id:'mine',teamId:'team-2',teamName:names[2],author:body.author,createdAt:1792001000,order:body.order});
        }
        const actual=[...ids].reverse();
        const result=finished?{order:actual,rows:actual.map((id,i)=>({id,name:items.find(t=>t.id===id).name,position:i+1,elo:'Gold IV · 30 LP'})),settledAt:1900000000}:null;
        const visible=posts.slice(offset,offset+6).map(p=>({...p,comparison:finished?{status:'SETTLED',exact:p.order.filter((id,i)=>actual[i]===id).length,total:9,positions:p.order.map((id,i)=>({teamId:id,predicted:i+1,actual:actual.indexOf(id)+1,correct:actual[i]===id}))}:null}));
        return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,items,posts:visible,total:posts.length,offset,limit:6,result,publishing:{teamId:logged?'team-2':null,teamName:logged?names[2]:null,canPublish:logged&&!published,reason:!logged?'login':published?'browser':'ready',message:!logged?'Inicia sesión con tu equipo para publicar.':published?'Ya has publicado tu pronóstico desde este navegador.':'Publicando como Marx&Mises.'}})});
      }
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:'{}'});
      const file=url.pathname.slice(1);
      if(!['porra.html','porra.js','porra.css','navigation.js','styles.css','data.js','alerts.js'].includes(file)&&!file.startsWith('assets/tierlist/'))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.png')?'image/png':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://pepes.test/porra.html');
    await page.waitForSelector('[data-porra-post]');
    assert.equal(await page.locator('[data-porra-post]').count(),6);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    assert.match(await page.locator('[data-porra-post] time').first().textContent(),/Publicado el.*2026.*Madrid/);
    await page.locator('#porra-next').click();
    await page.waitForFunction(()=>document.getElementById('porra-page-info').textContent==='Página 2 de 3');
    await page.locator('#porra-next').click();
    await page.waitForFunction(()=>document.getElementById('porra-page-info').textContent==='Página 3 de 3');
    assert.equal(await page.locator('[data-porra-post]').count(),1);
    await page.locator('[data-porra-expand]').click();
    assert.ok(await page.locator('#porra-detail').isVisible());
    assert.equal(await page.locator('#porra-detail .rp-team').count(),9);
    await page.keyboard.press('Escape');
    await page.locator('.rp-switch [data-porra-view="editor"]').click();
    assert.equal(await page.locator('[data-porra-team]').count(),9);
    assert.ok(await page.locator('#porra-publish').isDisabled());
    await page.locator('[data-team="team-0"][data-porra-shift="1"]').click();
    assert.equal(await page.locator('[data-position="0"]').getAttribute('data-porra-team'),'team-1');
    await page.locator('[data-porra-team="team-6"]').dragTo(page.locator('[data-porra-team="team-7"]'));
    assert.equal(await page.locator('[data-position="7"]').getAttribute('data-porra-team'),'team-6');
    await page.locator('#porra-author').fill('Mi porra');
    const before=await page.evaluate(()=>JSON.parse(localStorage.getItem('pepes_final_prediction_draft_v1')).order);
    await page.reload();
    await page.waitForSelector('[data-porra-team]');
    assert.equal(await page.locator('#porra-author').inputValue(),'Mi porra');
    assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('pepes_final_prediction_draft_v1')).order),before);
    await page.evaluate(()=>{sessionStorage.setItem('pepes_player_token','team-session');document.dispatchEvent(new Event('player-session-changed'));});
    await page.waitForFunction(()=>!document.getElementById('porra-publish').disabled);
    await page.locator('#porra-author').fill('Mi apuesta');
    await Promise.all([page.waitForResponse(r=>r.url().includes('/api/final-predictions')),page.evaluate(()=>window.dispatchEvent(new Event('focus')))]);
    assert.equal(await page.locator('#porra-author').inputValue(),'Mi apuesta');
    fail=true;
    await page.locator('#porra-publish').click();
    await page.waitForSelector('#porra-form-error:not([hidden])');
    assert.match(await page.locator('#porra-form-error').textContent(),/No se pudo guardar/);
    assert.equal(requests.length,0);
    fail=false;
    await page.waitForFunction(()=>!document.getElementById('porra-publish').disabled);
    await page.locator('#porra-publish').click();
    await page.waitForSelector('[data-porra-post="mine"]');
    assert.equal(requests.length,1);
    assert.equal(requests[0].author,'Mi apuesta');
    assert.deepEqual(requests[0].order,before);
    assert.match(await page.locator('[data-porra-post="mine"] time').textContent(),/Madrid/);
    finished=true;
    await page.locator('#porra-refresh').click();
    await page.waitForFunction(()=>document.getElementById('porra-result-status').textContent.includes('Torneo finalizado'));
    await page.locator('[data-porra-post="mine"] [data-porra-expand]').click();
    assert.equal(await page.locator('#porra-detail .rp-result-row').count(),10);
    assert.match(await page.locator('#porra-detail .rp-score').textContent(),/\/ 9/);
    for(const width of [1440,1100,768,390,320]){
      await page.setViewportSize({width,height:1000});
      const box=await page.locator('#porra-detail').boundingBox();
      assert.ok(box.x>=0&&box.x+box.width<=width,'dialog fits '+width);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page fits '+width);
    }
    await page.keyboard.press('Escape');
    await page.locator('.rp-switch [data-porra-view="editor"]').click();
    assert.ok(await page.locator('#porra-publish').isDisabled());
    await page.locator('#porra-form').dispatchEvent('submit');
    assert.equal(requests.length,1,'quota also protects repeat submission');
    await page.evaluate(()=>{sessionStorage.removeItem('pepes_player_token');document.dispatchEvent(new Event('player-session-ended'));});
    await page.waitForFunction(()=>!document.getElementById('porra-login').hidden);
    assert.deepEqual(errors,[]);
    console.log('Porra browser checks passed: podium, drag, arrows, draft, auth, dates, pagination, save failure, publication, final comparison, XSS and five widths.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
