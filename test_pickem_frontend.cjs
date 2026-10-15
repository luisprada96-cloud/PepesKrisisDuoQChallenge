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
    let saved = {}, author = '', closed = false, fail = false, calls = [], correct = 9, pending = 0, awarded = true, sharedDuel = null, sharedKills = null;
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
          {id:'best_game_kda',title:'¿Quién hará la partida con mejor KDA?',description:'Mejor partida individual.',placeholder:'Selecciona un jugador',icon:'⚔',options:[{id:'a1',label:'A1 · Equipo A'},{id:'a2',label:'A2 · Equipo A'},{id:'b1',label:'B1 · Equipo B'},{id:'b2',label:'B2 · Equipo B'}]},
          {id:'first_five_negative',title:'¿Cuántos dúos tendrán winrate negativo en sus primeras 5 ranked?',description:'Las cinco primeras ranked del torneo.',placeholder:'Selecciona cuántos dúos',icon:'📉',eventLabel:'ESTRENO DEL TORNEO',options:Array.from({length:10},(_,i)=>({id:String(i),label:String(i)}))},
          {id:'first_individual_shell',title:'¿Quién conseguirá el primer pepazo individual del torneo?',description:'Primer jugador con pentakill, 20+ kills, 30+ asistencias o KDA perfecto.',placeholder:'Selecciona un jugador',icon:'🐢',eventLabel:'ESTRENO DEL TORNEO',options:Array.from({length:18},(_,i)=>({id:'person'+i,label:'Persona '+i+' · Equipo '+Math.floor(i/2)}))},
          {id:'joji_parradise_deaths',kind:'duel',sharedWithTeam:true,teamAnswer:logged?(sharedDuel||saved.joji_parradise_deaths||null):null,title:'¿Quién morirá más: Joji o Parradise?',description:'Muertes acumuladas en la primera semana. En empate, ambas respuestas valen.',placeholder:'Selecciona a Joji o Parradise',icon:'💀',eventLabel:'EVENTO · PRIMERA SEMANA',options:[{id:'joji',label:'Joji'},{id:'parradise',label:'Parradise'}]},
          {id:'first_week_last',title:'¿Qué equipo quedará último la primera semana?',description:'Menor ELO al cierre de la primera semana.',placeholder:'Selecciona un equipo',icon:'🪦',eventLabel:'ESTRENO DEL TORNEO',options:Array.from({length:9},(_,i)=>({id:String.fromCharCode(97+i),label:'Equipo '+String.fromCharCode(65+i)}))},
          {id:'weekly_player_kda',kind:'player',title:'¿Quién tendrá el mejor KDA de la semana?',description:'KDA individual acumulado de la semana: (asesinatos totales + asistencias totales) / máximo(muertes totales, 1).',placeholder:'Selecciona un integrante',icon:'📊',options:Array.from({length:18},(_,i)=>({id:'person'+i,label:'Persona '+i+' · Equipo '+Math.floor(i/2)}))},
          {id:'chicha_fogell_kills',kind:'duel',sharedWithTeam:true,teamAnswer:logged?(sharedKills||saved.chicha_fogell_kills||null):null,title:'¿Quién hará más kills esta semana: Chicha o Fogell?',description:'Kills individuales acumuladas esta semana. En empate, ambas respuestas valen.',placeholder:'Selecciona a Chicha o Fogell',icon:'⚔️',eventLabel:'DUELO SEMANAL',options:[{id:'chicha',label:'Chicha'},{id:'fogell',label:'Fogell'}]}
        ].map(c=>({...c,myAnswer:logged?saved[c.id]||null:null,
          result:closed?{status:'SETTLED',value:c.id==='unique_champions'?32:20,summary:c.id==='unique_champions'?'32 campeones distintos':c.id==='weekly_leader'?'Primer puesto · Gold IV · 50 LP':c.id==='first_week_last'?'Último puesto de la primera semana · Iron IV · 0 LP':c.id==='first_five_negative'?'0 dúos con winrate negativo en sus primeras 5 ranked':c.id==='first_individual_shell'?'Primer logro individual del torneo · 15/10 19:00':c.id==='joji_parradise_deaths'?'Joji: 12 muertes · Parradise: 8 muertes':'Mejor partida individual · 20.00 KDA',optionLabel:c.id==='unique_champions'?'30–39':['weekly_leader','first_week_last'].includes(c.id)?'Equipo B':c.id==='first_five_negative'?'0':c.id==='first_individual_shell'?'Persona 0 · Equipo 0':c.id==='joji_parradise_deaths'?'Joji':'A2 · Equipo A',optionIds:[c.id==='unique_champions'?'30-39':['weekly_leader','first_week_last'].includes(c.id)?'b':c.id==='first_five_negative'?'0':c.id==='first_individual_shell'?'person0':c.id==='joji_parradise_deaths'?'joji':'a2']}:null}));
        if(closed) categories.find(c=>c.id==='weekly_player_kda').result={status:'SETTLED',value:4.5,summary:'Mejor KDA acumulado semanal · 4.50 KDA',optionLabel:'Persona 0 · Equipo 0',optionIds:['person0']};
        if(closed) categories.find(c=>c.id==='chicha_fogell_kills').result={status:'SETTLED',summary:'Chicha: 13 kills · Fogell: 20 kills',optionLabel:'Fogell',optionIds:['fogell']};
        const hasBallot=Object.keys(saved).length>0;
        const state={rewardRule:{minCorrect:3,shells:1},week:url.searchParams.get('week')||'2026-10-12',weeks:['2026-10-19','2026-10-12'],startsAt:future-86400*4,endsAt:future+60,closesAt:closed?1:future,closed,categories,
          entries:hasBallot?1:0,myBallot:logged&&hasBallot?{author,answers:saved}:null,
          participation:{teamId:logged?'a':null,teamName:logged?'Equipo A':null,canAnswer:logged&&!closed,message:closed?'Las predicciones están cerradas.':logged?'Participando como Equipo A.':'Inicia sesión con tu equipo para rellenar la quiniela.'},
          predictions:closed?[{id:'mine',teamId:'a',teamName:'Equipo A',author:'<img src=x onerror="window.injected=true">',answers:saved,correct,pending,reward:awarded?{status:'AWARDED',shells:1}:pending?null:{status:'NO_REWARD',shells:0}}]:[]};
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
    assert.equal(await page.locator('[data-pickem-category]').count(),9,'all mocked categories including the weekly kills duel are active');
    assert.equal(await page.locator('.pickem-card').filter({has:page.locator('[data-pickem-category="joji_parradise_deaths"]')}).locator('.pickem-event').textContent(),'EVENTO · PRIMERA SEMANA');
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
    const duelCard = page.locator('[data-pickem-category="joji_parradise_deaths"]');
    await duelCard.click();
    assert.match(await page.locator('#pickem-dialog-description').textContent(), /Una elección por equipo/);
    await page.locator('#pickem-answer').selectOption('parradise');
    // A teammate submits while this modal still has the opposite unsent choice.
    sharedDuel = 'joji';
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>document.getElementById('pickem-submit').textContent==='Confirmar elección del equipo');
    assert.equal(await page.locator('#pickem-answer').inputValue(), 'joji');
    assert.equal(await page.locator('#pickem-answer').isDisabled(), true);
    assert.equal(await page.locator('#pickem-answer option[value=parradise]').isDisabled(), true);
    assert.equal(await page.locator('#pickem-submit').isEnabled(), true);
    assert.match(await page.locator('#pickem-dialog-description').textContent(), /Elección del equipo: Joji/);
    await page.evaluate(()=>{document.getElementById('pickem-answer').value='parradise';});
    await page.locator('#pickem-form').dispatchEvent('submit');
    assert.equal(calls.length,1,'forged opposite choice must not be sent');
    await page.keyboard.press('Escape');
    for(const [id,option,count,placeholder] of [['weekly_leader','b',3,'Selecciona un equipo'],['best_game_kda','a2',5,'Selecciona un jugador'],['first_five_negative','0',11,'Selecciona cuántos dúos'],['first_individual_shell','person0',19,'Selecciona un jugador'],['joji_parradise_deaths','joji',3,'Selecciona a Joji o Parradise'],['first_week_last','b',10,'Selecciona un equipo'],['weekly_player_kda','person0',19,'Selecciona un integrante']]) {
      await page.locator(`[data-pickem-category="${id}"]`).click();
      assert.equal(await page.locator('#pickem-answer option').count(),count);
      assert.equal(await page.locator('#pickem-answer option').first().textContent(),placeholder);
      assert.equal(await page.locator('#pickem-author').inputValue(),'Luis');
      assert.equal(await page.locator('#pickem-author').isDisabled(),true);
      if(id==='joji_parradise_deaths') {
        assert.equal(await page.locator('#pickem-answer').inputValue(),option);
        assert.equal(await page.locator('#pickem-answer').isDisabled(),true);
      } else await page.locator('#pickem-answer').selectOption(option);
      await page.locator('#pickem-submit').click();
      await page.waitForFunction(()=>!document.getElementById('pickem-dialog').open);
      assert.equal(await page.locator('#pickem-entries').textContent(),'1 quiniela enviada','categories share the same ballot');
    }
    assert.equal(calls.length,8);
    assert.equal(calls[3].optionId,'0','zero is a valid saved prediction');
    const killsCard=page.locator('[data-pickem-category="chicha_fogell_kills"]');
    await killsCard.click();
    assert.deepEqual(await page.locator('#pickem-answer option').allTextContents(),['Selecciona a Chicha o Fogell','Chicha','Fogell']);
    await page.locator('#pickem-answer').selectOption('chicha');
    sharedKills='fogell';
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>document.getElementById('pickem-answer').value==='fogell');
    assert.equal(await page.locator('#pickem-answer').isDisabled(),true);
    assert.match(await page.locator('#pickem-dialog-description').textContent(),/Elección del equipo: Fogell/);
    assert.equal(await page.locator('#pickem-submit').isEnabled(),true);
    await page.evaluate(()=>{document.getElementById('pickem-answer').value='chicha';});
    await page.locator('#pickem-form').dispatchEvent('submit');
    assert.equal(calls.length,8,'opposite choice is blocked in the new duel too');
    await page.keyboard.press('Escape');
    await killsCard.click();
    await page.locator('#pickem-submit').click();
    await page.waitForFunction(()=>!document.getElementById('pickem-dialog').open);
    assert.equal(calls.length,9);
    assert.equal(calls[8].optionId,'fogell');
    assert.equal(await page.locator('#pickem-entries').textContent(),'1 quiniela enviada');
    closed=true;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForSelector('.pickem-result-entry');
    assert.match(await page.locator('.pickem-card-result').nth(0).textContent(),/32 campeones distintos/);
    assert.match(await page.locator('.pickem-card-result').nth(1).textContent(),/Equipo B/);
    assert.match(await page.locator('.pickem-card-result').nth(2).textContent(),/20.00 KDA/);
    assert.match(await page.locator('.pickem-card-result').nth(3).textContent(),/0 dúos con winrate negativo/);
    assert.match(await page.locator('.pickem-card-result').nth(4).textContent(),/Primer logro individual del torneo/);
    assert.match(await page.locator('.pickem-card-result').nth(4).textContent(),/Persona 0/);
    assert.match(await page.locator('.pickem-card-result').nth(5).textContent(),/Joji: 12 muertes · Parradise: 8 muertes/);
    assert.match(await page.locator('.pickem-card-result').nth(6).textContent(),/Último puesto de la primera semana/);
    assert.match(await page.locator('.pickem-card-result').nth(6).textContent(),/Equipo B/);
    assert.match(await page.locator('.pickem-card-result').nth(7).textContent(),/Mejor KDA acumulado semanal · 4.50 KDA/);
    assert.match(await page.locator('.pickem-card-result').nth(7).textContent(),/Persona 0 · Equipo 0/);
    assert.match(await page.locator('.pickem-card-result').nth(8).textContent(),/Chicha: 13 kills · Fogell: 20 kills/);
    assert.equal(await page.locator('.pickem-result-entry').count(),9);
    assert.match(await page.locator('.pickem-result-entry').last().textContent(),/Fogell.*Acierto/);
    assert.match(await page.locator('.pickem-ballot-summary').textContent(),/9 aciertos/);
    assert.match(await page.locator('.pickem-ballot-summary').textContent(),/\+1 pepazo/);
    assert.equal(await page.locator('.pickem-result-entry').filter({hasText:'+1 pepazo'}).count(),0,'no individual category prizes');
    assert.match(await page.locator('.pickem-result-entry').first().textContent(),/Acierto/);
    assert.match(await page.locator('#pickem-reward-rule').textContent(),/al menos 3 aciertos/);
    assert.equal(await page.locator('.pickem-reward').filter({hasText:'por acierto'}).count(),0);
    correct=2; pending=1; awarded=false;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>document.querySelector('.pickem-ballot-summary').textContent.includes('2 aciertos'));
    assert.match(await page.locator('.pickem-ballot-summary').textContent(),/Pendiente de resultados/);
    pending=0;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>document.querySelector('.pickem-ballot-summary').textContent.includes('Sin premio'));
    correct=6; awarded=true;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>document.querySelector('.pickem-ballot-summary').textContent.includes('6 aciertos'));
    assert.match(await page.locator('.pickem-ballot-summary').textContent(),/\+1 pepazo/);
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
