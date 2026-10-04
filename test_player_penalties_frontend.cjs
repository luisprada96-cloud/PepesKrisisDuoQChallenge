// Browser regression for the team's punishment tabs; all data is mocked.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext();
    const penalty = (id, scope, requirements = {}, status = 'ACTIVE') => ({id, scope, requirements, status,
      penalty:{name:id, icon:'⚡', desc:'Condición de prueba'}, attacker:'Rival', assignedAt:'2026-10-03T12:00:00Z'});
    const team = {id:'test', teamName:'Pruebas', player1:{displayName:'Ana', name:'Uno', tag:'EUW', puuid:'p1'},
      player2:{displayName:'Luis', name:'Dos', tag:'EUW', puuid:'p2'}, tier:'Gold', division:'IV', blueShells:2,
      activeDebuffs:[
        ...Array.from({length:22}, (_, i) => penalty(`Individual ${i}`, 'ONE', {assignmentVersion:2, assignedPlayer:'player1'})),
        penalty('Para Luis', 'ONE', {assignmentVersion:2, assignedPlayer:'player2'}),
        penalty('Dúo', 'BOTH'), penalty('Anterior', 'ONE'),
        penalty('Sin asignación', 'ONE', {assignmentVersion:2}),
        penalty('Cuenta antigua', 'ONE', {assignedPlayer:'player2', assignedAccount:{name:'Viejo', tag:'EUW', puuid:'old'}}),
        ...Array.from({length:21}, (_, i) => penalty(`Cumplido ${i}`, 'BOTH', {}, 'COMPLETED')),
        penalty('Retirado', 'BOTH', {}, 'CANCELLED')], pendingShellAttacks:[], outgoingShellAttacks:[]};
    await context.addInitScript(value => {
      sessionStorage.setItem('pepes_player_token', 'mock-session');
      sessionStorage.setItem('pepes_player_session', JSON.stringify(value));
      const original = window.fetch;
      window.fetch = (url, options) => String(url).endsWith('/player/events')
        ? Promise.resolve(new Response(new ReadableStream(), {headers:{'Content-Type':'text/event-stream'}}))
        : original(url, options);
    }, team);
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        const result = url.pathname === '/api/duos' ? [team] : {success:true, duo:team};
        return route.fulfill({contentType:'application/json', body:JSON.stringify(result)});
      }
      const file = url.pathname.slice(1);
      if (!['player.html','player.js','data.js','styles.css','alerts.js','roulette-core.js','roulette-window.js'].includes(file)) {
        return route.fulfill({status:404, body:''});
      }
      return route.fulfill({contentType:file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html',
        body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://pepes.test/player.html');
    await page.locator('#player-shells-tab').waitFor();
    assert.equal(await page.locator('#player-shells-panel').isVisible(), true);
    assert.equal(await page.locator('#player-penalties-panel').isVisible(), false);
    await page.locator('#player-shells-tab').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#player-penalties-tab').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#player-penalties-tab').evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('#player-penalties-count').textContent(), '26');
    assert.equal(await page.locator('#player-pending-count').textContent(), '26');
    assert.equal(await page.locator('#active-debuffs-list .player-penalty-card').count(), 26);
    assert.equal(await page.locator('[data-penalty-group=player1] .player-penalty-card').count(), 22);
    assert.equal(await page.locator('[data-penalty-group=player2] .player-penalty-card').count(), 1);
    assert.equal(await page.locator('[data-penalty-group=both] .player-penalty-card').count(), 1);
    assert.equal(await page.locator('[data-penalty-group=any]').count(), 0);
    assert.doesNotMatch(await page.locator('#active-debuffs-list').textContent(), /Cualquiera de los dos|Castigos anteriores/);
    assert.equal(await page.evaluate(() => activeDuo.activeDebuffs.some(d => d.id === 'Anterior')), true, 'legacy records must not be deleted');
    assert.match(await page.locator('[data-penalty-group=previous]').textContent(), /Viejo#EUW/);
    assert.equal(await page.locator('[data-penalty-group=unassigned] .player-penalty-card').count(), 1);
    await page.locator('[data-player-penalty-view=history]').click();
    assert.equal(await page.locator('.player-penalty-history .player-penalty-card').count(), 20);
    assert.equal(await page.locator('#player-history-count').textContent(), '22');
    await page.locator('[data-player-history-step="1"]').click();
    assert.equal(await page.locator('.player-penalty-history .player-penalty-card').count(), 2);
    assert.equal(await page.locator('.penalty-status-retired').textContent(), ' Retirado');
    await page.evaluate(() => renderDashboardData());
    assert.equal(await page.locator('#player-penalties-panel').isVisible(), true);
    assert.equal(await page.locator('[data-player-penalty-view=history]').getAttribute('aria-pressed'), 'true');
    assert.match(await page.locator('.player-history-pagination').textContent(), /Página 2 de 2/);
    for (const width of [1280,390,320]) {
      await page.setViewportSize({width,height:850});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `history width ${width}`);
      await page.locator('[data-player-penalty-view=pending]').click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `pending width ${width}`);
      await page.locator('#player-shells-tab').click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `shells width ${width}`);
      await page.locator('#player-penalties-tab').click();
    }
    await page.evaluate(() => {
      activeDuo.player1.displayName = '<img src=x onerror="window.injected=true">';
      activeDuo.activeDebuffs[0].penalty.icon = '<img src=x>';
      renderActiveDebuffs();
    });
    assert.equal(await page.locator('#active-debuffs-list img').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.evaluate(() => {
      window.__allDebuffs = activeDuo.activeDebuffs;
      activeDuo.activeDebuffs = activeDuo.activeDebuffs.filter(d => d.id === 'Anterior');
      renderActiveDebuffs();
    });
    assert.equal(await page.locator('#player-pending-count').textContent(), '0');
    assert.equal(await page.locator('[data-penalty-group=any]').count(), 0);
    assert.equal(await page.locator('#active-debuffs-list .player-penalty-card').count(), 0);
    await page.evaluate(() => { activeDuo.activeDebuffs = window.__allDebuffs; });
    await page.evaluate(() => {
      activeDuo.activeDebuffs = activeDuo.activeDebuffs.filter(playerPenaltyFinished);
      renderDashboardData();
    });
    assert.match(await page.locator('#active-debuffs-list').textContent(), /No tenéis castigos pendientes/);
    assert.equal(await page.locator('#player-penalties-count').textContent(), '0');
    await page.locator('[data-player-penalty-view=history]').click();
    assert.equal(await page.locator('.player-penalty-history .player-penalty-card').count(), 20);
    await page.evaluate(() => {activeDuo = {...activeDuo, id:'another'}; showDashboardView();});
    assert.equal(await page.locator('#player-shells-panel').isVisible(), true, 'another team starts in inventory');
    assert.deepEqual(errors, []);
    console.log('Player punishment tabs passed: assigned groups, hidden legacy free-choice cards without deletion, matching counters, history pagination, refresh, keyboard, mobile and escaping.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
