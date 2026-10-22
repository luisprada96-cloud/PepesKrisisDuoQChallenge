const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const week = '2026-10-15', errors = [], deletions = [];
    let failDelete = false;
    let posts = [
      {id:'own', title:'Mi clip <b>sin HTML</b>', canDelete:true},
      {id:'foreign', title:'Clip de otro', canDelete:false},
      {id:'legacy', title:'Clip antiguo', canDelete:false}
    ].map((post, i) => ({...post, slug:'ExampleClip'+i,url:'https://clips.twitch.tv/ExampleClip'+i,
      team:'Equipo A',initials:'EA',scene:1,createdAt:Date.now()/1000-i,votes:0,commentCount:0}));
    const payload = admin => ({week,clips:posts.map(p=>({...p,canDelete:admin || p.canDelete})),teams:[{id:'a',name:'Equipo A'}],voting:null,weeklyReward:{closed:false}});
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if(url.origin !== 'http://clip-delete.test') return route.abort();
      if(url.pathname === '/api/clips/moderate') {
        if(req.postDataJSON().authPin !== '9999') return route.fulfill({status:401,json:{error:'PIN de administrador incorrecto.'}});
        return route.fulfill({json:payload(true)});
      }
      if(url.pathname === '/api/clips/delete') {
        const data = req.postDataJSON(); deletions.push(data);
        if(failDelete) {failDelete=false;return route.fulfill({status:503,json:{error:'Fallo temporal'}});}
        posts = posts.filter(p=>p.id !== data.clipId);
        return route.fulfill({json:payload(data.authPin==='9999')});
      }
      if(url.pathname === '/api/clips') return route.fulfill({json:payload(false)});
      if(url.pathname.startsWith('/api/')) return route.fulfill({json:{}});
      const file = path.join(__dirname,url.pathname.slice(1));
      if(!fs.existsSync(file)) return route.fulfill({status:404,body:''});
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
    });
    const page = await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://clip-delete.test/clips.html');
    await page.locator('[data-delete-clip="own"]').waitFor();
    assert.equal(await page.locator('[data-delete-clip]').count(),1);
    assert.equal(await page.locator('#clips-moderation').isVisible(),false);
    await page.locator('[data-play="foreign"]').click();
    assert.equal(await page.locator('iframe').count(),1);
    page.once('dialog',d=>d.dismiss());
    await page.locator('[data-delete-clip="own"]').click();
    assert.equal(deletions.length,0,'Cancel must not send any deletion.');
    failDelete = true;
    page.once('dialog',d=>d.accept());
    await page.locator('[data-delete-clip="own"]').click();
    await page.waitForFunction(()=>document.querySelector('#clips-feedback').textContent==='Fallo temporal');
    assert.equal(await page.locator('[data-clip-id="own"]').count(),1);
    assert.equal(await page.locator('iframe').count(),1,'Failed deletion must preserve playback.');
    page.once('dialog',d=>d.accept());
    await page.locator('[data-delete-clip="own"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('.clip-post').length===2);
    assert.deepEqual(deletions.at(-1),{clipId:'own',week});
    assert.equal(await page.locator('iframe').count(),1);
    await page.goto('http://clip-delete.test/clips.html?moderate=1');
    await page.locator('#clips-moderation').waitFor({state:'visible'});
    await page.locator('#clips-admin-pin').fill('wrong');
    await page.locator('#clips-moderation [type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('#clips-moderation-status').textContent.includes('incorrecto'));
    assert.equal(await page.locator('[data-delete-clip]:visible').count(),0);
    await page.locator('#clips-admin-pin').fill('9999');
    await page.locator('#clips-moderation [type="submit"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-delete-clip]').length===2);
    assert.equal(await page.locator('#clips-admin-pin').inputValue(),'');
    assert.equal(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}).includes('9999')),false);
    for(const width of [360,780,1440]) {
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true);
    }
    page.once('dialog',d=>d.accept());
    await page.locator('[data-delete-clip="legacy"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('.clip-post').length===1);
    assert.equal(deletions.at(-1).authPin,'9999');
    await page.locator('#clips-moderation-end').click();
    await page.waitForFunction(()=>!document.querySelector('[data-delete-clip="foreign"]') || document.querySelector('[data-delete-clip="foreign"]').hidden);
    assert.deepEqual(errors,[]);
    console.log('CLIP_DELETE_UI_OK: owner-only controls, confirm/cancel, failed writes, video preservation, admin/legacy deletion, PIN privacy and responsive layout.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
