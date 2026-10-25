// Local browser checks for the weekly page; no real account or database changes.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
  try {
    const context=await browser.newContext();
    const errors=[];
    const weeks=['2026-10-05','2026-09-28'];
    const elo={start:{tier:'Emerald',division:'IV',lp:61,observedAt:1790546400},end:{tier:'Emerald',division:'III',lp:47,observedAt:1791150000},delta:86,partial:false};
    const totals={kills:145,deaths:121,assists:269};
    const players=[{key:'player1',name:'Ana',riotId:'Uno#EUW',games:28,totals,kda:3.42,mainRole:'TOP',favorite:{name:'MonkeyKing',games:10},elo,penaltiesCompleted:3},
      {key:'player2',name:'Luis',riotId:'Dos#EUW',games:25,totals,kda:3.42,mainRole:'UTILITY',favorite:null,elo:{start:null,end:null,delta:null,partial:true},penaltiesCompleted:0}];
    const team={id:'a',name:'krisis',games:28,wins:17,losses:11,winrate:61,bestStreak:5,totals,kda:3.42,detailGames:25,players,
      shells:{launched:3,received:4,returned:1,achievements:5,credited:2,blocked:1,creditUnknown:2,clipPrize:3},
      penalties:{received:4,completed:3,manual:1,pending:2},bestMatch:{champions:['MonkeyKing','Lulu'],totals:{kills:24,deaths:5,assists:31},kda:11,at:1791000000}};
    const archived={week:weeks[1],startsAt:1790546400,endsAt:1791151200,updatedAt:1791151202,status:'ARCHIVED',teams:[team],
      totals:{games:84,shellsLaunched:12,penaltiesCompleted:9,penaltiesManual:1},
      highlights:{rising:{...players[0],teamName:'krisis'},falling:null,attacker:team,completed:{...players[0],teamName:'krisis'}},
      clips:{available:true,posts:5,votes:35,winner:{status:'AWARDED',title:'Robo de Nashor',teamName:'krisis',teamId:'a',votes:24,shells:3,url:'https://clips.twitch.tv/Winner'}}};
    const current={...structuredClone(archived),week:weeks[0],status:'CURRENT',clips:{available:true,posts:0,votes:0,winner:null}};
    let fail=false, openingOnly=false;
    await context.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname==='/api/weekly-summary') {
        if(fail)return route.fulfill({status:503,contentType:'application/json',body:'{"error":"No disponible"}'});
        const week=url.searchParams.get('week');
        if(openingOnly && week && week!==weeks[0])return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'Resumen semanal no encontrado.'})});
        return route.fulfill({contentType:'application/json',body:JSON.stringify({weeks:openingOnly?[weeks[0]]:weeks,currentWeek:weeks[0],summary:!openingOnly&&week===weeks[1]?archived:current})});
      }
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:'{}'});
      const file=url.pathname.slice(1);
      if(!['resumen.html','resumen.js','resumen.css','data.js','alerts.js','styles.css'].includes(file))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://pepes.test/resumen.html');
    await page.locator('#weekly-report').waitFor({state:'visible'});
    assert.equal(await page.locator('#weekly-week').inputValue(),weeks[1],'latest archived week is default');
    assert.equal(await page.locator('#weekly-state').textContent(),'Semana cerrada');
    assert.match(await page.locator('#weekly-content').textContent(),/Robo de Nashor/);
    assert.match(await page.locator('#weekly-content').textContent(),/Premio: \+3 pepazos/);
    await page.locator('[data-weekly-clip]').click();
    const src=await page.locator('.weekly-embed').getAttribute('src');
    assert.match(src,/clip=Winner/);assert.match(src,/parent=pepes.test/);
    await page.locator('[data-weekly-view=team]').click();
    assert.match(await page.locator('#weekly-content').textContent(),/Sin datos suficientes/);
    assert.match(await page.locator('#weekly-content').textContent(),/Wukong \(10\)/);
    assert.match(await page.locator('#weekly-content').textContent(),/Wukong \+ Lulu/);
    assert.doesNotMatch(await page.locator('#weekly-content').textContent(),/MonkeyKing/);
    assert.match(await page.locator('#weekly-content').textContent(),/marcados por administración/);
    assert.doesNotMatch(await page.locator('#weekly-content').textContent(),/sin registro|sin sumar por el límite/);
    assert.equal(await page.locator('#connection-status').count(),0);
    archived.teams[0].shells.creditUnknown = 0;
    for(const width of [1280,390,320]){
      await page.setViewportSize({width,height:900});
      for(const view of ['team','general']){
        await page.locator('[data-weekly-view='+view+']').click();
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'width '+width+' '+view);
      }
    }
    await page.locator('#weekly-week').selectOption(weeks[0]);
    await page.waitForFunction(()=>document.getElementById('weekly-state').textContent==='Semana en curso');
    assert.match(await page.locator('#weekly-content').textContent(),/domingo a las 23:59/);
    assert.equal(await page.locator('[data-weekly-clip]').count(),0);
    await page.locator('[data-weekly-view=team]').click();
    fail=true;
    await page.locator('#weekly-week').selectOption(weeks[1]);
    await page.locator('#weekly-status.is-error').waitFor();
    assert.equal(await page.locator('#weekly-week').inputValue(),weeks[0]);
    assert.equal(await page.locator('[data-weekly-view=team]').getAttribute('aria-pressed'),'true');
    fail=false;
    archived.teams[0].name='<img src=x onerror="window.injected=true">';
    archived.highlights.rising.name=archived.teams[0].name;
    archived.clips.winner.title=archived.teams[0].name;
    archived.clips.winner.url='javascript:alert(1)';
    await page.locator('#weekly-week').selectOption(weeks[1]);
    await page.waitForFunction(()=>document.getElementById('weekly-state').textContent==='Semana cerrada');
    await page.locator('[data-weekly-view=general]').click();
    archived.clips.winner.shells=1;
    // Re-fetch to use the new fixture rather than the previous server snapshot.
    await page.reload();
    await page.locator('#weekly-report').waitFor({state:'visible'});
    assert.match(await page.locator('#weekly-content').textContent(),/Premio: \+1 pepazo\b/);
    assert.doesNotMatch(await page.locator('#weekly-content').textContent(),/Premio: \+1 pepazos/);
    assert.equal(await page.locator('#weekly-content img').count(),0);
    assert.equal(await page.locator('[data-weekly-clip]').count(),0);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    openingOnly=true;
    await page.goto('http://pepes.test/resumen.html?week='+weeks[1]);
    await page.locator('#weekly-report').waitFor({state:'visible'});
    assert.equal(await page.locator('#weekly-week option').count(),1,'preseason weeks absent from selector');
    assert.equal(await page.locator('#weekly-week').inputValue(),weeks[0]);
    assert.equal(await page.locator('#weekly-state').textContent(),'Semana en curso');
    assert.equal(new URL(page.url()).searchParams.get('week'),weeks[0],'old bookmark falls back to available tournament week');
    assert.equal(await page.locator('#weekly-status').textContent(),'');
    assert.deepEqual(errors,[]);
    if(process.env.WEEKLY_SCREENSHOT)await page.screenshot({path:process.env.WEEKLY_SCREENSHOT,fullPage:true});
    console.log('Weekly recap browser checks passed: archive/current/team views, clip embed, missing data, inventory cap, errors, escaping and mobile.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
