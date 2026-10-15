// Corrected roles and stale-draft recovery, using the real backend catalog and mocked publication.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {items,tiers} = JSON.parse(execFileSync(process.env.PEPES_TEST_PYTHON || 'python', ['-B','-c',
  "import json, tierlists_service as t; print(json.dumps({'items':t.catalog('roles'),'tiers':t.ROLE_TIERS}))"], {cwd:__dirname,encoding:'utf8'}));

(async () => {
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1050}});
    const stale=Object.fromEntries(tiers.map(role=>[role,items.filter(item=>item.role===role).map(item=>item.id)]));
    stale.TOP[stale.TOP.indexOf('player-taberneta')]='player-ameteum';
    stale.MIDDLE[stale.MIDDLE.indexOf('player-ameteum')]='player-taberneta';
    await context.addInitScript(value=>{
      sessionStorage.setItem('pepes_player_token','test-session');
      localStorage.setItem('pepes_tierlist_roles_draft_v1',JSON.stringify({tiers:value,author:'Mi ranking'}));
    },stale);
    let posts=[];
    const errors=[];
    await context.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname==='/api/tierlists') {
        assert.equal(url.searchParams.get('kind'),'roles');
        if(request.method()==='POST') {
          const body=request.postDataJSON();
          assert.equal(body.kind,'roles');
          assert.ok(body.tiers.TOP.includes('player-taberneta'));
          assert.ok(body.tiers.MIDDLE.includes('player-ameteum'));
          assert.ok(!body.tiers.TOP.includes('player-ameteum'));
          assert.ok(!body.tiers.MIDDLE.includes('player-taberneta'));
          posts=[{id:'corrected-role-post',kind:'roles',teamId:'mine',teamName:'ATodoFlash',author:body.author,tiers:body.tiers,createdAt:1792100000}];
        }
        return route.fulfill({contentType:'application/json',body:JSON.stringify({kind:'roles',items,tiers,posts,total:posts.length,offset:0,limit:6,
          publishing:{teamId:'mine',teamName:'ATodoFlash',canPublish:!posts.length,reason:posts.length?'browser':'ready',message:posts.length?'Ya has publicado.':'Publicando como ATodoFlash.'}})});
      }
      if(url.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:'{}'});
      const file=url.pathname.slice(1);
      if(!['tierlist.html','tierlist.js','tierlist.css','styles.css','data.js','navigation.js','alerts.js'].includes(file)&&!items.some(item=>item.image===url.pathname))return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page=await context.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://pepes.test/tierlist.html?tipo=roles#crear');
    await page.waitForFunction(()=>document.querySelectorAll('#tierlist-pool [data-tierlist-item]').length===2);
    assert.match(await page.locator('#tierlist-remaining').textContent(),/2 integrantes pendientes/);
    assert.equal(await page.locator('#tierlist-author').inputValue(),'Mi ranking');
    const ameteum=page.locator('#tierlist-pool [data-tierlist-item="player-ameteum"]');
    const taberneta=page.locator('#tierlist-pool [data-tierlist-item="player-taberneta"]');
    assert.equal(await ameteum.locator('.pool-role-badge').textContent(),'MID');
    assert.equal(await taberneta.locator('.pool-role-badge').textContent(),'TOP');
    await ameteum.click();
    await page.locator('button.tier-label[data-place=TOP]').click();
    assert.match(await page.locator('#tierlist-form-error').textContent(),/MEDIO/);
    assert.equal(await page.locator('#tierlist-pool [data-tierlist-item]').count(),2);
    await page.locator('button.tier-label[data-place=MIDDLE]').click();
    await taberneta.click();
    await page.locator('button.tier-label[data-place=TOP]').click();
    assert.equal(await page.locator('#tierlist-pool [data-tierlist-item]').count(),0);
    assert.equal(await page.locator('#tierlist-board [data-place=TOP] [data-tierlist-item="player-taberneta"]').count(),1);
    assert.equal(await page.locator('#tierlist-board [data-place=MIDDLE] [data-tierlist-item="player-ameteum"]').count(),1);
    assert.equal(await page.locator('#tierlist-publish').isEnabled(),true);
    for(const width of [1440,768,390,320]) {
      await page.setViewportSize({width,height:1100});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`roles editor fits ${width}`);
    }
    await page.locator('#tierlist-publish').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-feedback').textContent.includes('ya está publicada'));
    assert.equal(posts.length,1);
    assert.equal(await page.locator('[data-tierlist-post] .tier-item').count(),18);
    assert.equal(await page.evaluate(()=>localStorage.getItem('pepes_tierlist_roles_draft_v1')),null);
    assert.deepEqual(errors,[]);
    console.log('Role tierlist verified: Ameteum MID, Taberneta TOP, stale draft recovery, wrong-row rejection, publication and mobile.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
