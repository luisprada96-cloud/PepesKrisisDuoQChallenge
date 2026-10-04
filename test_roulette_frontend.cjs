// Optional browser regressions: NODE_PATH must provide Playwright; uses installed Chrome.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

(async () => {
  const core = {window: {}, Date, setTimeout, clearTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'roulette-core.js'), 'utf8'), core);
  const state = {phase: 'spinning', teamName: 'Dúo de prueba', startedAt: 1000, holdMs: 13500,
    penalty: {name: 'Sin Flash', icon: '⚡', desc: 'Juega sin Flash en la próxima partida.'}};
  assert.equal(core.window.ShellRoulette.revealMs, 4704);
  assert.equal(core.window.ShellRoulette.frame(state, 5703).revealed, false);
  for (let elapsed = 0; elapsed < core.window.ShellRoulette.revealMs; elapsed += 25) {
    assert.doesNotMatch(core.window.ShellRoulette.frame(state, state.startedAt + elapsed).name, /BOTAS/);
  }
  assert.equal(core.window.ShellRoulette.frame(state, 5704).revealed, true);
  assert.equal(core.window.ShellRoulette.frame({...state,penalty:{...state.penalty,assignment:'Debe cumplirlo: Luis'}},5704).assignment,'Debe cumplirlo: Luis');
  assert.equal(core.window.ShellRoulette.frame({...state,penalty:{...state.penalty,assignment:'Luis'}},5703).assignment,undefined);

  assert.equal(core.window.ShellRoulette.frame(state, 19203).done, false);
  assert.equal(core.window.ShellRoulette.frame(state, 19204).done, true);
  assert.equal(core.window.ShellRoulette.frame({phase: 'prepared', message: 'Pulsa Girar'}).nextIn, null);

  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext();
    let spinCount = 0;
    let failSpin = false;
    let popupApiCalls = 0;
    const errors = [];
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    const pending = {id: 'shell-1', attackerName: 'Rival', launchedAt: '2026-10-01'};

    const assignedPenalty = {id:'penalty-test', scope:'ONE', penalty:state.penalty, requirements:{assignmentVersion:2,assignedPlayer:'player2',
      assignedAccount:{displayName:'Luis',name:'Dos',tag:'EUW',puuid:'p2'}},attacker:'Rival',timestamp:'01/10/2026',status:'ACTIVE'};
    const team = {id: 'test', teamName: 'Dúo de prueba', player1: {name: 'Uno', tag: 'EUW'}, player2: {name: 'Dos', tag: 'EUW'},
      tier: 'Gold', division: 'IV', lp: 0, blueShells: 1, pendingShellAttacks: [pending], outgoingShellAttacks: [], activeDebuffs: []};
    await context.addInitScript(value => {
      if (location.pathname === '/player.html') {
        sessionStorage.setItem('pepes_player_token', 'private-session');
        sessionStorage.setItem('pepes_player_session', JSON.stringify(value));
      }
      const fetchOriginal = window.fetch;
      window.fetch = (url, options) => String(url).endsWith('/player/events')
        ? Promise.resolve(new Response(new ReadableStream({start(controller) {
            options.signal.addEventListener('abort', () => {try {controller.close();} catch (_) {}});
          }}), {headers: {'Content-Type': 'text/event-stream'}}))
        : fetchOriginal(url, options);
    }, team);
    await context.route('**/*', async route => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        if (req.frame().page().url().includes('roulette.html')) popupApiCalls++;
        let result = {success: true};
        if (url.pathname === '/api/duos') result = [team];
        if (url.pathname === '/api/player/state') result = {success: true, duo: team};
        if (url.pathname === '/api/player/spin-shell') {
          spinCount++;
          assert.equal(req.postDataJSON().sessionToken, 'private-session');
          await new Promise(resolve => setTimeout(resolve, 300));
          if (failSpin) return route.fulfill({status: 503, contentType: 'application/json',
            body: JSON.stringify({success: false, error: 'Fallo de prueba'})});
          result = {success: true, penalty: state.penalty, penaltyInstance:assignedPenalty, duo: {...team, pendingShellAttacks: [],
            activeDebuffs: [assignedPenalty]}};
        }
        return route.fulfill({contentType: 'application/json', body: JSON.stringify(result)});
      }
      const file = url.pathname.slice(1);
      const allowed = ['player.html', 'data.js', 'alerts.js', 'player.js', 'styles.css', 'roulette.html',
        'roulette.css', 'roulette-core.js', 'roulette-window.js', 'roulette-popup.js'];
      if (!allowed.includes(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html',
        body: fs.readFileSync(path.join(__dirname, file))});
    });
    const page = await context.newPage();
    await page.goto('http://pepes.test/player.html');
    await page.locator('[data-spin-id]').waitFor();
    assert.equal(await page.locator('[data-spin-outside-id]').textContent(), 'Girar ruleta fuera ↗');

    // Normal spin chooses a result and animates solely in the team panel.
    await page.locator('[data-spin-id]').click();
    await page.locator('#inline-roulette-container').waitFor({state: 'visible'});
    assert.equal(spinCount, 1);
    assert.equal(context.pages().length, 1, 'normal spin must never open a popup');
    assert.equal(await page.locator('#open-roulette-window').isVisible(), false);
    assert.equal(await page.locator('[data-spin-outside-id]').isEnabled(), false);
    await page.locator('#inline-roulette-desc').waitFor({state: 'visible'});
    assert.equal(await page.locator('#inline-roulette-assignment').textContent(), 'Debe cumplirlo: Luis · Dos#EUW');
    assert.equal(await page.locator('#inline-roulette-assignment').isVisible(), true);

    await page.waitForTimeout(1000);
    assert.equal(await page.locator('#inline-roulette-container').isVisible(), true);
    await page.waitForFunction(() => !rouletteBusy, undefined, {timeout: 25000});
    await page.locator('#player-penalties-tab').click();
    await page.locator('#active-debuffs-list').getByText('Sin Flash', {exact: true}).waitFor();
    assert.match(await page.locator('#active-debuffs-list .penalty-assignment').textContent(), /Luis · Dos#EUW/);
    await page.locator('#player-shells-tab').click();


    // Restore the fixture for another shell, without changing the production database.
    await page.evaluate(value => {activeDuo.pendingShellAttacks = [value]; renderDashboardData();}, pending);
    const popupPromise = page.waitForEvent('popup');
    await page.locator('[data-spin-outside-id]').click();
    let popup = await popupPromise;
    await popup.waitForLoadState();
    await popup.locator('#roulette-spin').waitFor({state: 'visible'});
    assert.equal(await popup.locator('#roulette-name').textContent(), 'LISTA PARA GIRAR');
    await page.waitForTimeout(700);
    assert.equal(spinCount, 1, 'opening the external window must not choose a penalty');
    assert.equal(await page.evaluate(() => rouletteBusy), false);
    assert.equal(await page.locator('#inline-roulette-container').isVisible(), false);
    assert.equal(await popup.evaluate(() => sessionStorage.getItem('pepes_player_token')), null);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('pepes_player_token')), 'private-session');

    // Spoofed messages cannot start a spin or replace the popup's content.
    await page.evaluate(() => window.postMessage({type: 'pepes-roulette-spin', attackId: 'shell-1'}, location.origin));
    await popup.evaluate(() => window.postMessage({type: 'pepes-roulette-state', channel: location.hash.slice(1),
      state: {phase: 'error', teamName: 'Intruso', message: 'No'}}, location.origin));
    assert.equal(await popup.locator('#roulette-team').textContent(), team.teamName);
    assert.equal(spinCount, 1);

    if (process.env.ROULETTE_SCREENSHOT) await popup.screenshot({path: process.env.ROULETTE_SCREENSHOT});
    // Only the popup's Girar button chooses the penalty. Duplicate clicks/messages cannot repeat it.
    await popup.locator('#roulette-spin').click();
    await popup.evaluate(() => {
      const message = {type: 'pepes-roulette-spin', channel: location.hash.slice(1), attackId: 'shell-1'};
      window.opener.postMessage(message, location.origin);
      window.opener.postMessage(message, location.origin);
    });
    await popup.locator('#roulette-box.revealed').waitFor();
    assert.equal(spinCount, 2);
    assert.equal(await popup.locator('#roulette-name').textContent(), 'SIN FLASH');
    assert.equal(await popup.locator('#roulette-assignment').textContent(), 'Debe cumplirlo: Luis · Dos#EUW');
    assert.equal(await popup.locator('#roulette-assignment').isVisible(), true);
    if (process.env.ASSIGNMENT_ROULETTE_SCREENSHOT) await popup.screenshot({path:process.env.ASSIGNMENT_ROULETTE_SCREENSHOT});

    assert.equal(await popup.locator('#roulette-spin').isVisible(), false);
    assert.equal(await page.locator('#inline-roulette-container').isVisible(), false, 'external mode animates only externally');
    await page.waitForFunction(() => !rouletteBusy, undefined, {timeout: 25000});
    await page.locator('#player-penalties-tab').click();
    await page.locator('#active-debuffs-list').getByText('Sin Flash', {exact: true}).waitFor();
    assert.match(await page.locator('#active-debuffs-list .penalty-assignment').textContent(), /Luis · Dos#EUW/);
    await page.locator('#player-shells-tab').click();

    assert.equal(await page.locator('[data-spin-id]').count(), 0);
    assert.equal(await popup.locator('#roulette-name').textContent(), 'SIN FLASH');
    for (const width of [680, 320]) {
      await popup.setViewportSize({width, height: 460});
      assert.equal(await popup.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }

    // Reopening retains the result and never spins again.
    await popup.close();
    const reopen = page.waitForEvent('popup');
    await page.locator('#open-roulette-window').click();
    popup = await reopen;
    await popup.locator('#roulette-box.revealed').waitFor();
    assert.equal(spinCount, 2);
    assert.equal(await popup.locator('#roulette-spin').isVisible(), false);

    // Failed external requests let the receiver retry explicitly inside the same window.
    await page.evaluate(value => {activeDuo.pendingShellAttacks = [value]; renderDashboardData();}, pending);
    failSpin = true;
    const pagesBefore = context.pages().length;
    await page.locator('[data-spin-outside-id]').click();
    await popup.locator('#roulette-spin').waitFor({state: 'visible'});
    assert.equal(spinCount, 2);
    await popup.locator('#roulette-spin').click();
    await popup.waitForFunction(() => document.getElementById('roulette-name').textContent === 'NO SE PUDO GIRAR');
    assert.equal(spinCount, 3);
    assert.equal(context.pages().length, pagesBefore);
    assert.equal(await popup.locator('#roulette-spin').isEnabled(), true);
    assert.equal(await page.evaluate(() => rouletteBusy), false);
    failSpin = false;
    await popup.locator('#roulette-spin').click();
    await popup.waitForFunction(() => document.getElementById('roulette-spin').hidden);
    assert.equal(spinCount, 4);
    await popup.locator('#roulette-box.revealed').waitFor();
    // The popup keeps animating if the parent is closed after the result was chosen.
    await page.close();
    assert.equal(await popup.locator('#roulette-name').textContent(), 'SIN FLASH');
    await popup.close();

    // Blocking the external window must leave the shell pending and the normal button usable.
    const blockedPage = await context.newPage();
    await blockedPage.goto('http://pepes.test/player.html');
    await blockedPage.locator('[data-spin-outside-id]').waitFor();
    await blockedPage.evaluate(() => {window.open = () => null;});
    await blockedPage.locator('[data-spin-outside-id]').click();
    assert.equal(spinCount, 4);
    assert.match(await blockedPage.locator('#player-toast-notification').textContent(), /ventanas emergentes/);
    assert.equal(await blockedPage.locator('[data-spin-id]').isEnabled(), true);
    await blockedPage.locator('[data-spin-id]').click();
    await blockedPage.locator('#inline-roulette-container').waitFor({state: 'visible'});
    assert.equal(spinCount, 5);
    assert.equal(popupApiCalls, 0);
    assert.deepEqual(errors, []);
    console.log('Roulette regressions passed: normal panel spin, external preparation without mutation, explicit Girar, single request, retry, blocked popup, result hold, dashboard update, no credentials/API in popup.');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
