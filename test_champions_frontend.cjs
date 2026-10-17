const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'assets/pickem/champions.json'),'utf8'));
    let fail=false, picks={Ahri:4,Lux:2,MonkeyKing:1}, requests=[];
    const board=()=>{
      const champions=catalog.champions.map(row=>({id:row.id,name:row.label,games:picks[row.id]||0,played:!!picks[row.id]}));
      champions.sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name,'es'));
      return {champions,catalogVersion:catalog.version,totalChampions:champions.length,playedChampions:Object.keys(picks).length,totalPicks:Object.values(picks).reduce((a,b)=>a+b,0),totalMatches:4,pendingMatches:1};
    };
    await context.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.hostname==='ddragon.leagueoflegends.com') {
        if(process.env.CHAMPIONS_REAL_IMAGES)return route.continue();
        return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" fill="#3a92c9"/></svg>'});
      }
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname.startsWith('/api/')){
        requests.push({path:url.pathname,method:route.request().method()});
        if(url.pathname==='/api/sync/status')return route.fulfill({json:{riot:{},twitch:{}}});
        assert.equal(url.pathname,'/api/champions');
        return fail?route.fulfill({status:503,json:{error:'unavailable'}}):route.fulfill({json:board()});
      }
      const file=url.pathname.slice(1);
      if(!['campeones.html','campeones.js','campeones.css','navigation.js','styles.css','data.js','alerts.js'].includes(file))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://pepes.test/campeones.html',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(count=>document.querySelectorAll('.champion-tile').length===count,catalog.champions.length);
    assert.equal(await page.locator('[aria-current=page]').getAttribute('href'),'campeones.html');
    assert.equal(await page.locator('.champion-tile').first().getAttribute('data-champion-id'),'Ahri');
    assert.equal(await page.locator('.champion-tile.is-played').count(),3);
    assert.equal(await page.locator('#champions-progress').textContent(),`3 / ${catalog.champions.length}`);
    assert.equal(await page.locator('#champions-picks').textContent(),'7');
    assert.equal(await page.locator('#champions-warning').isVisible(),true);
    const ahri=page.locator('[data-champion-id=Ahri]');
    assert.equal(await ahri.locator('.champion-placeholder').isVisible(),false);
    assert.match(await ahri.locator('img').evaluate(img=>getComputedStyle(img).filter),/grayscale\(1\)/);
    assert.equal(await page.locator('[data-champion-id=Aatrox] img').evaluate(img=>getComputedStyle(img).filter),'none');
    await ahri.hover();
    await page.waitForFunction(()=>getComputedStyle(document.getElementById('champion-tooltip-Ahri')).opacity==='1');
    assert.match(await ahri.getByRole('tooltip').textContent(),/4 apariciones/);
    await page.mouse.move(1,1);await ahri.focus();
    await page.keyboard.press('Enter');
    assert.match(await page.locator('#champions-detail').textContent(),/Ahri.*4 apariciones/);
    await page.locator('#champions-search').fill('wukong');
    assert.equal(await page.locator('.champion-tile').count(),1);
    await page.locator('.champion-tile').click();
    assert.match(await page.locator('#champions-detail').textContent(),/Wukong.*1 aparición/);
    await page.locator('#champions-search').fill('no existe');
    assert.equal(await page.locator('#champions-empty').isVisible(),true);
    await page.locator('#champions-search').fill('');
    fail=true;await page.locator('#champions-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#champions-status').textContent.includes('Conexión interrumpida'));
    assert.equal(await page.locator('.champion-tile').count(),catalog.champions.length);
    await page.locator('#champions-search').fill('Ahri');
    assert.match(await page.locator('#champions-status').textContent(),/Conexión interrumpida/);
    await page.locator('#champions-search').fill('');
    fail=false;picks={Ahri:5,Lux:2,MonkeyKing:1,Zed:1};
    await page.locator('#champions-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#champions-picks').textContent==='9');
    assert.equal(await page.locator('.champion-tile.is-played').count(),4);
    for(const width of [1440,768,390,320]){
      await page.setViewportSize({width,height:950});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`album fits ${width}px`);
      await page.locator('[data-champion-id=Ahri]').click();
      assert.match(await page.locator('#champions-detail').textContent(),/5 apariciones/);
    }
    await page.setViewportSize({width:1440,height:1000});
    if(process.env.CHAMPIONS_SCREENSHOT){
      await page.evaluate(()=>scrollTo(0,0));
      await page.waitForTimeout(process.env.CHAMPIONS_REAL_IMAGES?2000:100);
      await page.screenshot({path:process.env.CHAMPIONS_SCREENSHOT});
    }
    assert.ok(requests.every(request=>request.method==='GET'));
    assert.deepEqual(errors,[]);
    console.log('PASS: full catalog, sorted picks, grayscale only played champions, hover/focus/touch, search, offline preservation, refresh and 4 screen sizes.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
