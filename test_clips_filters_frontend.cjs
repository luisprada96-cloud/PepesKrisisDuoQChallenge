// Search/team filters compose with pagination, archives and anonymous seen marks.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const week = '2026-10-26', archive = '2026-10-15';
    const teams = [{id: 'a', name: 'LosÉLOgidos'}, {id: 'b', name: 'Marx&Mises'}, {id: 'empty', name: 'Sin clips'}];
    const post = (id, title, teamId, team, index) => ({id, title, teamId, team, scene: 1, initials: 'CL',
      createdAt: 1800000000 - index, votes: 100 - index, liked: false,
      slug: `Test${id}`, url: `https://clips.twitch.tv/Test${id}`});
    let clips = [
      ...Array.from({length: 18}, (_, i) => post(`a${i}`, i === 0 ? '¡Qué jugadón de Ahri!' : `Jugada A ${i}`, 'a', teams[0].name, i)),
      ...Array.from({length: 16}, (_, i) => post(`b${i}`, i === 0 ? 'Un dragón y un robo' : `Jugada B ${i}`, 'b', teams[1].name, i + 18)),
      post('old', 'El equipo antiguo', 'deleted-team', 'Equipo anterior', 34),
      post('community', 'La comunidad comparte', undefined, 'Comunidad', 35),
      post('legacy-a', 'Pentakill de Ahri', undefined, 'loselogidos', 36)
    ];
    const archiveClips = [post('archived', 'Ahri de la primera semana', 'deleted-team', 'Equipo anterior', 0)];
    const errors = [], writes = [];
    let reads = 0;
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname === '/api/clips') {
        reads++;
        if (request.method() !== 'GET') writes.push(request.postDataJSON());
        const selected = url.searchParams.get('week') || week;
        const result = {week: selected, currentWeek: week, archived: selected === archive,
          clips: selected === archive ? archiveClips : clips, teams, voting: null,
          weeks: [{week}, {week: archive, archived: true}], weeklyReward: {closed: selected === archive}};
        return route.fulfill({contentType: 'application/json', body: JSON.stringify(result)});
      }
      if (url.pathname.startsWith('/api/')) return route.fulfill({contentType: 'application/json', body: '{}'});
      const file = url.pathname.slice(1);
      if (!['clips.html', 'clips.css', 'clips.js', 'styles.css', 'navigation.js', 'data.js', 'alerts.js'].includes(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(__dirname, file))});
    });
    const page = await context.newPage();
    await page.goto('http://pepes.test/clips.html');
    await page.locator('.clip-post').first().waitFor();
    const ids = () => page.locator('.clip-post').evaluateAll(posts => posts.map(post => post.dataset.clipId));
    const team = page.locator('#clips-team-filter'), search = page.locator('#clips-search');
    const clear = page.locator('#clips-clear-filters');
    const pagination = page.locator('[data-clips-pagination]').first();
    assert.equal(await page.locator('[data-vote]').first().isDisabled(), true);
    assert.equal(await team.getAttribute('disabled'), null);
    assert.equal(await clear.isVisible(), false);
    assert.equal(await page.locator('#clips-count').innerText(), '37 clips');
    assert.equal(await team.locator('option').count(), 6, 'roster, archived team and community are selectable; legacy names join the matching team');
    await pagination.locator('[data-clips-page="next"]').click();
    assert.equal((await ids())[0], 'a15');
    await team.selectOption('id:a');
    assert.equal(await page.locator('#clips-count').innerText(), '19 de 37 clips');
    assert.match(await pagination.innerText(), /Página 1 de 2/);
    assert.equal((await ids())[0], 'a0');
    await pagination.locator('[data-clips-page="next"]').click();
    assert.deepEqual(await ids(), ['a15', 'a16', 'a17', 'legacy-a']);
    await search.fill('AHRI   LOSÉLOGIDOS');
    assert.deepEqual(await ids(), ['a0', 'legacy-a'], 'AND tokens match title and team without accents or case');
    assert.equal(await pagination.isVisible(), false);
    assert.equal(await page.locator('#clips-count').innerText(), '2 de 37 clips');
    await search.fill('dragón');
    assert.equal(await page.locator('.clip-post').count(), 0);
    assert.match(await page.locator('.clips-empty').innerText(), /No hay clips que coincidan/);
    await team.selectOption('id:b');
    assert.deepEqual(await ids(), ['b0']);
    await clear.click();
    assert.equal(await search.inputValue(), '');
    assert.equal(await team.inputValue(), '');
    assert.equal(await search.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('.clip-post').count(), 15);
    await team.selectOption('id:empty');
    assert.match(await page.locator('.clips-empty').innerText(), /No hay clips que coincidan/);
    assert.equal(await page.locator('#clips-count').innerText(), '0 de 37 clips');
    await team.selectOption('id:deleted-team');
    assert.deepEqual(await ids(), ['old']);
    await team.selectOption('name:comunidad');
    assert.deepEqual(await ids(), ['community']);
    await clear.click();
    await search.fill('<img src=x onerror=alert(1)>');
    assert.equal(await page.locator('#clips-feed img').count(), 0);
    assert.match(await page.locator('.clips-empty').innerText(), /No hay clips que coincidan/);
    await search.fill('  ');
    assert.equal(await page.locator('#clips-count').innerText(), '37 clips');
    await clear.click();

    // Filters and seen marks do not send mutations or require a team login.
    await team.selectOption('id:a');
    await search.fill('ahri');
    await page.locator('[data-seen="a0"]').click();
    assert.equal(await page.locator('[data-clip-id="a0"] .clip-seen-label').isVisible(), true);
    assert.equal(await page.locator('[data-clip-id="legacy-a"] .clip-seen-label').isVisible(), false);
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.deepEqual(await ids(), ['legacy-a']);
    assert.equal(await team.inputValue(), 'id:a');
    assert.equal(await search.inputValue(), 'ahri');
    await page.locator('[data-seen="legacy-a"]').click();
    assert.match(await page.locator('.clips-empty').innerText(), /No quedan clips sin ver con estos filtros/);
    assert.equal(await page.locator('#clips-count').innerText(), '0 no vistos · 2 de 37 clips');
    await page.locator('[data-clips-sort="recent"]').click();
    await page.locator('[data-seen="a0"]').click();
    assert.equal(await page.locator('[data-clip-id="a0"] .clip-seen-label').isVisible(), false);
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.deepEqual(await ids(), ['a0']);
    await page.locator('[data-clips-sort="votes"]').click();
    await page.locator('[data-play="a0"]').click();
    await page.evaluate(() => {window.__frame = document.querySelector('[data-clip-id="a0"] iframe');});
    await search.fill('jugadon');
    assert.equal(await page.evaluate(() => window.__frame === document.querySelector('[data-clip-id="a0"] iframe')), true, 'typing matching filters keeps the player alive');
    const beforeRead = reads;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(() => document.getElementById('clips-count').textContent === '1 de 37 clips');
    await page.waitForTimeout(100);
    assert.ok(reads > beforeRead);
    assert.equal(await team.inputValue(), 'id:a');
    assert.equal(await search.inputValue(), 'jugadon');
    assert.equal(await page.evaluate(() => window.__frame === document.querySelector('[data-clip-id="a0"] iframe')), true);

    // A newly opened tab inherits guest marks, not its search/team choices.
    const second = await context.newPage();
    await second.goto('http://pepes.test/clips.html');
    await second.locator('.clip-post').first().waitFor();
    await second.locator('#clips-search').fill('pentakill');
    assert.equal(await second.locator('[data-seen="legacy-a"]').getAttribute('aria-pressed'), 'true');
    await second.locator('[data-seen="legacy-a"]').click();
    await page.waitForFunction(() => JSON.parse(localStorage.getItem('pepes_clips_seen')).ids.length === 0);
    await second.close();
    await clear.click();
    await team.selectOption('id:deleted-team');
    await page.selectOption('#clips-week-select', archive);
    await page.locator('[data-clip-id="archived"]').waitFor();
    assert.equal(await team.inputValue(), 'id:deleted-team');
    assert.equal(await page.locator('#clips-publish').isDisabled(), true);
    await search.fill('AHRI');
    assert.deepEqual(await ids(), ['archived']);
    await page.locator('[data-seen="archived"]').click();
    await page.locator('[data-clips-sort="unseen"]').click();
    assert.match(await page.locator('.clips-empty').innerText(), /No quedan clips sin ver/);
    await page.selectOption('#clips-week-select', week);
    await page.waitForFunction(() => !document.getElementById('clips-week-select').disabled);
    assert.equal(await search.inputValue(), 'AHRI');
    assert.equal(await team.inputValue(), 'id:deleted-team');
    assert.match(await page.locator('.clips-empty').innerText(), /No hay clips que coincidan/);
    await clear.click();
    await page.locator('[data-clips-sort="votes"]').click();
    await page.locator('[data-seen="a0"]').click();
    await page.reload();
    await page.locator('.clip-post').first().waitFor();
    assert.equal(await page.locator('[data-clip-id="a0"] .clip-seen-label').isVisible(), true);
    assert.equal(await page.locator('#clips-team-filter').inputValue(), '');
    assert.equal(await page.locator('#clips-search').inputValue(), '');
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({width, height: 1000});
      await search.fill('ahri');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `no overflow at ${width}`);
      assert.equal(await clear.isVisible(), true);
    }
    if (process.env.CLIPS_FILTERS_SCREENSHOT) await page.screenshot({path: process.env.CLIPS_FILTERS_SCREENSHOT, fullPage: true});
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    console.log('PASS: combined filters/search, accents, old teams, empty states, pagination, archives, retained playback, anonymous seen persistence, cross-tab updates and five widths.');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
