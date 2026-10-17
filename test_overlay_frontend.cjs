const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1920,height:1080}});
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    let chosen = 'a', requests = [];
    const teams = [{id:'a',teamName:'LosELOgidos'}, {id:'b',teamName:'Otro dúo'}];
    await context.addInitScript(() => {
      window.overlaySounds = 0;
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function(...args) { window.overlaySounds++; window.overlayAudioDuration = this.buffer?.duration; return start.apply(this, args); };
      const original = window.fetch;
      window.fetch = (url, options) => {
        if (url !== '/api/player/events') return original(url, options);
        window.streamAuth = options.headers.Authorization;
        return Promise.resolve(new Response(new ReadableStream({start(controller) {
          window.emitFrame = value => controller.enqueue(new TextEncoder().encode(value));
          window.closeStream = () => controller.close();
          options.signal.addEventListener('abort', () => {try {controller.close();} catch (_) {}});
        }}), {headers:{'Content-Type':'text/event-stream'}}));
      };
    });
    await context.route('**/*', route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== 'http://overlay.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        requests.push(url.pathname);
        if (url.pathname === '/api/duos') return route.fulfill({json:teams});
        const body = req.postDataJSON();
        if (url.pathname === '/api/player/login') {
          assert.equal(body.password,'test-password'); chosen = body.teamId;
          return route.fulfill({json:{success:true,sessionToken:'private-'+chosen}});
        }
        if (url.pathname === '/api/player/state') {
          assert.equal(body.sessionToken, 'private-'+chosen);
          return route.fulfill({json:{success:true,duo:{...teams.find(t=>t.id===chosen),pendingShellAttacks:[{id:'old'}]}}});
        }
        if (url.pathname === '/api/player/logout') return route.fulfill({json:{success:true}});
        throw new Error('Unexpected mutation: '+url.pathname);
      }
      const file = path.join(__dirname,url.pathname.slice(1));
      return route.fulfill({body:fs.readFileSync(file),contentType:url.pathname.endsWith('.mp3')?'audio/mpeg':url.pathname.endsWith('.css')?'text/css':url.pathname.endsWith('.js')?'text/javascript':'text/html'});
    });
    await page.goto('http://overlay.test/overlay.html?team=b');
    await page.waitForFunction(() => document.querySelector('#team').options.length===3);
    assert.equal(await page.locator('#team').inputValue(),'b');
    assert.equal(requests.includes('/api/player/login'),false,'A suggested team must not authenticate the overlay.');
    assert.equal(await page.locator('#settings').isVisible(),true);
    // The local preview works before login and cannot spend or open a pepazo.
    await page.locator('#preview').click();
    await page.waitForFunction(() => !document.querySelector('#alert').hidden && window.overlaySounds > 0);
    assert.equal(await page.locator('#settings').isVisible(), false);
    assert.match(await page.locator('#attacker').textContent(), /Dúo de prueba/);
    assert.equal(await page.locator('#alert').innerText().then(text => /caparaz/i.test(text)), false);
    assert.deepEqual(requests, ['/api/duos']);
    assert.ok(Math.abs(await page.evaluate(() => window.overlayAudioDuration) - 10) < .03,
      'The decoded soundtrack must last ten seconds.');
    await page.waitForTimeout(6800);
    assert.equal(await page.locator('.message').evaluate(el => getComputedStyle(el).opacity), '1',
      'The sender must remain readable after the impact.');
    assert.equal(await page.locator('#alert').isVisible(), true);
    await page.waitForFunction(() => document.querySelector('#alert').hidden, {}, {timeout:12000});
    await page.mouse.dblclick(1800,900);
    await page.locator('#team').selectOption('a');
    await page.locator('#password').fill('test-password');
    await page.locator('#submit').click();
    await page.waitForFunction(() => !!window.emitFrame);
    assert.equal(await page.evaluate(()=>window.streamAuth),'Bearer private-a');
    assert.equal(await page.locator('#password').inputValue(), '');
    assert.equal(await page.evaluate(() => localStorage.getItem('pepes_obs_session_v1_default').includes('test-password')), false);
    const send = (team, attacks) => page.evaluate(({team,attacks})=>window.emitFrame('data: '+JSON.stringify({team:{id:team,name:team==='a'?'LosELOgidos':'Otro dúo'},attacks})+'\n\n'),{team,attacks});
    await send('a',[{id:'old'}]);
    await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Conectado'));
    assert.equal(await page.locator('#alert').isVisible(),false);
    await page.locator('#hide').click();
    await send('b',[{id:'foreign',attackerName:'Wrong team'}]);
    assert.equal(await page.locator('#alert').isVisible(),false);
    // Split JSON/frame delimiters across stream chunks; text must not become HTML.
    const attacker = '<img src=x onerror=alert(1)>';
    await page.evaluate(attacker => {
      const frame='data: '+JSON.stringify({team:{id:'a',name:'LosELOgidos'},attacks:[{id:'one',attackerName:attacker},{id:'two',attackerName:'Segundo'}]})+'\n\n';
      window.emitFrame(frame.slice(0,37)); window.emitFrame(frame.slice(37,-1));window.emitFrame(frame.slice(-1));
    },attacker);
    await page.waitForFunction(()=>!document.querySelector('#alert').hidden);
    assert.match(await page.locator('#attacker').innerText(),/<img/);
    assert.equal(await page.locator('#attacker img').count(),0);
    fs.mkdirSync(path.join(__dirname,'preview'),{recursive:true});
    await page.waitForFunction(()=>document.querySelector('#attacker').textContent.startsWith('Segundo'),{},{timeout:15000});
    await send('a',[{id:'one'},{id:'two'}]);
    await page.waitForFunction(()=>document.querySelector('#alert').hidden,{},{timeout:15000});
    await page.waitForTimeout(400);
    assert.equal(await page.locator('#alert').isVisible(),false);
    // Reconnect with a new event; preserve deduplication.
    await page.evaluate(()=>{window.emitFrame=null;window.closeStream();});
    await page.waitForFunction(()=>!!window.emitFrame,{},{timeout:6000});
    await send('a',[{id:'two'},{id:'three',attackerName:'Reconectado'}]);
    await page.waitForFunction(()=>document.querySelector('#attacker').textContent.startsWith('Reconectado'));
    await page.reload();
    await page.waitForFunction(()=>!!window.emitFrame);
    assert.equal(await page.locator('#settings').isVisible(),false);
    await send('a',[{id:'three'}]);
    await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Conectado'));
    assert.equal(await page.locator('#alert').isVisible(),false);
    await page.evaluate(()=>window.emitFrame('event: expired\ndata: {}\n\n'));
    await page.waitForFunction(()=>!document.querySelector('#warning').hidden);
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('pepes_obs_session_v1_default')||'null')),null);
    await page.mouse.dblclick(1800,900);
    await page.locator('#team').selectOption('b');
    await page.locator('#password').fill('test-password'); await page.locator('#submit').click();
    await page.waitForFunction(()=>window.streamAuth==='Bearer private-b');
    await send('b',[{id:'b-one',attackerName:'Rival B'}]);
    await page.waitForFunction(()=>document.querySelector('#target').textContent==='Otro dúo');
    await page.locator('#hide').click();
    await page.waitForTimeout(3000);
    await page.screenshot({path:path.join(__dirname,'preview','overlay-pepazo.png'),omitBackground:true});
    assert.ok(requests.every(p=>['/api/duos','/api/player/login','/api/player/state','/api/player/logout'].includes(p)));
    assert.deepEqual(errors,[]);
    console.log('PASS: teams, private session, baseline, isolation, fragmented SSE, safe text, queue, duplicates, reconnect, reload and expiry.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
