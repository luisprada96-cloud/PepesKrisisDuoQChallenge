// Clock-controlled browser checks. All API responses are isolated fixtures.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}, timezoneId:'America/Los_Angeles'});
    const first = Date.parse('2026-10-16T00:00:00+02:00')/1000;
    const close = Date.parse('2026-10-17T00:00:00+02:00')/1000;
    const end = Date.parse('2026-10-26T00:00:00+01:00')/1000;
    const ballots = [
      {id:'one',teamId:'a',teamName:'Equipo A',author:'=1+1',createdAt:first+3600,answers:{unique_champions:'0-19'},correct:0,pending:1},
      {id:'two',teamId:'a',teamName:'Equipo A',author:'<img src=x onerror="window.injected=true">',createdAt:first+7200,answers:{weekly_leader:'b'},correct:0,pending:1},
      {id:'other',teamId:'b',teamName:'Equipo B',author:'Autor privado rival',createdAt:first+3600,answers:{unique_champions:'20-29'},correct:0,pending:1}
    ];
    const categories = [
      {id:'unique_champions',title:'¿Cuántos campeones distintos se jugarán?',description:'Participantes del torneo.',options:[{id:'0-19',label:'Menos de 20'},{id:'20-29',label:'20–29'}]},
      {id:'weekly_leader',kind:'team',title:'¿Qué equipo terminará primero?',description:'ELO al cierre.',options:[{id:'a',label:'Equipo A'},{id:'b',label:'Equipo B'}]}
    ];
    const errors=[], posts=[];
    let deniedAdmin=false;
    context.on('page', page=>page.on('pageerror', error=>errors.push(error.message)));
    await context.route('**/*', async route=>{
      const req=route.request(), url=new URL(req.url());
      if(url.origin!=='http://pepes.test')return route.abort();
      const logged=req.headers().authorization==='Bearer team-session';
      const board={success:true,week:'2026-10-16',weeks:['2026-10-16'],startsAt:first,endsAt:end,closesAt:close,
        periods:{'2026-10-16':{startsAt:first,endsAt:end,closesAt:close}},closed:false,resultsVisible:false,
        entries:3,rewardRule:{minCorrect:3,shells:1},
        categories:categories.map(c=>({...c,myAnswer:logged?ballots[0].answers[c.id]||null:null,result:null})),
        myBallot:logged?{author:ballots[0].author,answers:ballots[0].answers}:null,
        teamBallots:logged?ballots.slice(0,2):[],predictions:[],
        participation:{teamId:logged?'a':null,canAnswer:logged,message:logged?'Participando como Equipo A.':'Inicia sesión con tu equipo.'}};
      if(url.pathname==='/api/pickem') {
        if(req.method()==='POST')posts.push(req.postDataJSON());
        return route.fulfill({contentType:'application/json',body:JSON.stringify(board)});
      }
      if(url.pathname==='/api/admin/pickem') {
        assert.equal(req.method(),'POST');
        assert.equal(req.postDataJSON().authPin,'9999');
        return route.fulfill({status:deniedAdmin?401:200,contentType:'application/json',body:JSON.stringify(deniedAdmin?{success:false,error:'PIN incorrecto'}:{...board,predictions:ballots})});
      }
      if(url.pathname==='/api/admin/login')return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,duos:[],penaltyCatalog:[],config:{startDate:'2026-10-15T18:00:00+02:00',endDate:'2026-11-15T23:59:00+01:00'}})});
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:JSON.stringify(url.pathname==='/api/duos'?[]:{})});
      const file=url.pathname.slice(1);
      if(!['pickem.html','pickem.js','pickem.css','data.js','styles.css','alerts.js','admin.html','admin.js','app.js','navigation.js','match-history.js'].includes(file))return route.fulfill({status:404,body:''});
      // Exercise the preserved feature while its public entry is temporarily paused.
      const body=fs.readFileSync(path.join(__dirname,file),'utf8').replace(' data-pickem-paused','');
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body});
    });
    const page=await context.newPage();
    await page.clock.install({time:new Date((close-2)*1000)});
    await page.clock.pauseAt(new Date((close-2)*1000));
    await page.addInitScript(()=>sessionStorage.setItem('pepes_player_token','team-session'));
    await page.goto('http://pepes.test/pickem.html');
    await page.locator('#pickem-team-picks .pickem-ballot').first().waitFor();
    assert.equal(await page.locator('#pickem-team-picks .pickem-ballot').count(),2);
    assert.doesNotMatch(await page.locator('main').textContent(),/Autor privado rival/);
    assert.equal(await page.locator('#pickem-results').isVisible(),false);
    assert.match(await page.locator('#pickem-week option').textContent(),/16 oct.*25 oct/);
    assert.match(await page.locator('#pickem-closing').textContent(),/16 oct.*23:59.*25 oct.*23:59/);
    const answered=page.locator('[data-pickem-category="unique_champions"]');
    const unanswered=page.locator('[data-pickem-category="weekly_leader"]');
    await unanswered.click();
    await page.locator('#pickem-answer').selectOption('a');
    assert.equal(await page.locator('#pickem-submit').isDisabled(),false);
    await page.clock.runFor(2100);
    assert.equal(await unanswered.isDisabled(),true);
    assert.equal(await unanswered.textContent(),'Plazo cerrado');
    assert.equal(await page.locator('#pickem-submit').isDisabled(),true);
    await page.locator('#pickem-form').dispatchEvent('submit');
    assert.deepEqual(posts,[]);
    await page.keyboard.press('Escape');
    assert.equal(await answered.isDisabled(),false);
    await answered.click();
    assert.equal(await page.locator('#pickem-answer').inputValue(),'0-19');
    assert.equal(await page.locator('#pickem-answer').isDisabled(),true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#pickem-results').isVisible(),false);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    await page.evaluate(()=>{sessionStorage.removeItem('pepes_player_token');document.dispatchEvent(new Event('player-session-ended'));});
    await page.waitForFunction(()=>document.getElementById('pickem-team-picks').hidden);
    assert.doesNotMatch(await page.locator('#pickem-team-pick-list').textContent(),/Equipo A|=1\+1/);

    const admin=await context.newPage();
    await admin.goto('http://pepes.test/admin.html');
    await admin.locator('#admin-pin-input').fill('9999');
    await admin.locator('#admin-pin-form button[type=submit]').click();
    await admin.locator('#admin-pickem-list details').first().waitFor();
    assert.equal(await admin.locator('#admin-pickem-list details').count(),3);
    await admin.locator('#admin-pickem-list summary').first().click();
    assert.match(await admin.locator('#admin-pickem-list').textContent(),/Menos de 20/);
    assert.equal(await admin.locator('#admin-pickem-list img').count(),0);
    assert.equal(await admin.evaluate(()=>window.injected),undefined);
    let csv=await admin.evaluate(()=>adminPickemCsv());
    assert(csv.startsWith('\ufeff'));
    assert.match(csv,/'=1\+1/);
    assert.match(csv,/Autor privado rival/);
    assert.match(csv,/16\/10\/2026.*01:00/);
    assert.doesNotMatch(csv,/visitor|authPin|puuid/);
    await admin.locator('#admin-pickem-team').selectOption('b');
    assert.equal(await admin.locator('#admin-pickem-list details').count(),1);
    csv=await admin.evaluate(()=>adminPickemCsv());
    assert.match(csv,/Equipo B/);
    assert.doesNotMatch(csv,/Equipo A/);
    const [download]=await Promise.all([admin.waitForEvent('download'),admin.locator('#admin-pickem-export').click()]);
    assert.equal(download.suggestedFilename(),'pickem-2026-10-16.csv');
    assert.equal(fs.readFileSync(await download.path(),'utf8'),csv);
    for(const width of [1440,390,320]) {
      await admin.setViewportSize({width,height:1000});
      const fits=await admin.locator('#admin-pickem').evaluate(section=>section.getBoundingClientRect().right<=innerWidth&&
        [...section.querySelectorAll('select,button,summary,.admin-penalties-table-wrap')].every(el=>el.getBoundingClientRect().right<=innerWidth));
      assert.equal(fits,true,`Pick’em admin controls and scrollable tables fit ${width}`);
    }
    deniedAdmin=true;
    await admin.locator('#admin-pickem-refresh').click();
    await admin.waitForFunction(()=>document.getElementById('admin-pickem-status').textContent==='PIN incorrecto');
    assert.equal(await admin.locator('#admin-pickem-export').isDisabled(),true);
    assert.equal(await admin.locator('#admin-pickem-list').textContent(),'');
    assert.deepEqual(errors,[]);
    console.log('Pick’em calendar browser checks passed: exact deadline, disabled cards, read-only own picks, both team ballots, privacy, admin filters and safe CSV export.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
