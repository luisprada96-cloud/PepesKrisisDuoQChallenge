// Pick'em UI against an isolated API: no real accounts, votes or Riot requests.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1050}});
    const options = [{id:'0-19',label:'Menos de 20'}, ...Array.from({length:10},(_,i)=>({id:`${20+i*10}-${29+i*10}`,label:`${20+i*10}–${29+i*10}`})), {id:'120+',label:'120 o más'}];
    let saved = {}, author = '', closed = false, fail = false, calls = [];
    const future = Date.now()/1000+86400, errors = [];
    await context.route('**/*', async route => {
      const request=route.request(), url=new URL(request.url());
      if(url.origin!=='http://pepes.test')return route.abort();
      const logged=request.headers().authorization==='Bearer team-session';
      if(url.pathname==='/api/pickem') {
        if(request.method()==='POST') {
          if(fail)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudo guardar. Prueba otra vez.'})});
          const body=request.postDataJSON();
          assert.equal(logged,true); assert.equal(saved[body.categoryId],undefined);
          assert.equal(body.week,'2026-10-12');
          calls.push(body); saved[body.categoryId]=body.optionId; author=body.author;
        }
        const categories=[
          {id:'unique_champions',title:'¿Cuántos campeones distintos se jugarán?',description:'Los campeones de los participantes, sin repetir.',placeholder:'Selecciona un rango',options},
          {id:'weekly_leader',title:'¿Qué equipo terminará primero esta semana?',description:'ELO al cierre semanal.',placeholder:'Selecciona un equipo',icon:'🏆',options:[{id:'a',label:'Equipo A'},{id:'b',label:'Equipo B'}]},
          {id:'best_game_kda',title:'¿Quién hará la partida con mejor KDA?',description:'Mejor partida individual.',placeholder:'Selecciona un jugador',icon:'⚔',options:[{id:'a1',label:'A1 · Equipo A'},{id:'a2',label:'A2 · Equipo A'},{id:'b1',label:'B1 · Equipo B'},{id:'b2',label:'B2 · Equipo B'}]}
        ].map(c=>({...c,reward:1,myAnswer:logged?saved[c.id]||null:null,
          result:closed?{status:'SETTLED',value:c.id==='unique_champions'?32:20,summary:c.id==='unique_champions'?'32 campeones distintos':c.id==='weekly_leader'?'Primer puesto · Gold IV · 50 LP':'Mejor partida individual · 20.00 KDA',optionLabel:c.id==='unique_champions'?'30–39':c.id==='weekly_leader'?'Equipo B':'A2 · Equipo A',winners:[{ballotId:'mine'}]}:null}));
        const hasBallot=Object.keys(saved).length>0;
        const state={week:url.searchParams.get('week')||'2026-10-12',weeks:['2026-10-19','2026-10-12'],startsAt:future-86400*4,endsAt:future+60,closesAt:closed?1:future,closed,categories,
          entries:hasBallot?1:0,myBallot:logged&&hasBallot?{author,answers:saved}:null,
          participation:{teamId:logged?'a':null,teamName:logged?'Equipo A':null,canAnswer:logged&&!closed,message:closed?'Las predicciones están cerradas.':logged?'Participando como Equipo A.':'Inicia sesión con tu equipo para rellenar la quiniela.'},
          predictions:closed?[{id:'mine',teamId:'a',teamName:'Equipo A',author:'<img src=x onerror="window.injected=true">',answers:saved}]:[]};
        return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
      }
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:'{}'});
      const file=url.pathname.slice(1);
      if(!['pickem.html','pickem.js','pickem.css','styles.css','data.js','alerts.js'].includes(file))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page = await context.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://pepes.test/pickem.html');
    const card=page.locator('[data-pickem-category="unique_champions"]');
    await card.waitFor();
    assert.equal(await page.locator('[data-pickem-category]').count(),3,'all three categories are active');
    await card.click();
    assert.equal(await page.locator('#pickem-dialog').isVisible(),true);
    assert.equal(await page.locator('#pickem-answer option').count(),13);
    await page.locator('#pickem-answer').selectOption('120+');
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true,'guests can preview only');
    await page.locator('#pickem-form').dispatchEvent('submit');
    assert.equal(calls.length,0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#pickem-dialog').isVisible(),false);
    await page.evaluate(()=>{sessionStorage.setItem('pepes_player_token','team-session');window.dispatchEvent(new Event('focus'));});
    await page.waitForFunction(()=>document.getElementById('pickem-participation').textContent.includes('Equipo A'));
    await card.click();
    await page.locator('#pickem-answer').selectOption('30-39');
    await page.locator('#pickem-author').fill('Luis');
    assert.equal(await page.locator('#pickem-submit').isEnabled(),true);
    // Background refresh must retain an unsent choice and optional author.
    await Promise.all([page.waitForResponse(r=>r.url().includes('/api/pickem')),page.evaluate(()=>window.dispatchEvent(new Event('focus')))]);
    assert.equal(await page.locator('#pickem-answer').inputValue(),'30-39');
    assert.equal(await page.locator('#pickem-author').inputValue(),'Luis');
    if(process.env.PICKEM_MODAL_SCREENSHOT)await page.screenshot({path:process.env.PICKEM_MODAL_SCREENSHOT});
    fail=true;
    await page.locator('#pickem-submit').click();
    await page.waitForFunction(()=>document.getElementById('pickem-form-error').textContent.includes('No se pudo guardar'));
    assert.equal(await page.locator('#pickem-dialog').isVisible(),true);
    assert.equal(await page.locator('#pickem-answer').inputValue(),'30-39');
    await page.waitForFunction(()=>!document.getElementById('pickem-submit').disabled);
    fail=false;
    await page.locator('#pickem-submit').click();
    await page.waitForFunction(()=>document.getElementById('pickem-feedback').textContent.includes('Predicción guardada'));
    assert.equal(calls.length,1); assert.equal(calls[0].author,'Luis');
    assert.deepEqual(Object.keys(calls[0]).sort(),['author','categoryId','optionId','week']);
    assert.equal(await page.locator('#pickem-dialog').isVisible(),false);
    await card.click();
    assert.equal(await page.locator('#pickem-answer').inputValue(),'30-39');
    assert.equal(await page.locator('#pickem-answer').isDisabled(),true);
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true);
    await page.locator('#pickem-form').dispatchEvent('submit');
    assert.equal(calls.length,1,'cannot change a submitted prediction');
    await page.keyboard.press('Escape');
    for(const [id,option,count,placeholder] of [['weekly_leader','b',3,'Selecciona un equipo'],['best_game_kda','a2',5,'Selecciona un jugador']]) {
      await page.locator(`[data-pickem-category="${id}"]`).click();
      assert.equal(await page.locator('#pickem-answer option').count(),count);
      assert.equal(await page.locator('#pickem-answer option').first().textContent(),placeholder);
      assert.equal(await page.locator('#pickem-author').inputValue(),'Luis');
      assert.equal(await page.locator('#pickem-author').isDisabled(),true);
      await page.locator('#pickem-answer').selectOption(option);
      await page.locator('#pickem-submit').click();
      await page.waitForFunction(()=>!document.getElementById('pickem-dialog').open);
      assert.equal(await page.locator('#pickem-entries').textContent(),'1 quiniela enviada','categories share the same ballot');
    }
    assert.equal(calls.length,3);
    closed=true;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForSelector('.pickem-result-entry');
    assert.match(await page.locator('.pickem-card-result').nth(0).textContent(),/32 campeones distintos/);
    assert.match(await page.locator('.pickem-card-result').nth(1).textContent(),/Equipo B/);
    assert.match(await page.locator('.pickem-card-result').nth(2).textContent(),/20.00 KDA/);
    assert.equal(await page.locator('.pickem-result-entry').count(),3);
    assert.match(await page.locator('.pickem-result-entry').first().textContent(),/\+1 caparazón/);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    await Promise.all([page.waitForResponse(r=>r.url().includes('week=2026-10-19')),page.locator('#pickem-week').selectOption('2026-10-19')]);
    for(const width of [1440,1100,768,390,320]) {
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`no horizontal overflow at ${width}`);
      await card.click();
      const box=await page.locator('#pickem-dialog').boundingBox();
      assert.ok(box.x>=0&&box.x+box.width<=width,`modal fits ${width}`);
      await page.keyboard.press('Escape');
    }
    assert.deepEqual(errors,[]);
    console.log('Pick’em browser checks passed: ranges, guest preview, auth, saved choice, failed save, immutable answer, results, week selector, XSS and 5 screen sizes.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
