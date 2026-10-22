// Uses the actual server catalog and migration, isolated from the real database.
const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const fixture = JSON.parse(execFileSync(path.join(__dirname, '.venv', 'Scripts', 'python.exe'), ['-c',
    "import json,server; from test_favorite_weight_transfer import old_weights; print(json.dumps(dict(penaltyCatalog=server.PENALTY_CATALOG,penaltyWeights=server.without_retired_weights(old_weights()))))"],
    {cwd: __dirname, env: {...process.env, PEPES_STORAGE: 'local'}, encoding: 'utf8'}));
  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    let saved = null;
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      if (url.pathname.startsWith('/api/')) {
        let result = {success: true};
        if (url.pathname === '/api/config') {
          if (request.method() === 'POST') {
            saved = request.postDataJSON().config.penaltyWeights;
            result = {success: true, config: {...fixture, penaltyWeights: saved}};
          } else result = fixture;
        } else if (url.pathname === '/api/admin/login') result = {...fixture, success: true, config: fixture, duos: []};
        else if (url.pathname === '/api/admin/pickem') result = {success: true, weeks: [], predictions: [], categories: []};
        else if (url.pathname === '/api/duos') result = [];
        else if (url.pathname === '/api/sync/status') result = {riot: {}, twitch: {}};
        return route.fulfill({contentType: 'application/json', body: JSON.stringify(result)});
      }
      const file = url.pathname.slice(1);
      if (!/^[a-z-]+\.(html|css|js)$/.test(file) || !fs.existsSync(path.join(__dirname, file))) return route.fulfill({status: 404, body: ''});
      return route.fulfill({contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(__dirname, file))});
    });
    await page.goto('http://pepes.test/torneo.html');
    await page.locator('#roulette-rules-list article').first().waitFor();
    assert.equal(await page.locator('#roulette-rules-list article').count(), 9);
    assert.doesNotMatch(await page.locator('#roulette-rules-list').innerText(), /favorito/i);
    for (const [scope, weight] of [['UNO', 22], ['AMBOS', 13]]) {
      const card = page.locator('#roulette-rules-list article').filter({hasText: `Campeón aleatorio · ${scope}`});
      assert.equal(await card.locator('.roulette-rule-chance').innerText(), `${weight}%`);
    }
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.locator('#roulette-rules-list').evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await page.goto('http://pepes.test/admin.html');
    await page.locator('#admin-pin-input').fill('9999');
    await page.locator('#admin-pin-form button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('admin-pin-overlay').style.display === 'none');
    assert.equal(await page.locator('[data-penalty-weight]').count(), 9);
    assert.equal(await page.locator('[data-penalty-weight="random_champion_one"]').inputValue(), '22');
    assert.equal(await page.locator('[data-penalty-weight="random_champion_both"]').inputValue(), '13');
    assert.doesNotMatch(await page.locator('#penalty-weights-grid').innerText(), /favorito/i);
    assert.equal(await page.locator('#penalty-weight-total').innerText(), '100%');
    assert.equal(await page.locator('#btn-save-penalty-weights').isEnabled(), true);
    await page.locator('#btn-save-penalty-weights').click();
    await page.waitForFunction(() => document.getElementById('penalty-weight-total').innerText === '100%');
    assert.deepEqual(saved, fixture.penaltyWeights);
    assert.deepEqual(errors, []);
    console.log('PASS: rules and admin display 22% / 13%, no favorite outcomes; 100% saved.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
