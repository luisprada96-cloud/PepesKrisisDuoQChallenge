// Browser + real HTTP/SSE + disposable data. The sample WebM is synthetic and transparent.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {existsSync,mkdirSync} = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const venv = path.join(__dirname,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python = process.env.PEPES_TEST_PYTHON || (existsSync(venv)?venv:'python');
const env = {...process.env,PEPES_STORAGE:'local'};
for(const name of ['DATABASE_URL','RIOT_API_KEY','TWITCH_CLIENT_ID','TWITCH_CLIENT_SECRET','DISCORD_LIVE_WEBHOOK_URL'])delete env[name];
const fixture=spawn(python,['-u','-B','-c',`
import server
import test_shell_penalties as fixtures
server.remote_backend = None
case = fixtures.ShellEndpointTests()
case.setUp()
try:
    print('READY=' + case.base, flush=True)
    input()
finally:
    server.player_sessions.clear()
    server.notify_shell_receivers()
    case.tearDown()
`],{cwd:__dirname,env,stdio:['pipe','pipe','pipe']});
fixture.stderr.pipe(process.stderr);
const ready=new Promise((resolve,reject)=>{
  let output='';const timer=setTimeout(()=>reject(new Error('Fixture timeout')),20000);
  fixture.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/READY=(http:\/\/127\.0\.0\.1:\d+)/);if(match){clearTimeout(timer);resolve(match[1]);}});
  fixture.on('error',error=>{clearTimeout(timer);reject(error);});
  fixture.on('exit',code=>{clearTimeout(timer);reject(new Error('Fixture exited '+code));});
});
(async()=>{
  let browser;
  try{
    const base=await ready;
    browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
    const errors=[];
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    context.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
    // Connect both OBS clients BEFORE adding a new effect.
    const clients=[];
    for(let i=0;i<2;i++){
      const page=await context.newPage();
      await page.goto(base+`/overlay.html?team=b&instance=client-${i}`);
      await page.locator('#password').fill('b-pass');await page.locator('#submit').click();
      await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Conectado'));
      await page.locator('#hide').click();clients.push(page);
    }
    const admin=await context.newPage();await admin.goto(base+'/admin.html');
    await admin.locator('#admin-pin-input').fill('9999');await admin.locator('#admin-pin-form button[type=submit]').click();
    await admin.locator('#admin-overlay-effects').waitFor({state:'visible'});
    await admin.waitForFunction(()=>document.querySelectorAll('.overlay-library-card').length===1);
    assert.equal(await admin.locator('.overlay-library-card button').isDisabled(),true,'Cannot disable the last active effect.');
    await admin.locator('#overlay-upload-file').setInputFiles(path.join(__dirname,'test_fixtures','overlay-sample.webm'));
    await admin.waitForFunction(()=>!document.querySelector('#overlay-upload-submit').disabled);
    await admin.locator('#overlay-upload-name').fill('<img src=x onerror=alert(1)> Efecto nuevo');
    await admin.locator('#overlay-upload-submit').click();
    await admin.waitForFunction(()=>document.querySelectorAll('.overlay-library-card').length===2);
    assert.equal(await admin.locator('.overlay-library-card img').count(),0);
    assert.match(await admin.locator('#overlay-library-status').textContent(),/50/);
    await admin.locator('.overlay-library-card').first().getByRole('button',{name:'Desactivar',exact:true}).click();
    await admin.waitForFunction(()=>document.querySelector('#overlay-library-status').textContent.includes('100'));
    const logged=await (await admin.request.post(base+'/api/player/login',{data:{teamId:'a',password:'a-pass'}})).json();
    const launch=await (await admin.request.post(base+'/api/player/launch-shell',{data:{sessionToken:logged.sessionToken,targetId:'b'}})).json();
    assert.equal(launch.success,true);assert.equal(launch.attack.overlayEffect.kind,'video');
    const source=launch.attack.overlayEffect.url;
    await Promise.all(clients.map(async page=>{
      await page.waitForFunction(()=>document.querySelector('#alert').classList.contains('video-effect'));
      assert.equal(await page.locator('#effect-video').getAttribute('src'),source);
      await page.waitForFunction(()=>document.querySelector('#effect-video').readyState>=2);
      // The transparent fixture must actually decode with an alpha background.
      const alpha=await page.locator('#effect-video').evaluate(video=>{
        const c=document.createElement('canvas');c.width=320;c.height=180;const ctx=c.getContext('2d');
        ctx.drawImage(video,0,0,320,180);return ctx.getImageData(5,5,1,1).data[3];
      });
      assert.equal(alpha,0);
      await page.waitForFunction(()=>document.querySelector('#alert').classList.contains('video-hold'));
      assert.equal(await page.locator('.message').evaluate(el=>getComputedStyle(el).opacity),'1');
      assert.equal(await page.locator('#attacker').textContent(),'Atacante');
    }));
    mkdirSync(path.join(__dirname,'preview'),{recursive:true});
    await admin.locator('#admin-overlay-effects').screenshot({path:path.join(__dirname,'preview','overlay-library-admin.png')});
    await Promise.all(clients.map(page=>page.waitForFunction(()=>document.querySelector('#alert').hidden,{},{timeout:6500})));
    await clients[0].reload();
    await clients[0].waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Conectado'));
    assert.equal(await clients[0].locator('#alert').isVisible(),false);
    await admin.setViewportSize({width:390,height:844});
    assert.equal(await admin.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: admin upload, equal probabilities, last-active guard, safe names, new effect on two connected clients without reload, WebM alpha, sender hold, deduplication and mobile.');
  }finally{
    if(browser)await browser.close();
    if(fixture.exitCode===null)fixture.stdin.end('\n');
    const timer=setTimeout(()=>fixture.kill(),5000);timer.unref();fixture.once('exit',()=>clearTimeout(timer));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
