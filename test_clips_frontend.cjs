// Browser regressions for weekly clip pagination and browser-local watched marks.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 960}});
    let week = '2026-09-28';
    let weekClosed = false;
    let sessionExpired = false;
    const teams = [{id:'a', name:'Atacante'}, {id:'b', name:'Receptor'}];
    let clips = Array.from({length: 31}, (_, i) => ({id: `clip-${String(i + 1).padStart(2, '0')}`, title: `Jugada ${i + 1}`, slug: '', url: '',
      team: 'Comunidad', initials: 'CL', scene: i % 3 + 1, createdAt: 1800000000 - i * 60, votes: 31 - i, liked: false}));
    const writes = [];
    const errors = [];
    context.on('page', page => page.on('pageerror', failure => errors.push(failure.message)));
    await context.route('**/*', async route => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        if (req.method() === 'POST' && url.pathname.startsWith('/api/clips')) {
          writes.push({path: url.pathname, body: req.postDataJSON(), authorization:req.headers().authorization});
          if (url.pathname === '/api/clips/like') {
            const body = req.postDataJSON();
            const clip = clips.find(item => item.id === body.clipId);
            if (sessionExpired || req.headers().authorization !== 'Bearer test-team-session') return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:'Inicia sesión con tu equipo para votar.'})});
            if (clip.liked !== body.liked) clip.votes += body.liked ? 1 : -1;
            clip.liked = body.liked;
          } else if (url.pathname === '/api/clips') {
            const body = req.postDataJSON();
            clips.push({id: 'new-clip', title: body.title, slug: body.url.split('/').at(-1), url: body.url, createdAt: 1900000000, teamId:body.teamId, team:teams.find(team=>team.id===body.teamId).name, initials: 'CL', scene: 1, votes: 0, liked: false});
          }
        }
        const result = url.pathname === '/api/clips' || url.pathname === '/api/clips/like' ? {week, preview: true, clips, teams, voting: !sessionExpired && req.headers().authorization === 'Bearer test-team-session' ? {teamId:'a',teamName:'Atacante'} : null,
          weeklyReward:{closed:weekClosed,award:weekClosed ? {status:'AWARDED', teamName:'Atacante', shells:3, title:'Ganador', votes:7} : null}} : {};
        return route.fulfill({contentType: 'application/json', body: JSON.stringify(result)});
      }
      const file = url.pathname.slice(1);
      if (!['clips.html', 'clips.css', 'clips.js', 'styles.css', 'data.js', 'alerts.js'].includes(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(__dirname, file))});
    });
    const page = await context.newPage();
    await page.goto('http://pepes.test/clips.html');
    await page.locator('.clip-post').first().waitFor();
    const top = page.locator('[data-clips-pagination]').first();
    const next = top.locator('[data-clips-page="next"]');
    const previous = top.locator('[data-clips-page="previous"]');
    const ids = () => page.locator('.clip-post').evaluateAll(posts => posts.map(post => post.dataset.clipId));
    assert.equal(await page.locator('[data-vote]').first().isDisabled(), true, 'guests cannot vote');
    assert.equal(await page.locator('#clips-login').isVisible(), true);
    assert.equal(await page.locator('.clip-post').count(), 15);
    assert.match(await top.textContent(), /Página 1 de 3 · 1–15 de 31/);
    assert.equal(await previous.isDisabled(), true);
    await next.click();
    assert.equal(await page.locator('.clip-post').count(), 15);
    assert.equal((await ids())[0], 'clip-16');
    await next.click();
    assert.deepEqual(await ids(), ['clip-31']);
    assert.equal(await next.isDisabled(), true);
    assert.match(await top.textContent(), /Página 3 de 3 · 31–31 de 31/);
    await previous.click();
    await page.locator('[data-clips-sort="recent"]').click();
    assert.equal((await ids())[0], 'clip-01', 'switching filters starts at page one');
    await page.locator('[data-seen="clip-01"]').click();
    assert.equal(await page.locator('[data-seen="clip-01"]').getAttribute('aria-pressed'), 'true');
    assert.equal(writes.length, 0, 'watched status must stay local');
    assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('pepes_clips_seen')).ids), ['clip-01']);
    await page.reload();
    await page.locator('.clip-post').first().waitFor();
    assert.equal(await page.locator('[data-seen="clip-01"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.equal((await ids())[0], 'clip-02');
    assert.equal(await page.locator('.clip-post').count(), 15);
    assert.equal(await page.locator('[data-seen="clip-01"]').count(), 0);
    assert.match(await page.locator('#clips-count').textContent(), /30 no vistos/);
    await page.locator('[data-seen="clip-02"]').click();
    assert.equal((await ids())[0], 'clip-03');
    assert.equal(await page.locator('.clip-post').count(), 15, 'fill the page after marking a clip');
    await page.locator('[data-clips-sort="recent"]').click();
    await page.locator('[data-seen="clip-01"]').click();
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.equal((await ids())[0], 'clip-01', 'unmark returns the clip to pending');

    // Keep loaded video/post nodes when polling unchanged data.
    await page.locator('[data-play="clip-01"]').click();
    await page.evaluate(() => {window.__post = document.querySelector('[data-clip-id="clip-01"]');});
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(() => window.__post === document.querySelector('[data-clip-id="clip-01"]')), true);
    assert.equal(await page.locator('.clip-example-player').count(), 1);
    await context.addInitScript(() => { if (location.origin === 'http://pepes.test') sessionStorage.setItem('pepes_player_token','test-team-session'); });
    await page.evaluate(() => {sessionStorage.setItem('pepes_player_token','test-team-session');window.dispatchEvent(new Event('focus'));});
    await page.waitForFunction(() => !document.querySelector('[data-vote="clip-01"]').disabled);
    assert.match(await page.locator('#clips-voting-status').textContent(), /Atacante/);
    await page.locator('[data-vote="clip-01"]').click();
    await page.waitForFunction(() => document.querySelector('[data-vote="clip-01"]').getAttribute('aria-pressed') === 'true');
    assert.equal(writes.at(-1).path, '/api/clips/like');
    assert.deepEqual(writes.at(-1).body, {clipId: 'clip-01', liked: true, week});

    assert.equal(writes.at(-1).authorization, 'Bearer test-team-session');
    assert.equal(await page.locator('.clip-team-votes, [data-unvote]').count(), 0, 'no team counter or extra vote control');
    assert.doesNotMatch(await page.locator('main').innerText(), /[012]\/2/);
    await page.locator('[data-vote="clip-01"]').click();
    await page.waitForFunction(() => document.querySelector('[data-vote="clip-01"]').getAttribute('aria-pressed') === 'false');
    assert.deepEqual(writes.at(-1).body, {clipId:'clip-01', liked:false, week});
    await page.locator('[data-vote="clip-01"]').click();
    await page.waitForFunction(() => document.querySelector('[data-vote="clip-01"]').getAttribute('aria-pressed') === 'true');

    // Other tabs in this browser reflect local marks.
    const second = await context.newPage();
    await second.goto('http://pepes.test/clips.html');
    await second.locator('.clip-post').first().waitFor();
    assert.equal(await second.locator('[data-seen="clip-02"]').getAttribute('aria-pressed'), 'true');
    await second.locator('[data-seen="clip-03"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-seen="clip-03"]'));
    await second.close();

    // Shrinking the unseen list on the final page clamps to an existing page.
    await page.locator('[data-clips-sort="recent"]').click();
    await next.click();
    await next.click();
    await page.locator('[data-seen="clip-31"]').click();
    await page.locator('[data-clips-sort="unseen"]').click();
    await next.click();
    for (const id of await ids()) await page.locator(`[data-seen="${id}"]`).click();
    assert.match(await top.textContent(), /Página 1 de 1/);
    assert.equal(await top.isVisible(), false);
    while (await page.locator('[data-seen]').count()) await page.locator('[data-seen]').first().click();
    assert.match(await page.locator('.clips-empty').textContent(), /Estás al día/);
    assert.match(await page.locator('#clips-count').textContent(), /0 no vistos/);
    await page.locator('[data-clips-sort="recent"]').click();
    assert.equal(await page.locator('.clip-post').count(), 15, 'watched clips remain in the normal tabs');

    // Publishing from a later page returns to the newest clip on page one.
    await next.click();
    await page.locator('#clips-publish').click();
    await page.locator('#clip-url').fill('https://clips.twitch.tv/ExampleSlug');
    await page.locator('#clip-title').fill('Nuevo clip');
    await page.locator('#clip-team').selectOption('b');
    await page.locator('#clips-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.clip-post')?.dataset.clipId === 'new-clip');
    assert.equal(await page.locator('.clip-post').count(), 15);
    assert.match(await top.textContent(), /Página 1 de 3/);
    assert.equal(await page.locator('[data-clips-sort="recent"]').getAttribute('aria-pressed'), 'true');
    assert.doesNotMatch(await page.locator('main').innerText(), /ejemplo|vista previa/i, 'real clips must not show prototype labels');
    assert.equal(await page.locator('[data-clip-id="new-clip"] iframe').count(), 1);
    assert.equal(writes.find(write => write.path === '/api/clips').body.teamId, 'b');
    assert.equal(await page.locator('[data-clip-id="new-clip"] .clip-team').textContent(), 'Receptor');

    // Weekly rollover resets marks and pagination, even when an ID is reused.
    week = '2026-10-05';
    clips = [{...clips[0], createdAt: 1900000001}, {...clips[1], createdAt: 1900000000}];
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(() => document.querySelectorAll('.clip-post').length === 2);
    assert.equal(await page.locator('[data-seen="clip-01"]').getAttribute('aria-pressed'), 'false');
    assert.equal(await top.isVisible(), false);
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.deepEqual(await ids(), ['clip-01', 'clip-02']);
    for (const width of [1440, 375, 320]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `no overflow at ${width}`);
    }
    await page.setViewportSize({width: 1440, height: 960});
    if (process.env.CLIPS_SCREENSHOT) await page.screenshot({path: process.env.CLIPS_SCREENSHOT});
    // Close/reopen the page in the same browser profile retains marks.
    await page.locator('[data-seen="clip-01"]').click();
    await page.close();
    const reopened = await context.newPage();
    await reopened.goto('http://pepes.test/clips.html');
    await reopened.locator('.clip-post').first().waitFor();
    assert.equal(await reopened.locator('[data-seen="clip-01"]').getAttribute('aria-pressed'), 'true');
    // Storage disabled: still allow marking in this tab without pretending persistence.
    await reopened.evaluate(() => {Storage.prototype.setItem = () => {throw new Error('Storage disabled');};});
    await reopened.locator('[data-seen="clip-02"]').click();
    assert.equal(await reopened.locator('[data-seen="clip-02"]').getAttribute('aria-pressed'), 'true');
    assert.match(await reopened.locator('#clips-feedback').textContent(), /no permite guardarla/);
    // Votes may cross ranks or page boundaries without moving a watched card.
    clips = Array.from({length: 17}, (_, i) => ({id: `rank-${i + 1}`, title: `Ranking ${i + 1}`, slug: '',
      url: i === 1 ? 'https://clips.twitch.tv/StablePlayer' : '', team: 'Comunidad', initials: 'CL', scene: 1,
      createdAt: i === 1 ? 1800000020 : 1800000010 - i, votes: i === 0 ? 5 : i === 1 ? 4 : 1, liked: false}));
    const stable = await context.newPage();
    await stable.goto('http://pepes.test/clips.html');
    await stable.locator('.clip-post').first().waitFor();
    const stableIds = () => stable.locator('.clip-post').evaluateAll(posts => posts.map(post => post.dataset.clipId));
    const before = await stableIds();
    assert.equal(before[0], 'rank-1');
    await stable.locator('[data-play="rank-2"]').click();
    await stable.evaluate(() => {
      window.__post = document.querySelector('[data-clip-id="rank-2"]');
      window.__frame = window.__post.querySelector('iframe');
    });
    assert.equal(await stable.locator('[data-clip-id="rank-2"] iframe').count(), 1, 'a real URL must embed even when its slug is missing');
    assert.doesNotMatch(await stable.locator('main').innerText(), /ejemplo|vista previa/i);
    const voteButton = stable.locator('[data-vote="rank-2"]');
    await voteButton.scrollIntoViewIfNeeded();
    const beforeScroll = await stable.evaluate(() => scrollY);
    await voteButton.click();
    await stable.waitForFunction(() => document.querySelector('[data-vote="rank-2"]').getAttribute('aria-pressed') === 'true');
    assert.deepEqual(await stableIds(), before, 'a like crossing a rank must not move cards');
    assert.equal(await stable.locator('[data-clip-id="rank-2"] .clip-vote strong').textContent(), '5');
    assert.equal(await stable.evaluate(() => scrollY), beforeScroll, 'voting must not scroll the page');
    assert.equal(await stable.evaluate(() => window.__post === document.querySelector('[data-clip-id="rank-2"]') && window.__frame === window.__post.querySelector('iframe')), true, 'voting must preserve the playing iframe');
    await stable.reload();
    await stable.locator('.clip-post').first().waitFor();
    assert.equal((await stableIds())[0], 'rank-2', 'reload sorts using the updated vote counts');
    await stable.locator('[data-vote="rank-2"]').click();
    await stable.waitForFunction(() => document.querySelector('[data-vote="rank-2"]').getAttribute('aria-pressed') === 'false');
    assert.equal((await stableIds())[0], 'rank-2', 'removing a like also keeps the current order');
    await stable.locator('[data-clips-sort="recent"]').click();
    await stable.locator('[data-clips-sort="votes"]').click();
    assert.equal((await stableIds())[0], 'rank-1', 'choosing the ranking tab explicitly sorts again');

    const beforePoll = await stableIds();
    clips[16].votes = 50;
    clips.push({...clips[0], id: 'arrival', title: 'New arrival', createdAt: 1900000000, votes: 1000});
    await stable.waitForFunction(() => document.getElementById('clips-count').textContent === '18 clips', {timeout: 10000});
    assert.deepEqual(await stableIds(), beforePoll, 'automatic polling must not reorder or shift the first page');
    const stableNav = stable.locator('[data-clips-pagination]').first();
    await stableNav.locator('[data-clips-page="next"]').click();
    assert.deepEqual(await stableIds(), ['rank-16', 'rank-17', 'arrival'], 'page navigation preserves the loaded order and appends new clips');
    assert.equal(await stable.locator('[data-clip-id="rank-17"] .clip-vote strong').textContent(), '50', 'polling still updates other visitors votes');
    await stable.locator('[data-vote="rank-17"]').click();
    await stable.waitForFunction(() => document.querySelector('[data-vote="rank-17"]')?.getAttribute('aria-pressed') === 'true');
    assert.deepEqual(await stableIds(), ['rank-16', 'rank-17', 'arrival'], 'a vote on a later page must not send the clip to page one');
    assert.match(await stableNav.textContent(), /Página 2 de 2/);
    await stable.reload();
    await stable.locator('.clip-post').first().waitFor();
    assert.deepEqual((await stableIds()).slice(0, 2), ['arrival', 'rank-17'], 'refresh applies the current ranking');
    sessionExpired = true;
    await stable.locator('[data-vote="arrival"]').click();
    await stable.waitForFunction(() => document.getElementById('clips-login').hidden === false);
    assert.equal(await stable.locator('[data-vote]').first().isDisabled(), true);
    assert.match(await stable.locator('#clips-feedback').textContent(), /Inicia sesión/);
    const votesAfterExpiry = writes.length;
    await stable.locator('[data-seen="arrival"]').click();
    assert.equal(writes.length, votesAfterExpiry, 'watched marks still work after session expiry');
    weekClosed = true;
    await stable.evaluate(() => window.dispatchEvent(new Event('focus')));
    await stable.waitForFunction(() => document.getElementById('clips-publish').disabled);
    assert.match(await stable.locator('#clips-reward-status').textContent(), /Atacante.*\+3.*Ganador/);
    assert.equal(await stable.locator('[data-vote]').first().isDisabled(), true);
    const writeCount = writes.length;
    await stable.locator('[data-vote]').first().dispatchEvent('click');
    assert.equal(writes.length, writeCount, 'votes stay frozen after the award');
    assert.deepEqual(errors, []);
    console.log('Clips browser regressions passed: 15 per page, sorting, watched marks, persistence, unseen filter, cross-tab updates, shrinking pages, weekly reset, publishing, likes, retained players, mobile layout, storage failure and stable order while voting/polling.');
  } finally {await browser.close();}
})().catch(failure => {console.error(failure); process.exitCode = 1;});
