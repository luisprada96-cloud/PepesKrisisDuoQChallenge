// Browser regressions for the actual match-history component, using Riot-shaped data.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1024,height:950}});
    const errors = [];
    const staticCalls = [];
    page.on('pageerror',error=>errors.push(error.message));
    const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5fcAAAAASUVORK5CYII=','base64');
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.host === 'ddragon.leagueoflegends.com') {
        if(url.pathname.endsWith('.json')) {
          staticCalls.push(url.pathname);
          let result;
          if(url.pathname.endsWith('versions.json')) result=['16.19.1','16.18.1'];
          else if(url.pathname.endsWith('item.json')) result={data:{'3089':{name:'Sombrero mortal de Rabadon',image:{full:'3089.png'}},'3020':{name:'Botas de hechicero',image:{full:'3020.png'}}}};
          else result={data:{Flash:{key:'4',name:'Destello',image:{full:'SummonerFlash.png'}},Barrier:{key:'21',name:'Barrera',image:{full:'SummonerBarrier.png'}}}};
          return route.fulfill({contentType:'application/json',body:JSON.stringify(result)});
        }
        return route.fulfill({contentType:'image/png',body:image});
      }
      if(url.host !== 'history.test') return route.abort();
      if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:'<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/styles.css"></head><body><div id="modal-overlay" class="modal-overlay active"><div class="modal-card"><div class="modal-header">Historial de krisis</div><div class="modal-body"><div class="match-history-list" id="history"></div></div></div></div><script src="/match-history.js"></script></body></html>'});
      const name=url.pathname.slice(1);
      if(!['styles.css','match-history.js'].includes(name)) return route.abort();
      return route.fulfill({contentType:name.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(__dirname,name))});
    });
    await page.goto('http://history.test/');
    const player = {riotIdGameName:'UnluckyElOtro',riotIdTagline:'EUW',championName:'Lux',champLevel:17,position:'MIDDLE',kills:8,deaths:3,assists:11,teamKills:27,cs:237,goldEarned:14860,visionScore:19,summonerSpellIds:[4,21],itemIds:[3089,3020,0,0,0,0,3363]};
    const rich = {matchId:'EUW1_RICH',result:'WIN',date:'02/10/2026 18:42',durationSeconds:1884,gameVersion:'16.19.123.1',player1Stats:player,player2Stats:{...player,riotIdGameName:'Jeff Buckley',championName:'Zyra',champLevel:16,position:'UTILITY',kills:3,deaths:5,assists:16,cs:38,goldEarned:10120,visionScore:63}};
    const old = {matchId:'EUW1_OLD',result:'LOSS',duration:'28m 06s',date:'02/10/2026 17:55',championP1:'Ahri',kda1:'4/7/5',championP2:'Lux',kda2:'1/8/9'};
    const solo = {...rich,matchId:'EUW1_SOLO',gameVersion:'16.18.1.1',player2Stats:null,participantsChecked:{player2:true},championP2:'Bogus',kda2:'999/0/999'};
    const zeros = {...rich,matchId:'EUW1_ZERO',player1Stats:{...player,kills:0,deaths:0,assists:0,teamKills:0,cs:0,goldEarned:0,visionScore:0,itemIds:[0,0,0,0,0,0,0]}};
    const unsafe = {...rich,matchId:'EUW1_ESCAPE',player1Stats:{...player,riotIdGameName:'<img src=x onerror="window.bad=true">'}};
    await page.evaluate(({matches})=>MatchHistory.mount(document.getElementById('history'),{player1:{name:'Cuenta 1'},player2:{name:'Cuenta 2'}},matches),{matches:[rich,old,solo,zeros,unsafe]});
    const games = page.locator('.history-match');
    assert.equal(await games.count(),5);
    await page.waitForFunction(()=>document.querySelector('[data-dd-item="3089"]').getAttribute('aria-label')==='Sombrero mortal de Rabadon');
    assert.equal(await games.first().getAttribute('open'),'');
    assert.equal(await games.nth(1).getAttribute('open'),null);
    const content=await games.first().textContent();
    assert.match(content,/31:24/);
    assert.match(content,/6,33 KDA · 70% participación/);
    assert.match(content,/3,80 KDA · 70% participación/);
    assert.match(content,/237 CS/);
    assert.match(content,/7,5 por minuto/);
    assert.equal(await games.first().locator('.match-level').first().textContent(),'17');
    assert.equal(await games.first().locator('.match-items').first().locator('.empty').count(),4);
    const item=games.first().getByRole('button',{name:'Sombrero mortal de Rabadon',exact:true}).first();
    await item.hover();
    assert.equal(await item.locator('.match-item-tooltip').isVisible(),true);
    await item.focus();
    assert.equal(await item.locator('.match-item-tooltip').isVisible(),true);
    await games.nth(1).locator('summary').click();
    assert.match(await games.nth(1).textContent(),/Objetos no disponibles/);
    assert.match(await games.nth(1).textContent(),/— CS/);
    await games.nth(2).locator('summary').click();
    assert.match(await games.nth(2).textContent(),/No participó en esta partida/);
    assert.doesNotMatch(await games.nth(2).textContent(),/999\/0\/999|Bogus/);
    await page.waitForFunction(()=>document.querySelector('.history-match:nth-child(3) [data-dd-item="3089"] img').src.includes('16.18.1'));
    await games.nth(3).locator('summary').click();
    assert.match(await games.nth(3).textContent(),/Perfecto · — participación/);
    assert.match(await games.nth(3).textContent(),/0 CS/);
    assert.doesNotMatch(await games.nth(3).textContent(),/NaN|Infinity|undefined/);
    await games.nth(4).locator('summary').click();
    assert.equal(await games.nth(4).locator('.match-player-name').first().locator('img').count(),0);
    assert.match(await games.nth(4).locator('.match-player-name').first().textContent(),/<img src=x/);
    assert.equal(await page.evaluate(()=>window.bad),undefined);
    await games.first().locator('summary').click();
    await games.first().locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await games.first().getAttribute('open'),'');
    assert.equal(staticCalls.filter(p=>p.endsWith('versions.json')).length,1);
    assert.equal(staticCalls.filter(p=>p==='/cdn/16.19.1/data/es_ES/item.json').length,1);
    assert.equal(staticCalls.filter(p=>p==='/cdn/16.19.1/data/es_ES/summoner.json').length,1);
    for (const width of [1024,736,390,320]) {
      await page.setViewportSize({width,height:950});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Page overflow at ${width}`);
      assert.equal(await page.locator('#history').evaluate(el=>el.scrollWidth>el.clientWidth+1),false,`Match overflow at ${width}`);
    }
    assert.deepEqual(errors,[]);
    console.log('Match history browser regressions passed');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
