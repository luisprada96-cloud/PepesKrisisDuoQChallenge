// Real HTTP + SSE + Chrome integration, with a temporary database and no cron jobs.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {existsSync, mkdirSync} = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const virtualPython = path.join(__dirname, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.PEPES_TEST_PYTHON || (existsSync(virtualPython) ? virtualPython : 'python');
const fixture = spawn(python, ['-u', '-B', '-c', `
import server
import test_shell_penalties as fixtures
server.remote_backend = None
case = fixtures.ShellEndpointTests()
case.setUp()
try:
    db = server.load_db()
    db['duos'][0]['teamName'] = 'Dúo atacante · PRUEBA LOCAL'
    db['duos'][1]['teamName'] = 'LosELOgidos · PRUEBA LOCAL'
    server.save_db(db)
    print('OVERLAY_TEST_URL=' + case.base, flush=True)
    input()
finally:
    server.player_sessions.clear()
    server.notify_shell_receivers()
    case.tearDown()
`], {cwd:__dirname, env:{...process.env, PEPES_STORAGE:'local'}, stdio:['pipe','pipe','pipe']});
fixture.stderr.pipe(process.stderr);

const ready = new Promise((resolve, reject) => {
  let output = '';
  const timer = setTimeout(() => reject(new Error('Temporary overlay server did not start.')), 20000);
  fixture.stdout.on('data', chunk => {
    output += chunk;
    const match = output.match(/OVERLAY_TEST_URL=(http:\/\/127\.0\.0\.1:\d+)/);
    if (match) { clearTimeout(timer); resolve(match[1]); }
  });
  fixture.once('error', error => {clearTimeout(timer); reject(error);});
  fixture.once('exit', code => {clearTimeout(timer); reject(new Error('Fixture exited: '+code));});
});

(async () => {
  let browser;
  try {
    const base = await ready;
    browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
    const page = await browser.newPage({viewport:{width:1920,height:1080}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.overlaySounds = 0;
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function(...args) {window.overlaySounds++; window.overlayAudioDuration = this.buffer?.duration; return start.apply(this,args);};
    });
    await page.goto(base+'/overlay.html');
    await page.locator('#team').selectOption('b');
    await page.locator('#password').fill('b-pass');
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Conectado'));
    await page.locator('#hide').click();
    assert.equal(await page.locator('#alert').isVisible(),false);
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor),'rgba(0, 0, 0, 0)');
    const login = await (await page.request.post(base+'/api/player/login', {data:{teamId:'a',password:'a-pass'}})).json();
    assert.equal(login.success,true);
    const launched = await (await page.request.post(base+'/api/player/launch-shell', {data:{sessionToken:login.sessionToken,targetId:'b'}})).json();
    assert.equal(launched.success,true);
    assert.equal(launched.attack.status,'PENDING_SPIN');
    await page.waitForFunction(() => !document.querySelector('#alert').hidden && window.overlaySounds > 0);
    assert.match(await page.locator('#attacker').textContent(),/Dúo atacante/);
    assert.match(await page.locator('#target').textContent(),/LosELOgidos/);
    assert.equal(await page.evaluate(id => JSON.parse(localStorage.getItem('pepes_obs_seen_default_b')).includes(id),launched.attack.id),true);
    assert.ok(Math.abs(await page.evaluate(() => window.overlayAudioDuration) - 10) < .03);
    await page.waitForTimeout(7000);
    assert.equal(await page.locator('.message').evaluate(el => getComputedStyle(el).opacity), '1');
    mkdirSync(path.join(__dirname,'preview'),{recursive:true});
    await page.screenshot({path:path.join(__dirname,'preview','overlay-live.png'),omitBackground:true});
    const session = await page.evaluate(() => JSON.parse(localStorage.getItem('pepes_obs_session_v1_default')));
    assert.ok(session.token);
    assert.equal('password' in session,false);
    const state = await (await page.request.post(base+'/api/player/state', {data:{sessionToken:session.token}})).json();
    assert.equal(state.duo.pendingShellAttacks.length,1);
    assert.equal(state.duo.pendingShellAttacks[0].id,launched.attack.id);
    assert.equal((state.duo.activeDebuffs || []).length,0,'Receiving an alert must not spin the roulette.');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Conectado'));
    assert.equal(await page.locator('#alert').isVisible(),false,'Do not replay pending attacks after reload.');
    assert.equal(await page.evaluate(() => window.overlaySounds),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: real HTTP/SSE delivers a single animated, audible alert before opening; reload does not replay it. Temporary data only.');
  } finally {
    if (browser) await browser.close();
    if (!fixture.killed && fixture.exitCode === null) fixture.stdin.end('\n');
    const timer = setTimeout(() => fixture.kill(),5000);
    timer.unref();
    fixture.once('exit', () => clearTimeout(timer));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
