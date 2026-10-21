// Optional browser regressions: requires Playwright and Chromium.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const discordTestRequests = [];

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const originalFetch = window.fetch;
      window.__alarmStarts = 0;
      window.__alarmGains = [];
      const connect = GainNode.prototype.connect;
      GainNode.prototype.connect = function(destination, ...args) {
        if (destination instanceof DynamicsCompressorNode) window.__alarmGains.push(this.gain.value);
        return connect.call(this, destination, ...args);
      };
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
    page.on('dialog', dialog => dialog.accept());
    page.on('pageerror', error => errors.push(error.message));
    const team = (id, netLp, wins, losses) => ({id, teamName: id, tier: 'Gold', division: 'IV', lp: 0, netLp, wins, losses, blueShells: 1, historyCount: 65,
      player1: {name: 'Jugador 1', tag: 'EUW', mainRole: 'TOP'}, player2: {name: 'Jugador 2', tag: 'EUW', mainRole: 'JUNGLE'}, activeDebuffs: [], history: []});
    const duos = [team('Segundo', 100, 4, 6), team('Primero', 100, 8, 2), team('Tercero', 20, 9, 1)];
    duos[0].tournamentRecord = {wins:1, losses:3, games:4};
    duos[1].tournamentRecord = {wins:2, losses:0, games:2};
    duos[2].tournamentRecord = {wins:0, losses:0, games:0};
    duos[0].statsBackfill = {remaining:2};
    duos[0].matchDetailsBackfill = {remaining:3};
    duos[0].riotMatchDiscovery = {pendingMatchIds:['pending-one']};
    duos[0].netLp = 9999; // Progress must not override current rank.
    duos[1].division = 'III';
    Object.assign(duos[1].player1, {displayName:'Luis', twitchUrl:'https://twitch.tv/luis_stream', twitchIsLive:false});
    Object.assign(duos[1].player2, {displayName:'Pepe', twitchUrl:'https://twitch.tv/pepe_stream', twitchIsLive:true});
    Object.assign(duos[1].player1, {opggUrl:'https://www.op.gg/lol/summoners/euw/Uno-EUW'});
    Object.assign(duos[1].player2, {opggUrl:'https://op.gg/lol/summoners/euw/Dos-EUW'});
    duos[1].playerInsights = {
      player1: {gamesAnalyzed:10, totals:{kills:30,deaths:10,assists:20}, topChampion:{name:'MonkeyKing',kda:'1.20'}, mostPlayedPosition:{position:'MIDDLE',games:6}},
      player2: {gamesAnalyzed:4, totals:{kills:5,deaths:0,assists:10}, topChampion:{name:'LeeSin',kda:'2.10'}, mostPlayedPosition:{position:'TOP',games:3}}
    };
    duos[0].twitchUrl = 'https://twitch.tv/legacy_channel';
    duos[0].twitchIsLive = true;
    const profileWrites = [];
    const assignedPenalty = {id:'assigned-test',penalty:{name:'Sin Flash',scope:'ONE'},scope:'ONE',status:'ACTIVE',
      requirements:{assignmentVersion:2,assignedPlayer:'player2',assignedAccount:{displayName:'Pepe',name:'Jugador 2',tag:'EUW'}}};
    duos[1].activeDebuffs = [assignedPenalty];


    duos[1].player2.rank = {tier: 'Emerald', division: 'IV', lp: 55};
    duos[2].player2.rank = {tier: 'Unranked', division: '', lp: 0};
    duos[1].eloHistory = [1200,1250,1210,1300].map((totalLp,i)=>({date:`2026-09-0${i+1}`,totalLp,tier:'Gold',division:'IV',lp:totalLp-1200,wins:10+i,losses:5}));
    duos[1].player2.eloHistory = [1700,1750,1720].map((totalLp,i)=>({date:`2026-09-0${i+2}`,totalLp,tier:'Platinum',division:'III',lp:totalLp-1700,wins:20+i,losses:10}));
    duos[1].bestCombinedKdaMatch = {player1:{championName:'MonkeyKing',position:'TOP',kda:'5/2/7'},player2:{championName:'LeeSin',position:'JUNGLE',kda:'2/1/10'},combinedKda:8,kills:7,deaths:3,assists:17,result:'WIN',date:'04/10/2026 19:00'};
    const historyOffsets = [];
    let failReads = false;
    let failWrites = false;
    let playerLoggedIn = false;
    let syncCount = 0;
    const spins = [];
    const publicRules = {penaltyCatalog: [{id: 'no_flash_one', name: 'Sin Flash · UNO', icon: '⚡', desc: 'Al menos uno debe jugar sin Flash.'}, {id: 'return_shell', name: 'Devuelve el pepazo', icon: '↩️', desc: 'Vuelve al equipo atacante.'}], penaltyWeights: {no_flash_one: 100, return_shell: 0}};
    publicRules.shellRewardRules = {inventoryLimit: 5, perMatchLimit: 2, rules: ['Racha', 'Pentakill', 'Asesinatos', 'Asistencias', 'KDA perfecto'].map(name => ({name, requirement: 'Requisito individual'}))};
    const history = Array.from({length: 65}, (_, i) => ({matchId: `EUW1_${1000-i}`, result: 'WIN', championP1: 'Ahri', kda1: '1/0/1', duration: '20m', date: '05/09/2026 12:00', lpChange: '', gameEndTimestamp: 1800000000000-i}));
    await page.context().route('**/*', async route => {
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
        } else if (url.pathname === '/api/duos' && request.method() === 'POST') {
          const {duo: submitted} = request.postDataJSON();
          profileWrites.push(submitted);
          const existing = duos.find(duo => duo.id === submitted.id);
          if (existing) for (const key of ['player1','player2']) if (submitted[key]) Object.assign(existing[key], submitted[key]);
          result = {success:true, duo:existing || submitted};
        } else if (url.pathname === '/api/duos') result = duos;
        else if (url.pathname === '/api/stats/progression') result = {players:[],pendingMatches:0};
        else if (url.pathname === '/api/config') result = {challengeTitle: 'Prueba', endDate: '2026-08-31', prizePool: 'Prueba', ...publicRules};
        else if (url.pathname === '/api/trophies') result = {status: 'provisional', roleMode: 'main_role_matches', endDate: '2030-01-01', cards: ['champion','TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY','dishonor'].map(id => ({id, title: id, icon: '🏆', description: 'Premio', entries: id === 'UTILITY' ? [] : [{name: 'Jugador', teamName: 'Equipo', value: '5.00 KDA', games: 10}]}))};
        else if (url.pathname === '/api/events') result = [{type: 'SHELL_LAUNCHED', attacker: 'Lanzamiento oculto'}, {type: 'SHELL_SPUN', attacker: 'Atacante', target: 'Receptor', ...assignedPenalty, penalty: {...assignedPenalty.penalty,desc:'Castigo abierto'}}, {type: 'PENALTY_ADMIN_CORRECTION', target: 'Corrección oculta'}];
        else if (url.pathname === '/api/sync/status') result = {riot:{lastSuccessAt:1791100000000,lastApiSuccessAt:'2026-10-04T14:44:00+00:00',pending:2},twitch:{lastSuccessAt:1791100000000,error:'Fallo técnico de Twitch'}};
        else if (url.pathname === '/api/admin/login') result = request.postDataJSON().pin === 'wrong' ? {success:false,error:'PIN incorrecto'} : {success: true, duos, config: {penaltyWeights: {}}, penaltyCatalog: []};
        else if (url.pathname === '/api/admin/pickem') result = {success:true,week:'2026-10-12',weeks:['2026-10-12'],periods:{'2026-10-12':{startsAt:1792072800,endsAt:1792360800}},categories:[],predictions:[],closesAt:1792360740,endsAt:1792360800};
        else if (url.pathname === '/api/sync') { syncCount++; result = {success: true, job: {running: true}}; }
        else if (url.pathname === '/api/discord/test') { discordTestRequests.push(request.postDataJSON()); result = {success:true}; }
        else if (url.pathname === '/api/player/login') { playerLoggedIn = true; result = {success: true, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}, sessionToken: 'fake'}; }
        else if (url.pathname === '/api/player/logout') { playerLoggedIn = false; result = {success:true}; }
        else if (url.pathname === '/api/player/spin-shell') { spins.push(request.postDataJSON()); result = {success: true, penalty: {name: 'Sin Flash', desc: 'Prueba', icon: 'X'}, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}}; }
        else if (url.pathname === '/api/player/state') {
          if (!playerLoggedIn) return route.fulfill({status:401,json:{success:false,error:'Sesión caducada'}});
          result = {success: true, duo: {...duos[0], pendingShellAttacks: [], outgoingShellAttacks: []}};
        }
        else result = {success: true};
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(result)});
      }
      const filename = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      if (!['roulette.html','roulette.css','roulette-core.js','roulette-window.js','roulette-popup.js','torneo.html','torneo.js','premios.html','premios.js','navigation.js','index.html','admin.html','player.html','stat-progression.js','app.js','match-history.js','admin.js','admin-overlay.js','player.js','data.js','alerts.js','styles.css'].includes(filename)) return route.fulfill({status:404, body:''});
      return route.fulfill({contentType: filename.endsWith('.js') ? 'text/javascript' : filename.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(__dirname, filename))});
    });
    await page.goto('http://pepes.test/');
    await page.waitForSelector('#leaderboard-tbody .duo-row');
    const bestChampions = page.locator('.best-champions').first();
    assert.match(await bestChampions.textContent(), /Wukong/);
    assert.doesNotMatch(await bestChampions.textContent(), /MonkeyKing/);
    assert.match(await bestChampions.getByAltText('Wukong').getAttribute('src'), /\/MonkeyKing\.png$/);
    const mapped = await page.evaluate(() => ['MonkeyKing', 'Kaisa', 'Chogath', 'AurelionSol', 'Ahri', 'NewChampion'].map(championDisplayName));
    assert.deepEqual(mapped, ['Wukong', "Kai'Sa", "Cho'Gath", 'Aurelion Sol', 'Ahri', 'NewChampion']);
    const assignment = await page.evaluate(() => { const req = {assignedPlayer:'player1', randomChampions:{player1:'MonkeyKing'}}; return {text:penaltyAssignmentText({scope:'ONE',requirements:req}), id:req.randomChampions.player1}; });
    assert.match(assignment.text, /Campeón: Wukong/);
    assert.equal(assignment.id, 'MonkeyKing');
    assert.equal(await page.locator('#personal-alert-bar').isVisible(), false);
    assert.equal(await page.locator('#leaderboard-tbody .duo-row').first().getAttribute('data-id'), 'Primero');
    const completedPenalties = page.locator('#stat-completed-penalties');
    assert.equal(await completedPenalties.textContent(), '0');
    assert.equal(await completedPenalties.locator('..').locator('.stat-label').textContent(), 'Castigos cumplidos');
    await page.evaluate(() => {
      currentDuos[0].activeDebuffs = [
        {status:'COMPLETED', resolved:true},
        {resolved:true},
        {status:'ACTIVE', resolved:false},
        {status:'CANCELLED', resolved:true}
      ];
      currentDuos[2].activeDebuffs = [{status:'COMPLETED'}];
      renderStatsOverview();
    });
    assert.equal(await completedPenalties.textContent(), '3', 'count completed penalties across duos, including legacy resolutions but excluding pending and cancelled penalties');
    await page.evaluate(() => {
      currentDuos[0].activeDebuffs = [];
      currentDuos[2].activeDebuffs = [];
      const savedDuos = currentDuos;
      currentDuos = [];
      renderStatsOverview();
      currentDuos = savedDuos;
    });
    assert.equal(await completedPenalties.textContent(), '0');
    await page.evaluate(() => renderStatsOverview());
    assert.equal(historyOffsets.length, 0, 'history must not be downloaded on initial load');
    assert.match(await page.locator('.duo-row[data-id="Segundo"] .winrate-wrapper').textContent(), /25%\s*1W \/ 3L/);
    assert.equal(await page.locator('.duo-row[data-id="Segundo"] .winrate-bar-fill').evaluate(el=>el.style.width),'25%');
    assert.match(await page.locator('.duo-row[data-id="Tercero"] .winrate-wrapper').textContent(), /0%\s*0W \/ 0L/);
    assert.equal(await page.locator('#stat-total-games').textContent(),'6');
    await page.selectOption('#sort-by','GAMES');
    assert.equal(await page.locator('.duo-row').first().getAttribute('data-id'),'Segundo');
    await page.selectOption('#sort-by','WINRATE');
    assert.equal(await page.locator('.duo-row').first().getAttribute('data-id'),'Primero');
    await page.selectOption('#sort-by','RANK');

    assert.deepEqual(await page.locator('.main-leaderboard-table thead th').allTextContents(), ['Pos', 'Nombre Dúo', 'Integrante 1', 'Integrante 2', 'Winrate %', 'Racha', 'Pepazos', '']);
    assert.doesNotMatch(await page.locator('body').innerText(), /caparaz[oó]n(?:es)?/i);
    assert.match(await page.locator('.duo-row[data-id="Primero"] [data-player-rank="player1"]').textContent(), /Gold III\s*\(0 LP\)/);
    assert.match(await page.locator('.duo-row[data-id="Primero"] [data-player-rank="player2"]').textContent(), /Emerald IV\s*\(55 LP\)/);
    assert.equal((await page.locator('.duo-row[data-id="Segundo"] [data-player-rank="player2"]').textContent()).trim(), 'Pendiente');
    assert.equal((await page.locator('.duo-row[data-id="Tercero"] [data-player-rank="player2"]').textContent()).trim(), 'Sin clasificar');
    assert.equal(await page.locator('.main-leaderboard-table .net-lp-label').count(), 0);
    const members = page.locator('.duo-row[data-id="Primero"] .participant-cell');
    assert.deepEqual(await members.locator('.participant-name').allTextContents(), ['Luis','Pepe']);
    assert.equal(await members.nth(0).locator('.twitch-link').getAttribute('href'), 'https://www.twitch.tv/luis_stream');
    assert.equal(await members.nth(0).locator('.is-live').count(), 0);
    assert.equal(await members.nth(1).locator('.twitch-link.is-live').count(), 1);
    assert.match(await members.nth(1).locator('.twitch-link').textContent(), /EN DIRECTO/);
    assert.equal(await page.locator('.duo-row[data-id="Segundo"] .participant-cell').nth(0).locator('.twitch-link.is-live').count(), 1);
    assert.equal(await page.locator('.duo-row[data-id="Segundo"] .participant-cell').nth(1).locator('.twitch-link').count(), 0);
    assert.equal(await page.locator('.duo-name-cell .twitch-link').count(), 0);

    assert.equal(await page.locator('#duo-insights-Primero > td').getAttribute('colspan'), '8');
    for (const width of [1440, 375]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.locator('.duo-row[data-id="Primero"] [data-player-rank="player1"]').isVisible(), true);
      assert.equal(await page.locator('.duo-row[data-id="Primero"] [data-player-rank="player2"]').isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.setViewportSize({width: 1440, height: 900});
    assert.match(await page.evaluate(() => renderPlayerRank({player2: {name: 'Otro', rank: {tier: 'Master', division: 'I', lp: 123}}}, 'player2')), /Master/);
    assert.doesNotMatch(await page.evaluate(() => renderPlayerRank({player2: {name: 'Otro', rank: {tier: 'Master', division: 'I', lp: 123}}}, 'player2')), /Master I/);

    await page.locator('.duo-row[data-id="Primero"]').click();
    const chart = page.locator('#duo-insights-Primero .elo-chart');
    assert.deepEqual(await chart.locator('svg > text').evaluateAll(elements => elements.map(el => el.textContent).filter(text => /^\d{2}-\d{2}$/.test(text))), ['01-09', '02-09', '03-09', '04-09']);
    assert.equal(await chart.locator('.elo-line').count(), 2);
    assert.equal(await chart.locator('[data-elo-player="player1"] .elo-point').count(), 4);
    assert.equal(await chart.locator('[data-elo-player="player2"] .elo-point').count(), 3);
    assert.match(await chart.locator('.elo-chart-legend').textContent(), /Jugador 1#EUW.*Jugador 2#EUW/);
    assert.equal(await chart.locator('.elo-series-player1 .elo-line').evaluate(el => getComputedStyle(el).stroke), 'rgb(255, 219, 87)');
    assert.equal(await chart.locator('.elo-series-player2 .elo-line').evaluate(el => getComputedStyle(el).stroke), 'rgb(0, 229, 155)');
    assert.equal(await chart.locator('[data-elo-player="player1"] .elo-point').nth(1).getAttribute('cx'), await chart.locator('[data-elo-player="player2"] .elo-point').first().getAttribute('cx'), 'same dates must share the same x-axis');
    await page.locator('#duo-insights-Primero .elo-point').first().focus();
    assert.match(await page.locator('#duo-insights-Primero .elo-chart-detail').textContent(), /10W/);
    await chart.locator('[data-elo-player="player2"] .elo-point').first().focus();
    assert.match(await chart.locator('.elo-chart-detail').textContent(), /Jugador 2#EUW · 02-09 · Platinum.*20W/);
    assert.equal(await page.evaluate(() => {
      const holder = document.createElement('div');
      holder.innerHTML = renderEloChart({teamName:'Test',player1:{name:'A',eloHistory:[]},player2:{name:'B',eloHistory:[{date:'2026-09-02',totalLp:1700,tier:'Platinum',lp:0}]}});
      return holder.querySelectorAll('.elo-point').length === 1 && holder.textContent.includes('Primer registro') && holder.textContent.includes('Pendiente de rango') && !holder.textContent.includes('undefined');
    }), true, 'one observed point must not invent a historical curve');
    if (process.env.ELO_SCREENSHOT) await chart.screenshot({path: process.env.ELO_SCREENSHOT});
    const cards = page.locator('#duo-insights-Primero .player-insight-card');
    assert.deepEqual(await cards.locator('h3').allTextContents(), ['Jugador 1#EUW','Jugador 2#EUW']);
    assert.deepEqual(await cards.nth(0).locator('.insight-metrics strong').allTextContents(), ['5.00','Mid','Wukong']);
    assert.deepEqual(await cards.nth(1).locator('.insight-metrics strong').allTextContents(), ['15.00','Top','Lee Sin']);
    assert.equal(await cards.locator('.opgg-profile-link').count(),2);
    assert.equal(await cards.nth(0).locator('.opgg-profile-link').getAttribute('href'),'https://www.op.gg/lol/summoners/euw/Uno-EUW');
    assert.equal(await cards.nth(0).locator('.opgg-profile-link').getAttribute('target'),'_blank');
    assert.equal(await cards.nth(0).locator('.opgg-profile-link').getAttribute('rel'),'noopener noreferrer');
    const popupReady = page.waitForEvent('popup');
    await cards.nth(0).locator('.opgg-profile-link').click();
    const opggPopup = await popupReady;
    assert.equal(await opggPopup.opener(),page);
    assert.equal(await opggPopup.evaluate(() => window.opener === null),true);
    await opggPopup.close();
    assert.equal(await page.locator('#duo-insights-Primero').isVisible(),true);
    assert.equal(await page.evaluate(() => {
      const holder=document.createElement('div'); holder.style.width='260px';
      holder.innerHTML=renderPlayerInsightCard({name:'UnNombreDeInvocadorMuyLargo',tag:'EUW',opggUrl:'https://op.gg/lol/summoners/euw/Test-EUW'},null);
      document.body.append(holder);
      const link=holder.querySelector('.opgg-profile-link').getBoundingClientRect();
      const card=holder.querySelector('.player-insight-card').getBoundingClientRect();
      const fits=link.right<=card.right && link.left>=card.left;
      holder.remove();return fits;
    }),true,'OP.GG button must stay inside a narrow player card');
    for (const value of ['', 'javascript:alert(1)', 'https://op.gg.evil.com/test', 'https://user@op.gg/test']) {
      assert.doesNotMatch(await page.evaluate(url => renderPlayerInsightCard({name:'Test',opggUrl:url},null),value),/opgg-profile-link/);
    }
    assert.match(await page.evaluate(() => renderPlayerInsightCard({name:'NoStats',mainRole:'UTILITY'}, null)), /Sin datos/);
    assert.match(await page.evaluate(() => renderPlayerInsightCard({name:'AutoRole',mainRole:'UTILITY'}, {mostPlayedPosition:{position:'MIDDLE',games:5}})), /<strong>Mid<\/strong>/);
    assert.match(await page.evaluate(() => renderPlayerInsightCard({name:'Pending',mainRole:'UTILITY'}, null)), /Pendiente de partidas/);
    const unsafeProfile = await page.evaluate(() => renderParticipantCell({player1:{name:'safe',displayName:'<img src=x onerror=alert(1)>',twitchUrl:'javascript:alert(1)'}}, 'player1'));
    assert.doesNotMatch(unsafeProfile, /<img|javascript:/);
    if (process.env.PARTICIPANT_SCREENSHOT) await page.locator('.main-leaderboard-table').screenshot({path: process.env.PARTICIPANT_SCREENSHOT});

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
      return ranks.map(rank => ({...rank, player1:{name:'P1',rank},player2:{name:'P2',rank}})).sort(compareCompetitionRank).map(x => x.id).join(',');
    }), 'challenger,grandmaster,master,gold3,gold4,iron,unranked');
    assert.deepEqual(await page.evaluate(() => {
      const rank = (tier, lp=0) => ({tier,division:'IV',lp});
      const a = {id:'A',tier:'Iron',player1:{name:'P1',rank:rank('Gold')},player2:{name:'P2',rank:rank('Diamond')}};
      const b = {id:'B',tier:'Challenger',player1:{name:'Q1',rank:rank('Platinum')},player2:{name:'Q2',rank:rank('Platinum')}};
      const order = [b,a].sort(compareCompetitionRank).map(d=>d.id);
      for (const key of ['player1','player2']) {
        a[key].accounts = [{id:'main',name:'Main',rank:rank('Challenger',900)}, {id:'alt',name:'Alt',rank:rank('Silver',51)}];
        a[key].eloAccountId = 'alt';
      }
      const selected = competitionAverageRank(a).totalLp;
      a.player2.accounts[1].rank = null;
      const pending = competitionAverageRank(a).ready;
      return {order,selected,pending,master:competitionRankPoints({tier:'Grandmaster',division:'I',lp:500}),
        half:competitionAverageRank({player1:{name:'P',rank:rank('Gold',1)},player2:{name:'Q',rank:rank('Gold')}}).totalLp};
    }), {order:['A','B'],selected:851,pending:false,master:3300,half:1200.5});
    assert.equal(await page.locator('.duo-average-elo').count(),0,'technical ELO points must remain internal');
    assert.doesNotMatch(await page.locator('#leaderboard-tbody').textContent(), /ELO medio:|\d[\d.,\s]* pts/);
    assert.equal(await page.evaluate(() => competitionAverageRank(currentDuos.find(d=>d.id==='Primero')).totalLp),1677.5,'hidden mean still drives ranking');
    await page.selectOption('#tier-filter','PLATINUM');
    assert.equal(await page.locator('.duo-row').count(),1,'tier filter follows average, not player one');
    assert.equal(await page.locator('.duo-row').first().getAttribute('data-id'),'Primero');
    await page.selectOption('#tier-filter','UNRANKED');
    assert.equal(await page.locator('.duo-row').count(),2);
    assert.deepEqual(await page.locator('.duo-row .rank-position-number').allTextContents(),['—','—']);
    await page.selectOption('#tier-filter','ALL');

    assert.equal(await page.locator('#rules, #trophies, #shell-rewards, #roulette-rules').count(), 0);
    await page.waitForFunction(() => document.querySelector('#recent-attacks-tbody').textContent.includes('Sin Flash'));
    assert.equal(await page.locator('#recent-attacks-tbody tr').count(), 1);
    assert.match(await page.locator('#recent-attacks-tbody .penalty-assignment').textContent(), /Debe cumplirlo: Pepe · Jugador 2#EUW/);

    assert.doesNotMatch(await page.locator('#recent-attacks-tbody').textContent(), /Lanzamiento oculto|Corrección oculta/);
    await page.locator('.duo-row[data-id="Primero"] .duo-expand-button').click();
    await page.locator('#duo-insights-Primero [data-history-id="Primero"]').click();
    await page.waitForSelector('.history-navigation');
    assert.deepEqual(historyOffsets, [0]);
    await page.getByRole('button', {name:'Siguiente', exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#modal-content').textContent.includes('desde la 31'));
    assert.deepEqual(historyOffsets, [0,30]);
    await page.locator('#modal-close').click();
    failReads = true;
    await page.evaluate(() => triggerManualSync());
    assert.equal(await page.locator('#leaderboard-tbody .duo-row').count(), 3);
    assert.equal(await page.locator('#connection-status').count(), 0, 'technical connection diagnostics must not exist on public pages');
    assert.equal(syncCount, 0, 'public refresh must not start Riot');
    failReads = false;
    await page.getByRole('link', {name:'Torneo', exact:true}).click();
    await page.waitForURL('**/torneo.html');
    await page.waitForSelector('#roulette-rules-list article');
    assert.equal(await page.locator('#trophies-grid').count(),0);
    await page.getByRole('link', {name:'Premios', exact:true}).click();
    await page.waitForURL('**/premios.html');
    await page.waitForSelector('.trophy-card');
    assert.equal(await page.locator('#connection-status').count(), 0);
    assert.equal(await page.locator('.trophy-card').count(), 7);
    assert.match(await page.locator('#trophies-status').textContent(), /provisional/);
    assert.match(await page.locator('#trophies-note').textContent(), /Solo cuentan las partidas jugadas en ese rol/);
    assert.match(await page.locator('.trophy-card').nth(5).textContent(), /Sin participantes/);
    await page.getByRole('link', {name:'Torneo', exact:true}).click();
    await page.waitForSelector('#roulette-rules-list article');
    assert.equal(await page.locator('#shell-rewards-body tr').count(), 5);
    assert.match(await page.locator('#shell-rewards-limits').textContent(), /5 pepazos.*2 obtenidos/);
    assert.doesNotMatch(await page.locator('body').innerText(), /caparaz[oó]n(?:es)?/i);
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
    // Opening the PIN screen must never trap visitors; each exit navigates away.
    for (const width of [1280,390]) {
      await page.setViewportSize({width,height:844});
      for (const exit of ['#admin-access-back','#admin-access-close']) {
        await page.goto('http://pepes.test/admin.html');
        await page.waitForSelector('#admin-pin-overlay.active');
        await page.locator(exit).click();
        await page.waitForURL('**/index.html');
      }
      await page.goto('http://pepes.test/admin.html');
      await page.waitForSelector('#admin-pin-overlay.active');
      await page.keyboard.press('Escape');
      await page.waitForURL('**/index.html');
    }
    await page.goto('http://pepes.test/admin.html');
    await page.locator('#admin-pin-input').fill('wrong');
    await page.locator('#admin-pin-form button[type="submit"]').click();
    await page.waitForFunction(()=>document.getElementById('pin-error-msg').style.display==='block');
    assert.equal(await page.locator('#admin-pin-overlay').isVisible(),true);
    assert.equal(await page.locator('#admin-diagnostics').isVisible(),false);
    await page.locator('#admin-access-back').click();
    await page.waitForURL('**/index.html');
    await page.setViewportSize({width:1280,height:720});
    await page.goto('http://pepes.test/admin.html');
    assert.equal(await page.locator('#admin-diagnostics').isVisible(), false);
    await page.locator('#admin-pin-input').fill('9999');
    await page.locator('#admin-pin-form button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('admin-pin-overlay').style.display === 'none');
    await page.locator('#btn-test-discord-admin').click();
    await page.waitForFunction(() => document.getElementById('toast-notification')?.textContent.includes('Mensaje de prueba enviado'));
    assert.deepEqual(discordTestRequests, [{authPin:'9999'}]);


    await page.evaluate(() => DataStore.refreshSyncStatus());
    assert.equal(await page.locator('#admin-diagnostics').isVisible(), true);
    assert.match(await page.locator('#connection-status').textContent(), /Riot: última llamada API OK 4\/10\/2026, 16:44:00 \(Madrid\)/);
    await page.evaluate(() => {
      latestSyncStatus.discord = {configured:true, lastSentAt:'2026-10-05T10:00:00+00:00', error:'Discord respondió HTTP 429.'};
      renderConnectionStatus();
    });
    assert.match(await page.locator('#connection-status').textContent(), /Discord: último aviso enviado 5\/10\/2026, 12:00:00 \(Madrid\)/);
    assert.match(await page.locator('#connection-status').textContent(), /Discord: Discord respondió HTTP 429/);
    await page.evaluate(() => { latestSyncStatus.riot.lastApiSuccessAt = null; renderConnectionStatus(); });
    assert.match(await page.locator('#connection-status').textContent(), /Riot: todavía no hay llamadas a la API confirmadas/);
    assert.doesNotMatch(await page.locator('#connection-status').textContent(), /Riot: última sincronización correcta/);
    await page.evaluate(() => DataStore.refreshSyncStatus());
    assert.match(await page.locator('#connection-status').textContent(), /2 partidas pendientes de completar/);
    assert.match(await page.locator('#connection-status').textContent(), /Twitch: Fallo técnico/);
    assert.equal(await page.locator('#admin-data-diagnostics tbody tr').count(), 3);
    assert.match(await page.locator('#admin-data-diagnostics tbody tr').first().textContent(), /Segundo\s*1\s*2\s*3/);
    assert.match(await page.locator('#admin-penalties-list .penalty-assignment').textContent(), /Pepe · Jugador 2#EUW/);
    await page.evaluate(() => {
      window.__savedAdminDuos = adminDuos;
      adminDuos = [{teamName:'Prueba', activeDebuffs:[{id:'retired', status:'CANCELLED', retiredPenalty:true, resolved:false, penalty:{name:'Botas'}}]}];
      renderAdminPenalties();
    });
    assert.equal(await page.locator('#admin-penalties-list .admin-penalty-status').textContent(), 'Retirado');
    assert.equal(await page.locator('#admin-penalties-list [data-penalty-action]').count(), 0);
    await page.evaluate(() => { adminDuos = window.__savedAdminDuos; renderAdminPenalties(); });
    const escapedAssignment = await page.evaluate(() => penaltyAssignmentText({scope:'ONE',requirements:{assignedPlayer:'player1',assignedAccount:{displayName:'<img>',name:'RiotName',tag:'EUW'}}}));
    assert.match(escapedAssignment, /<img>/); // Renderers must escape this text, while roulette uses textContent.
    assert.match(await page.evaluate(() => penaltyAssignmentText({scope:'ONE',requirements:{}})), /castigo anterior/);
    assert.match(await page.evaluate(() => penaltyAssignmentText({scope:'BOTH'})), /ambos/);
    const flashInstance = {scope:'ONE', penalty:{baseId:'swap_flash'}, requirements:{assignedPlayer:'player1', assignedAccount:{displayName:'Ana'}, flashBaselines:{player1:{slot:1}}}};
    assert.match(await page.evaluate(instance => penaltyAssignmentText(instance), flashInstance), /Ana.*Flash en F/);
    flashInstance.requirements.flashBaselines.player1.slot = 2;
    assert.match(await page.evaluate(instance => penaltyAssignmentText(instance), flashInstance), /Flash en D/);
    flashInstance.scope = 'BOTH';
    assert.match(await page.evaluate(instance => penaltyAssignmentText(instance), flashInstance), /ambos.*Flash en D.*Referencia pendiente/);
    flashInstance.scope = 'ONE';
    flashInstance.requirements.flashBaselines = {};
    assert.match(await page.evaluate(instance => penaltyAssignmentText(instance), flashInstance), /Referencia pendiente/);
    assert.equal(await page.locator('#p1-display-name-Primero').inputValue(), 'Luis');
    assert.equal(await page.locator('#p2-twitch-url-Primero').inputValue(), 'https://www.twitch.tv/pepe_stream');
    assert.equal(await page.locator('#p1-opgg-url-Primero').inputValue(),'https://www.op.gg/lol/summoners/euw/Uno-EUW');
    const beforeInvalidOpgg = profileWrites.length;
    await page.locator('#p1-opgg-url-Primero').fill('https://example.com/no');
    await page.locator('[data-team-action="profiles"][data-team-id="Primero"]').click();
    assert.equal(profileWrites.length,beforeInvalidOpgg);
    await page.locator('#p1-opgg-url-Primero').fill('https://op.gg/lol/summoners/euw/Editado-EUW');
    await page.locator('#p2-opgg-url-Primero').fill('');
    await page.locator('#p1-display-name-Primero').fill('Luis editado');
    await page.locator('#p2-display-name-Primero').fill('Pepe editado');
    await page.locator('#p2-twitch-url-Primero').fill('https://twitch.tv/new_pepe');
    await page.locator('[data-team-action="profiles"][data-team-id="Primero"]').click();
    await page.waitForFunction(() => document.getElementById('p1-display-name-Primero').value === 'Luis editado');
    assert.deepEqual(profileWrites.at(-1), {id:'Primero',player1:{displayName:'Luis editado',twitchUrl:'https://www.twitch.tv/luis_stream',opggUrl:'https://op.gg/lol/summoners/euw/Editado-EUW',accounts:[{id:'',name:'Jugador 1',tag:'EUW'}],eloAccountId:''},player2:{displayName:'Pepe editado',twitchUrl:'https://www.twitch.tv/new_pepe',opggUrl:'',accounts:[{id:'',name:'Jugador 2',tag:'EUW'}],eloAccountId:''}});
    const sources = page.locator('[data-player-accounts="p1-Primero"]');
    assert.equal(await sources.locator('input[type="radio"]:checked').count(),1);
    await sources.locator('[data-add-account]').click();
    const alternate = sources.locator('.admin-account-row').last();
    await alternate.locator('[data-account-name]').fill('Cuenta alternativa');
    await alternate.locator('[data-account-tag]').fill('ALT');
    await alternate.locator('input[type="radio"]').check();
    await page.locator('[data-team-action="profiles"][data-team-id="Primero"]').click();
    await page.waitForFunction(() => adminDuos.find(d => d.id === 'Primero').player1.accounts.length === 2);
    assert.equal(profileWrites.at(-1).player1.accounts[1].name,'Cuenta alternativa');
    assert.equal(profileWrites.at(-1).player1.eloAccountId,profileWrites.at(-1).player1.accounts[1].id);
    assert.equal(await sources.locator('input[type="radio"]:checked').count(),1);
    assert.equal(await sources.locator('[data-account-name]').last().inputValue(),'Cuenta alternativa');
    await page.setViewportSize({width:390,height:844});
    await sources.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(__dirname,'preview','multi-accounts-mobile.png')});
    assert.equal(await sources.evaluate(el => el.scrollWidth <= el.clientWidth + 1),true);
    await page.setViewportSize({width:1440,height:1000});
    await sources.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(__dirname,'preview','multi-accounts-desktop.png')});
    await page.locator('#new-team-name').fill('Nuevo equipo');
    await page.locator('#new-p1-display-name').fill('Uno');
    await page.locator('#new-p2-display-name').fill('Dos');
    await page.locator('#new-p1-twitch-url').fill('https://twitch.tv/new_one');
    await page.locator('#new-p2-twitch-url').fill('https://twitch.tv/new_two');
    await page.locator('#new-p1-opgg-url').fill('https://op.gg/lol/summoners/euw/Nuevo-EUW');
    await page.locator('#new-p1').fill('RiotUno#EUW');
    await page.locator('#new-p2').fill('RiotDos#ZZZ');
    assert.equal(await page.locator('#new-p1-role, #new-p2-role, [data-team-action="roles"], select[id^="p1-role-"], select[id^="p2-role-"]').count(),0);
    assert.ok(await page.locator('[data-auto-role]').count() > 0,'admin displays read-only derived positions');
    await page.locator('#add-duo-form button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('new-team-name').value === '');
    assert.equal(profileWrites.at(-1).player1.displayName, 'Uno');
    assert.equal(profileWrites.at(-1).player2.twitchUrl, 'https://www.twitch.tv/new_two');
    assert.equal(profileWrites.at(-1).player1.opggUrl,'https://op.gg/lol/summoners/euw/Nuevo-EUW');
    assert.equal(profileWrites.at(-1).player2.opggUrl,'');
    assert.equal(profileWrites.at(-1).player2.name, 'RiotDos');
    assert.equal(profileWrites.at(-1).player2.tag, 'ZZZ');
    assert.equal('mainRole' in profileWrites.at(-1).player1,false,'creating a team never submits a manual role');
    if (process.env.ADMIN_PARTICIPANT_SCREENSHOT) await page.locator('#admin-duos-list').screenshot({path: process.env.ADMIN_PARTICIPANT_SCREENSHOT});
    await page.locator('#btn-sync-matches-admin').click();
    await page.waitForFunction(() => document.getElementById('toast-notification')?.textContent.includes('iniciada'));
    assert.equal(syncCount, 1);
    failWrites = true;
    const failed = await page.evaluate(() => DataStore.saveDuo({id:'fake'}, '9999'));
    assert.equal(failed.success, false);
    assert.match(await page.locator('#connection-status').textContent(), /Conexión interrumpida/);
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
    assert.match(await page.locator('#player-shells-tab').textContent(), /Pepazos/);
    assert.match(await page.locator('#player-dashboard-section').textContent(), /Inventario de Pepazos/);
    assert.doesNotMatch(await page.locator('body').innerText(), /caparaz[oó]n(?:es)?/i);
    await page.evaluate(() => {
      window.__savedDebuffs = activeDuo.activeDebuffs;
      activeDuo.activeDebuffs = [{status:'CANCELLED', resolved:false, penalty:{name:'Botas'}, retirementReason:'Castigo retirado'}];
      renderActiveDebuffs();
    });
    await page.locator('#player-penalties-tab').click();
    await page.locator('[data-player-penalty-view=history]').click();
    assert.equal(await page.locator('#active-debuffs-list .penalty-status-retired').textContent(), ' Retirado');
    assert.equal(await page.locator('#active-debuffs-list .penalty-status-active, #active-debuffs-list .penalty-status-completed').count(), 0);
    await page.evaluate(() => { activeDuo.activeDebuffs = window.__savedDebuffs; renderActiveDebuffs(); });
    await page.locator('[data-player-penalty-view=pending]').click();
    await page.locator('#player-shells-tab').click();
    assert.equal(await page.locator('#connection-status').count(), 0);
    await page.waitForSelector('#personal-alert-bar:not([hidden])');
    assert.match(await page.locator('#personal-alert-bar').textContent(), /Segundo/);
    await page.waitForFunction(() => window.__notificationStreams.length > 0);
    await page.locator('#toggle-shell-sound').click();
    await page.waitForFunction(() => document.getElementById('toggle-shell-sound').getAttribute('aria-pressed') === 'true');
    const notification = {team: {id: 'Segundo', name: 'Segundo'}, attacks: [{id: 'alarm-1', attackerName: 'Rival'}]};
    await page.evaluate(value => window.__notify(value), notification);
    await page.waitForFunction(() => window.__alarmStarts === 1);
    assert.equal(await page.evaluate(() => window.__alarmGains.at(-1)), 2.25, 'shell warning uses the increased gain before the limiter');
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
    await page.evaluate(() => {activeDuo.pendingShellAttacks = [{id: "attack'1", attackerName: 'Rival', launchedAt: '2026-09-05', returnedFromAttackId:'original-attack'}]; renderDashboardData();});
    assert.match(await page.locator('#pending-shells-list').textContent(), /Pepazo devuelto por #Rival/);
    await page.locator('[data-spin-id]').click();
    assert.equal(spins[0].attackId, "attack'1");
    assert.equal(spins[0].sessionToken, 'fake');
    await page.locator('#personal-alert-bar').getByRole('button', {name: 'Cerrar sesión', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#personal-alert-bar').hidden);
    assert.equal(await page.locator('#personal-alert-bar').isVisible(), false);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('pepes_player_token')), null);
    assert.deepEqual(errors, []);
    console.log('Browser regressions passed: ranking, history, roulette rules, offline state, personal alerts, audio, mute, deduplication, reconnect and logout.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
