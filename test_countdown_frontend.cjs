// Official tournament boundaries, DST and Madrid admin input; no live data writes.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  const start = Date.parse('2026-10-15T16:00:00Z');
  const end = Date.parse('2026-11-15T22:59:00Z');
  const config = {challengeTitle:'Prueba', startDate:'2026-10-15T18:00:00+02:00', endDate:'2026-11-15T23:59:00+01:00', prizePool:'Prueba'};
  try {
    for (const timezoneId of ['Europe/Madrid','America/Los_Angeles','Asia/Tokyo']) {
      const context = await browser.newContext({timezoneId});
      await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== 'http://pepes.test') return route.abort();
        if (url.pathname.startsWith('/api/')) {
          return route.fulfill({contentType:'application/json',body:JSON.stringify(url.pathname === '/api/config' ? config : [])});
        }
        const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (!['index.html','app.js','admin.html','admin.js','data.js','alerts.js','styles.css'].includes(file)) return route.fulfill({status:404,body:''});
        return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.clock.install({time:new Date(start - 1000)});
      await page.clock.pauseAt(new Date(start - 1000));
      await page.goto('http://pepes.test/');
      await page.waitForSelector('#countdown-timer[data-phase=upcoming]');
      assert.equal(await page.locator('#prize-pool-text, .hero-subtitle').count(), 0);
      assert.ok(await page.locator('#countdown-timer').evaluate(el => parseFloat(getComputedStyle(el).fontSize) > 17.6), 'countdown is larger on desktop');
      assert.equal(await page.locator('#countdown-label').textContent(), 'El torneo empieza en');
      assert.deepEqual(await page.locator('.countdown-unit').allTextContents(), ['0d','0h','0m','1s']);
      await page.clock.runFor(1000);
      assert.equal(await page.locator('#countdown-timer').getAttribute('data-phase'), 'active');
      assert.equal(await page.locator('#countdown-label').textContent(), 'El torneo acaba en:');
      assert.deepEqual(await page.locator('.countdown-unit').allTextContents(), ['31d','6h','59m','0s']);
      await page.setViewportSize({width:320,height:850});
      assert.equal(await page.locator('#countdown-timer').evaluate(el => el.scrollWidth <= el.clientWidth), true, 'enlarged timer still fits on mobile');
      const dates = await page.evaluate(() => ({
        start:tournamentDateTimestamp('2026-10-15T18:00'), end:tournamentDateTimestamp('2026-11-15T23:59'),
        startInput:tournamentDateInput(currentConfig.startDate), endInput:tournamentDateInput(currentConfig.endDate),
        invalid:Number.isNaN(tournamentDateTimestamp('bad-date')),
        nonexistent:Number.isNaN(tournamentDateTimestamp('2026-03-29T02:30'))
      }));
      assert.deepEqual(dates,{start,end,startInput:'2026-10-15T18:00',endInput:'2026-11-15T23:59',invalid:true,nonexistent:true});
      await page.clock.pauseAt(new Date(end - 1000));
      await page.clock.runFor(1000);
      assert.equal(await page.locator('#countdown-timer').getAttribute('data-phase'), 'finished');
      assert.match(await page.locator('#countdown-timer').textContent(), /DESAFÍO FINALIZADO/);
      assert.equal(await page.locator('#countdown-label').textContent(), 'Torneo finalizado');
      await page.evaluate(() => {currentConfig.startDate='bad-date'; updateCountdownTimer();});
      assert.equal(await page.locator('#countdown-timer').getAttribute('data-phase'), 'invalid');
      assert.doesNotMatch(await page.locator('#countdown-timer').textContent(), /NaN/);
      await page.goto('http://pepes.test/admin.html');
      await page.evaluate(value => {
        adminConfig = value;
        fillConfigForm();
        window.alert = () => {};
        DataStore.saveConfig = async saved => {
          window.__savedDates = {startDate:saved.startDate,endDate:saved.endDate};
          return {success:true, config:saved};
        };
      }, config);
      assert.equal(await page.locator('#cfg-start').inputValue(), '2026-10-15T18:00');
      assert.equal(await page.locator('#cfg-end').inputValue(), '2026-11-15T23:59');
      await page.evaluate(() => saveConfigForm());
      assert.deepEqual(await page.evaluate(() => window.__savedDates), {startDate:'2026-10-15T16:00:00.000Z',endDate:'2026-11-15T22:59:00.000Z'});
      assert.equal(await page.locator('#cfg-start').inputValue(), '2026-10-15T18:00');
      assert.equal(await page.locator('#cfg-end').inputValue(), '2026-11-15T23:59');
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log('Countdown passed: automatic start/end, October DST, Madrid/LA/Tokyo timezone independence, admin date conversion, invalid dates.');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
