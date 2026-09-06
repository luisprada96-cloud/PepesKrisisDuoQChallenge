// Optional browser regressions: requires Playwright and Chromium.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const originalFetch = window.fetch;
      window.__alarmStarts = 0;
      window.__notificationStreams = [];
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function(...args) { window.__alarmStarts++; return start.apply(this, args); };
      window.fetch = (url, options) => {
        if (String(url).endsWith('/player/events')) {
          return Promise.resolve(new Response(new ReadableStream({start(controller) {
            window.__notificationStreams.push(controller);
            options.signal.addEventListener('abort', () => { try { controller.close(); } catch (_) {} });
          }}), {headers: {'Content-Type': 'text/event-stream'}}));
        }
        return originalFetch(url, options);
      };
      window.__notify = payload => {
        const controller = window.__notificationStreams.at(-1);
        controller.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(payload) + '\n\n'));
      };
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const team = (id, netLp, wins, losses) => ({id, teamName: id, tier: 'Gold', division: 'IV', lp: 0, netLp, wins, losses, blueShells: 1, historyCount: 65,
      player1: {name: 'Jugador 1', tag: 'EUW', mainRole: 'TOP'}, player2: {name: 'Jugador 2', tag: 'EUW', mainRole: 'JUNGLE'}, activeDebuffs: [], history: []});
    const duos = [team('Segundo', 100, 4, 6), team('Primero', 100, 8, 2), team('Tercero', 20, 9, 1)];
    duos[0].netLp = 9999; // Progress must not override current rank.
    duos[1].division = 'III';
    duos[1].eloHistory = [1200,1250,1210,1300].map((totalLp,i)=>({date:`2026-09-0${i+1}`,totalLp,tier:'Gold',division:'IV',lp:totalLp-1200,wins:10+i,losses:5}));
    const historyOffsets = [];
    let failReads = false;
    let failWrites = false;
    let syncCount = 0;
    const spins = [];
    const publicRules = {penaltyCatalog: [{id: 'no_flash_one', name: 'Sin Flash · UNO', icon: '⚡', desc: 'Al menos uno debe jugar sin Flash.'}, {id: 'return_shell', name: 'Devuelve el caparazón', icon: '↩️', desc: 'Vuelve al equipo atacante.'}], penaltyWeights: {no_flash_one: 100, return_shell: 0}};
    publicRules.shellRewardRules = {inventoryLimit: 5, perMatchLimit: 2, rules: ['Racha', 'Pentakill', 'Asesinatos', 'Asistencias', 'KDA perfecto'].map(name => ({name, requirement: 'Requisito individual'}))};
    const history = Array.from({length: 65}, (_, i) => ({matchId: `EUW1_${1000-i}`, result: 'WIN', championP1: 'Ahri', kda1: '1/0/1', duration: '20m', date: '05/09/2026 12:00', lpChange: '', gameEndTimestamp: 1800000000000-i}));
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        if (failReads && request.method() === 'GET') return route.abort();
        if (failWrites && request.method() === 'POST') return route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({success: false, error: 'Sin conexión de prueba'})});
        let result;
        if (url.pathname.endsWith('/history')) {
          const offset = Number(url.searchParams.get('offset'));
          historyOffsets.push(offset);
          result = {matches: history.slice(offset, offset + 30), total: history.length};
        } else if (url.pathname === '/api/duos') result = duos;
        else if (url.pathname === '/api/config') result = {challengeTitle: 'Prueba', endDate: '2026-08-31', prizePool: 'Prueba', ...publicRules};
        else if (url.pathname === '/api/trophies') result = {status: 'provisional', roleMode: 'main_role_matches', endDate: '2030-01-01', cards: ['champion','TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY','dishonor'].map(id => ({id, title: id, icon: '🏆', description: 'Premio', entries: id === 'UTILITY' ? [] : [{name: 'Jugador', teamName: 'Equipo', value: '5.00 KDA', games: 10}]}))};
        else if (url.pathname === '/api/events') result = [{type: 'SHELL_LAUNCHED', attacker: 'Lanzamiento oculto'}, {type: 'SHELL_SPUN', attacker: 'Atacante', target: 'Receptor', penalty: {name: 'Sin Flash', desc: 'Castigo abierto'}}, {type: 'PENALTY_ADMIN_CORRECTION', target: 'Corrección oculta'}];
        else if (url.pathname === '/api/sync/status') result = {};
        else if (url.pathname === '/api/admin/login') result = {success: true, duos, config: {penaltyWeights: {}}, penaltyCatalog: []};
        else if (url.pathname === '/api/sync') { syncCount++; result = {success: true, job: {running: true}}; }
        else if (url.pathname === '/api/player/login') result = {success: true, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}, sessionToken: 'fake'};
        else if (url.pathname === '/api/player/spin-shell') { spins.push(request.postDataJSON()); result = {success: true, penalty: {name: 'Sin Flash', desc: 'Prueba', icon: 'X'}, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}}; }
        else if (url.pathname === '/api/player/state') result = {success: true, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}};
        else result = {success: true};
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(result)});
      }
      const filename = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      if (!['torneo.html','torneo.js','index.html','admin.html','player.html','app.js','admin.js','player.js','data.js','alerts.js','styles.css'].includes(filename)) return route.fulfill({status:404, body:''});
      return route.fulfill({contentType: filename.endsWith('.js') ? 'text/javascript' : filename.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(__dirname, filename))});
    });
    await page.goto('http://pepes.test/');
    await page.waitForSelector('#leaderboard-tbody .duo-row');
    assert.equal(await page.locator('#personal-alert-bar').isVisible(), false);
    assert.equal(await page.locator('#leaderboard-tbody .duo-row').first().getAttribute('data-id'), 'Primero');
    assert.equal(await page.locator('#stat-top-duo').textContent(), 'Primero');
    assert.equal(historyOffsets.length, 0, 'history must not be downloaded on initial load');
    await page.locator('.duo-row[data-id="Primero"]').click();
    assert.equal(await page.locator('#duo-insights-Primero .elo-point').count(), 4);
    await page.locator('#duo-insights-Primero .elo-point').first().focus();
    assert.match(await page.locator('#duo-insights-Primero .elo-chart-detail').textContent(), /10W/);
    await page.locator('.duo-row[data-id="Primero"]').click();
    assert.equal(await page.evaluate(() => {
      const ranks = [
        {id:'unranked',tier:'Unranked',lp:999},
        {id:'iron',tier:'Iron',division:'IV',lp:0},
        {id:'gold4',tier:'Gold',division:'IV',lp:99},
        {id:'gold3',tier:'Gold',division:'III',lp:0},
        {id:'master',tier:'Master',lp:500},
        {id:'grandmaster',tier:'Grandmaster',lp:600},
        {id:'challenger',tier:'Challenger',lp:1000}
      ];
      return ranks.sort(compareCompetitionRank).map(x => x.id).join(',');
    }), 'challenger,grandmaster,master,gold3,gold4,iron,unranked');

    assert.equal(await page.locator('#rules, #trophies, #shell-rewards, #roulette-rules').count(), 0);
    await page.waitForFunction(() => document.querySelector('#recent-attacks-tbody').textContent.includes('Sin Flash'));
    assert.equal(await page.locator('#recent-attacks-tbody tr').count(), 1);
    assert.doesNotMatch(await page.locator('#recent-attacks-tbody').textContent(), /Lanzamiento oculto|Corrección oculta/);
    await page.locator('[data-history-id="Primero"]').click();
    await page.waitForSelector('.history-navigation');
    assert.deepEqual(historyOffsets, [0]);
    await page.getByRole('button', {name:'Siguiente', exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#modal-content').textContent.includes('desde la 31'));
    assert.deepEqual(historyOffsets, [0,30]);
    await page.locator('#modal-close').click();
    failReads = true;
    await page.evaluate(() => triggerManualSync());
    assert.equal(await page.locator('#leaderboard-tbody .duo-row').count(), 3);
    assert.match(await page.locator('#connection-status').textContent(), /Conexión interrumpida/);
    assert.equal(syncCount, 0, 'public refresh must not start Riot');
    failReads = false;
    await page.getByRole('link', {name:'Torneo y premios', exact:true}).click();
    await page.waitForURL('**/torneo.html');
    await page.waitForSelector('.trophy-card');
    assert.equal(await page.locator('.trophy-card').count(), 7);
    assert.match(await page.locator('#trophies-status').textContent(), /provisional/);
    assert.match(await page.locator('#trophies-note').textContent(), /Solo cuentan las partidas jugadas en ese rol/);
    assert.match(await page.locator('.trophy-card').nth(5).textContent(), /Sin participantes/);
    assert.equal(await page.locator('#shell-rewards-body tr').count(), 5);
    assert.match(await page.locator('#shell-rewards-limits').textContent(), /5 caparazones.*2 obtenidos/);
    assert.equal(await page.locator('#roulette-rules-list article').count(), 2);
    assert.equal(await page.locator('#roulette-rules-list input, #roulette-rules-list select, #roulette-rules-list button').count(), 0);
    assert.match(await page.locator('#roulette-rules-list').textContent(), /100%/);
    assert.match(await page.locator('#roulette-rules-list .is-disabled').textContent(), /0% · Desactivado/);
    publicRules.penaltyWeights = {no_flash_one: 75, return_shell: 25};
    await page.evaluate(() => refreshRouletteRules());
    assert.match(await page.locator('#roulette-rules-list').textContent(), /75%/);
    assert.equal(await page.locator('#roulette-rules-list .is-disabled').count(), 0);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.locator('#roulette-rules-list').evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await page.setViewportSize({width: 1280, height: 720});
    await page.goto('http://pepes.test/admin.html');
    await page.locator('#admin-pin-input').fill('9999');
    await page.locator('#admin-pin-form button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('admin-pin-overlay').style.display === 'none');
    await page.locator('#btn-sync-matches-admin').click();
    await page.waitForFunction(() => document.getElementById('toast-notification')?.textContent.includes('iniciada'));
    assert.equal(syncCount, 1);
    failWrites = true;
    const failed = await page.evaluate(() => DataStore.saveDuo({id:'fake'}, '9999'));
    assert.equal(failed.success, false);
    assert.equal(await page.evaluate(() => localStorage.getItem('pepes_duoq_teams_v1')), null);
    failWrites = false;
    await page.goto('http://pepes.test/player.html');
    await page.waitForFunction(() => document.querySelectorAll('#login-team-select option').length === 4);
    const dangerous = '<img src=x onerror="window.injected=true">';
    await page.evaluate(value => { allDuos[0].teamName = value; populateTeamsDropdown(); }, dangerous);
    assert.equal(await page.locator('#login-team-select img').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator('#login-team-select').selectOption('Segundo');
    await page.evaluate(() => populateTeamsDropdown());
    assert.equal(await page.locator('#login-team-select').inputValue(), 'Segundo');
    await page.locator('#login-password-input').fill('fake');
    await page.locator('#player-login-form button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('player-dashboard-section').style.display === 'block');
    await page.waitForSelector('#personal-alert-bar:not([hidden])');
    assert.match(await page.locator('#personal-alert-bar').textContent(), /Segundo/);
    await page.waitForFunction(() => window.__notificationStreams.length > 0);
    await page.locator('#toggle-shell-sound').click();
    await page.waitForFunction(() => document.getElementById('toggle-shell-sound').getAttribute('aria-pressed') === 'true');
    const notification = {team: {id: 'Segundo', name: 'Segundo'}, attacks: [{id: 'alarm-1', attackerName: 'Rival'}]};
    await page.evaluate(value => window.__notify(value), notification);
    await page.waitForFunction(() => window.__alarmStarts === 1);
    assert.match(await page.locator('#shell-received-notice').textContent(), /Rival/);
    await page.evaluate(value => window.__notify(value), notification);
    await page.evaluate(() => window.__notify({team: {id: 'Primero'}, attacks: [{id: 'other-team'}]}));
    await page.locator('#toggle-shell-sound').click();
    notification.attacks.push({id: 'alarm-2', attackerName: 'Otro rival'});
    await page.evaluate(value => window.__notify(value), notification);
    await page.waitForFunction(() => document.getElementById('shell-received-notice').textContent.includes('Otro rival'));
    assert.equal(await page.evaluate(() => window.__alarmStarts), 1);
    assert.equal(await page.locator('#toggle-shell-sound').getAttribute('aria-pressed'), 'false');
    await page.locator('#toggle-shell-sound').click();
    await page.evaluate(() => window.__notificationStreams.at(-1).close());
    await page.waitForFunction(() => window.__notificationStreams.length > 1);
    await page.evaluate(value => window.__notify(value), notification);
    await page.waitForFunction(() => document.querySelector('.personal-alert-connection').textContent === '');
    assert.equal(await page.evaluate(() => window.__alarmStarts), 1, 'reconnect must not replay known attacks');
    await page.locator('#toggle-shell-sound').click();
    await page.getByRole('button', {name: 'Cerrar aviso', exact: true}).click();
    await page.locator('#target-team-select').selectOption('Primero');
    await page.evaluate(() => renderDashboardData());
    assert.equal(await page.locator('#target-team-select').inputValue(), 'Primero');
    await page.evaluate(() => {activeDuo.pendingShellAttacks = [{id: "attack'1", attackerName: 'Rival', launchedAt: '2026-09-05'}]; renderDashboardData();});
    await page.locator('[data-spin-id]').click();
    assert.equal(spins[0].attackId, "attack'1");
    assert.equal(spins[0].sessionToken, 'fake');
    await page.locator('#personal-alert-bar').getByRole('button', {name: 'Cerrar sesión', exact: true}).click();
    assert.equal(await page.locator('#personal-alert-bar').isVisible(), false);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('pepes_player_token')), null);
    assert.deepEqual(errors, []);
    console.log('Browser regressions passed: ranking, history, roulette rules, offline state, personal alerts, audio, mute, deduplication, reconnect and logout.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
