// Searchable champion predictions against a mocked API; no real accounts or votes.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {champions} = require('./assets/pickem/champions.json');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1050}});
    let saved='', closed=false, fail=false;
    const calls=[], errors=[], closesAt=Date.now()/1000+86400;
    await context.route('**/*', route => {
      const request=route.request(), url=new URL(request.url());
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname==='/api/pickem') {
        const logged=request.headers().authorization==='Bearer champion-session';
        if(request.method()==='POST') {
          if(fail)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudo guardar.'})});
          const body=request.postDataJSON();
          assert.ok(logged);
          assert.equal(body.categoryId,'best_champion_winrate');
          assert.ok(champions.some(c=>c.id===body.optionId));
          assert.equal(saved,'');
          calls.push(body);saved=body.optionId;
        }
        const result=closed?{status:'SETTLED',optionIds:['MonkeyKing'],optionLabel:'Wukong',summary:'Mejor winrate semanal · 100.00 % · mínimo 3 partidas'}:null;
        const categories=[
          {id:'unique_champions',kind:'range',title:'Campeones distintos',description:'Rango de campeones',placeholder:'Selecciona un rango',options:[{id:'0-19',label:'Menos de 20'}],myAnswer:null,result:null},
          {id:'best_champion_winrate',kind:'champion',title:'¿Qué campeón tendrá mejor winrate?',description:'Mínimo 3 partidas individuales esta semana. En empate, valen todos.',placeholder:'Busca y selecciona un campeón',options:champions,myAnswer:logged?saved||null:null,result}
        ];
        return route.fulfill({contentType:'application/json',body:JSON.stringify({
          week:'2026-10-12',weeks:['2026-10-12'],closesAt:closed?1:closesAt,closed,categories,entries:saved?1:0,
          rewardRule:{minCorrect:3,shells:1},myBallot:logged&&saved?{author:'',answers:{best_champion_winrate:saved}}:null,
          participation:{teamId:logged?'a':null,teamName:logged?'Equipo A':null,canAnswer:logged&&!closed,message:logged?'Participando como Equipo A.':'Inicia sesión con tu equipo.'},
          predictions:closed?[{id:'one',teamName:'Equipo A',answers:{best_champion_winrate:saved},correct:1,pending:0,reward:{status:'NO_REWARD',shells:0}}]:[]
        })});
      }
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:'{}'});
      const file=url.pathname.slice(1);
      if(!['pickem.html','pickem.js','pickem.css','styles.css','data.js','alerts.js','navigation.js'].includes(file))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page=await context.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://pepes.test/pickem.html');
    const card=page.locator('[data-pickem-category="best_champion_winrate"]');
    await card.click();
    const search=page.getByRole('combobox',{name:'Tu pronóstico'});
    assert.equal(await search.getAttribute('id'),'pickem-champion-search');
    assert.equal(await page.locator('#pickem-answer').isVisible(),false);
    await search.fill('ahri');
    await page.getByRole('option',{name:'Ahri',exact:true}).click();
    assert.equal(await page.locator('#pickem-answer').inputValue(),'Ahri');
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true,'guests can preview champions');
    await page.keyboard.press('Escape');
    await page.evaluate(()=>{sessionStorage.setItem('pepes_player_token','champion-session');window.dispatchEvent(new Event('focus'));});
    await page.waitForFunction(()=>document.getElementById('pickem-participation').textContent.includes('Equipo A'));
    await card.click();
    await search.click();
    assert.equal(await page.locator('#pickem-champion-options').getByRole('option').count(),champions.length,'all champions available before filtering');
    await search.fill('not-a-real-champion');
    assert.match(await page.locator('#pickem-champion-options').textContent(),/No se encontró/);
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true);
    for(const [query,label] of [['kaisa',"Kai'Sa"],['cho gath',"Cho'Gath"],['maestro yi','Maestro Yi'],['bárdo','Bardo']]) {
      await search.fill(query);
      assert.equal(await page.getByRole('option',{name:label,exact:true}).count(),1);
    }
    await search.fill('kaisa');
    await search.press('ArrowDown');
    assert.ok(await search.getAttribute('aria-activedescendant'));
    await search.press('Enter');
    assert.equal(await search.inputValue(),"Kai'Sa");
    assert.equal(await page.locator('#pickem-answer').inputValue(),'Kaisa');
    assert.equal(calls.length,0,'Enter chooses a champion without submitting');
    await search.fill('ah');
    await Promise.all([page.waitForResponse(r=>r.url().includes('/api/pickem')),page.evaluate(()=>window.dispatchEvent(new Event('focus')))]);
    assert.equal(await search.inputValue(),'ah','background refresh preserves the search');
    assert.equal(await page.locator('#pickem-answer').inputValue(),'');
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true,'editing clears the previously selected champion');
    await search.press('Escape');
    assert.equal(await page.locator('#pickem-dialog').isVisible(),true,'Escape first closes suggestions');
    assert.equal(await search.getAttribute('aria-expanded'),'false');
    await search.press('Escape');
    assert.equal(await page.locator('#pickem-dialog').isVisible(),false);
    for(const width of [1440,768,390,320]) {
      await page.setViewportSize({width,height:1000});
      await card.click();
      await search.fill('lee');
      assert.equal(await page.getByRole('option',{name:'Lee Sin',exact:true}).isVisible(),true);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`page fits ${width}`);
      const box=await page.locator('#pickem-champion-options').boundingBox();
      assert.ok(box.x>=0&&box.x+box.width<=width,`champion dropdown fits ${width}`);
      if(width===390&&process.env.PICKEM_CHAMPION_SCREENSHOT)await page.screenshot({path:process.env.PICKEM_CHAMPION_SCREENSHOT});
      await page.getByRole('option',{name:'Lee Sin',exact:true}).click();
      await page.keyboard.press('Escape');
    }
    await card.click();
    await search.fill('monkey');
    await search.press('ArrowDown');
    await search.press('Enter');
    assert.equal(await search.inputValue(),'Wukong');
    assert.equal(await page.locator('#pickem-answer').inputValue(),'MonkeyKing');
    fail=true;
    await page.locator('#pickem-submit').click();
    await page.locator('#pickem-form-error').waitFor();
    await page.waitForFunction(()=>!document.getElementById('pickem-submit').disabled);
    assert.equal(await search.inputValue(),'Wukong','failed submission preserves selected champion');
    fail=false;
    await page.locator('#pickem-submit').click();
    await page.waitForFunction(()=>!document.getElementById('pickem-dialog').open);
    assert.equal(calls.length,1);
    assert.equal(calls[0].optionId,'MonkeyKing');
    await card.click();
    assert.equal(await search.inputValue(),'Wukong');
    assert.equal(await search.isDisabled(),true);
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true);
    await page.keyboard.press('Escape');
    await page.locator('[data-pickem-category="unique_champions"]').click();
    assert.equal(await page.locator('#pickem-champion-picker').isVisible(),false);
    assert.equal(await page.locator('#pickem-answer').isVisible(),true,'other categories retain their normal select');
    await page.keyboard.press('Escape');
    closed=true;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForSelector('.pickem-result-entry');
    assert.match(await page.locator('.pickem-card-result').last().textContent(),/100.00 %.*mínimo 3 partidas.*Wukong/s);
    assert.match(await page.locator('.pickem-result-entry').filter({hasText:'¿Qué campeón tendrá mejor winrate?'}).textContent(),/Wukong.*Acierto/s);
    assert.deepEqual(errors,[]);
    console.log('Champion picker passed: full catalog, search, aliases, keyboard, guest preview, refresh, failed save, immutable answer, result and mobile layouts.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
