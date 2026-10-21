// Real Chrome + isolated HTTP server/database; no production credentials/data.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const script = `
import os, sys, threading
import server
server.remote_backend = None
server.DB_FILE = os.path.join(sys.argv[1], 'db.json')
server.SECRETS_FILE = os.path.join(sys.argv[1], 'secrets.json')
if not os.path.exists(server.DB_FILE):
    duos = [{'id': key, 'teamName': name, 'passwordHash':server.hash_secret(key+'-pass'),
             'tier':'Gold', 'division':'IV', 'lp':20, 'blueShells':1, 'history':[],
             'player1':{'name':key+'1','tag':'EUW'}, 'player2':{'name':key+'2','tag':'EUW'}}
            for key, name in [('a','Equipo A'),('b','Equipo B')]]
    server.write_json(server.DB_FILE, {'config':{},'duos':duos,'events':[],'shellAttacks':[]})
httpd = server.ReusableServer(('127.0.0.1', int(sys.argv[2])), server.CustomHandler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print('READY http://127.0.0.1:'+str(httpd.server_port), flush=True)
sys.stdin.readline()
httpd.shutdown(); httpd.server_close()
`;

(async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pepes-auth-ui-'));
  let processServer, context, base;
  const errors = [];
  async function start(port = 0) {
    processServer = spawn(process.env.PYTHON || path.join(__dirname,'.venv','Scripts','python.exe'),
      ['-u', '-c', script, temp, String(port)], {cwd:__dirname, env:{...process.env,PEPES_STORAGE:'local',DATABASE_URL:''}, windowsHide:true});
    base = await new Promise((resolve,reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Test server did not start: '+output)),15000);
      processServer.stdout.on('data', chunk => {output += chunk; const match = /READY (http:\/\/127\.0\.0\.1:\d+)/.exec(output); if(match){clearTimeout(timer);resolve(match[1]);}});
      processServer.stderr.on('data', chunk => {output += chunk;});
      processServer.on('exit', code => {clearTimeout(timer);reject(new Error('Test server stopped: '+code+' '+output));});
    });
  }
  async function stop() {
    if (!processServer || processServer.exitCode !== null) return;
    const child = processServer;
    await new Promise(resolve => {child.once('exit',resolve);child.stdin.end('\n');});
  }
  async function openBrowser() {
    context = await chromium.launchPersistentContext(path.join(temp,'chrome'), {
      headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome', viewport:{width:1440,height:1000}});
    await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    return context.newPage();
  }
  async function dashboard(page, name='Equipo A') {
    await page.locator('#player-dashboard-section').waitFor({state:'visible'});
    await page.waitForFunction(name => document.querySelector('#dash-team-name')?.textContent === name, name);
  }
  async function login(page, key='a') {
    await page.locator('#login-team-select').selectOption(key);
    await page.locator('#login-password-input').fill(key+'-pass');
    await page.locator('#player-login-form button[type=submit]').click();
    await dashboard(page,key==='a'?'Equipo A':'Equipo B');
  }
  try {
    await start();
    let page = await openBrowser();
    await page.goto(base+'/player.html');
    await login(page);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('pepes_player_token')),null);
    assert.equal(await page.evaluate(() => document.cookie.includes('pepes_team_session')),false,'Session cookie must be HttpOnly.');
    const cookie = (await context.cookies()).find(c => c.name==='pepes_team_session');
    assert.ok(cookie.httpOnly && cookie.sameSite==='Lax' && cookie.expires > Date.now()/1000 + 29*86400);
    const tab = await context.newPage();
    await tab.goto(base+'/player.html');
    await dashboard(tab);
    assert.equal(await tab.evaluate(() => sessionStorage.getItem('pepes_player_token')),null);

    // An independent browser/device logging out must not revoke this browser.
    const device = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
    try {
      const other = await device.newContext();
      const auth = await other.request.post(base+'/api/player/login',{data:{teamId:'a',password:'a-pass'}});
      assert.equal(auth.status(),200);
      assert.equal((await other.request.post(base+'/api/player/logout',{data:{}})).status(),200);
      assert.equal((await context.request.post(base+'/api/player/state',{data:{}})).status(),200);
      await other.request.post(base+'/api/player/login',{data:{teamId:'b',password:'b-pass'}});
      assert.equal((await other.request.post(base+'/api/player/launch-shell',{data:{targetId:'a'}})).status(),200);
    } finally {await device.close();}

    // Closing Chrome discards sessionStorage; its persistent cookie restores auth.
    await context.close(); context = null;
    const port = Number(new URL(base).port);
    await stop();
    await start(port); // Genuine server process restart, same persisted test DB.
    page = await openBrowser();
    await page.goto(base+'/player.html');
    await dashboard(page);
    await page.locator('#personal-alert-bar').waitFor({state:'visible'});
    assert.equal((await page.evaluate(async () => (await fetch('/api/shop')).json())).wallet.teamId,'a');
    // Cookie-only auth must still allow external preparation and a real spin.
    const popupPromise = context.waitForEvent('page');
    await page.locator('[data-spin-outside-id]').click();
    const popup = await popupPromise;
    await popup.locator('#roulette-spin').waitFor({state:'visible'});
    await popup.locator('#roulette-spin').click();
    await page.waitForFunction(() => rouletteBusy);
    await page.waitForFunction(() => !rouletteBusy, null, {timeout:25000});
    assert.equal((await context.request.post(base+'/api/player/state',{data:{}})).status(),200);
    assert.equal(await page.locator('[data-spin-id]').count(),0);
    await popup.close();

    // A temporary outage must not revoke the cookie or clear the dashboard.
    let logoutCalls = 0;
    const countLogout = request => {if(request.url().endsWith('/api/player/logout'))logoutCalls++;};
    page.on('request',countLogout);
    await page.route('**/api/player/state', route => route.fulfill({status:503,json:{error:'Test outage'}}));
    await page.evaluate(() => document.dispatchEvent(new Event('player-session-changed')));
    await page.waitForTimeout(350);
    assert.equal(await page.locator('#player-dashboard-section').isVisible(),true);
    assert.equal(logoutCalls,0);
    await page.unroute('**/api/player/state');
    await page.evaluate(() => document.dispatchEvent(new Event('player-session-changed')));
    await dashboard(page);
    await page.route('**/api/player/logout', route => route.fulfill({status:503,json:{error:'Test outage'}}));
    await page.locator('#btn-logout').click();
    assert.equal(await page.locator('#player-dashboard-section').isVisible(),true);
    assert.ok((await context.cookies()).some(c=>c.name==='pepes_team_session'));
    await page.unroute('**/api/player/logout');

    const second = await context.newPage();
    await second.goto(base+'/player.html');
    await dashboard(second);
    // Simulate an old connection resolving after a new team has logged in.
    // This also exercises transports that settle despite AbortController.
    await page.evaluate(() => {
      const original = window.fetch;
      let delayed = false;
      window.fetch = (url, options) => {
        if (String(url).endsWith('/player/events') && !delayed) {
          delayed = true;
          return new Promise(resolve => { window.finishOldStream = () => resolve(new Response('', {status:401})); });
        }
        return original(url, options);
      };
      document.dispatchEvent(new Event('player-session-changed'));
    });
    await page.waitForFunction(() => typeof window.finishOldStream === 'function');
    // Cookie changes synchronize to an existing tab, without storing a secret.
    await second.evaluate(async () => DataStore.loginPlayer('b','b-pass'));
    await dashboard(page,'Equipo B');
    await dashboard(second,'Equipo B');
    await page.evaluate(() => window.finishOldStream());
    await page.waitForTimeout(150);
    await dashboard(page,'Equipo B');
    assert.equal(await page.evaluate(() => localStorage.getItem('pepes_auth_changed').includes('pass')),false);
    await second.locator('#btn-logout').click();
    await page.locator('#player-login-section').waitFor({state:'visible'});
    await second.locator('#player-login-section').waitFor({state:'visible'});
    assert.equal((await context.cookies()).some(c=>c.name==='pepes_team_session'),false);
    await page.reload();
    await page.locator('#player-login-section').waitFor({state:'visible'});
    assert.equal(await page.locator('#player-dashboard-section').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('REMEMBERED_BROWSER_OK: browser+server restart, cross-tab login/logout, isolated devices, HttpOnly cookie, offline safety, shop+alerts.');
  } finally {
    if (context) await context.close();
    await stop();
    // Only remove the unique temp directory created by this test.
    if (path.dirname(temp)===os.tmpdir() && path.basename(temp).startsWith('pepes-auth-ui-')) fs.rmSync(temp,{recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
