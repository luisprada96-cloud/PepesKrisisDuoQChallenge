// Editor interactions and published gallery; all network traffic is isolated.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1050}});
    const names = {'atodoflash':'ATodoFlash','loselogidos':'LosELOgidos','marx-mises':'Marx&Mises','nocturnidad':'NocturnidadYGunthervosia','patarrota':'Pat@rrota','supersalidos':'Supersalidos','tiltanic':'TILTanic','triperosgap':'TriperosGAP','vapores':'VaporesEnElC2'};
    const items = Object.entries(names).map(([id,name]) => ({id,name,image:`/assets/tierlist/${id}.png`}));
    const ids = items.map(i => i.id), ranks = ['S','A','B','C','D'];
    const rows = Object.fromEntries(ranks.map((rank,i) => [rank, ids.slice(i*2,i*2+2)]));
    let posts = Array.from({length:13}, (_,i) => ({id:`post-${i}`,teamId:`team-${Math.floor(i/2)}`,teamName:'Marx&Mises',author:i ? `Participante ${i}` : '<img src=x onerror="window.injected=true">',createdAt:1792000000-i,tiers:rows}));
    const playerSlugs=['markel','guille','unluckypingu','unluckypanda','joji','luis','sendi','chicha','ikerpantv','pato','mclovin','fogell','taberneta','ameteum','papaportu','parradise','pablo-crespo','pablo-casco'];
    const playerItems=playerSlugs.map(slug=>({id:'player-'+slug,name:slug,teamName:'Equipo del jugador',image:'/assets/tierlist/player-'+slug+'.png'}));
    let playerPosts=[],playerPublished=false;
    let published = false, failPublish = false, requests = [];
    const errors = [];
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== 'http://pepes.test') return route.abort();
      const logged = request.headers().authorization === 'Bearer team-session';
      const isPlayers=url.searchParams.get('kind')==='players';
      const alreadyPublished=isPlayers?playerPublished:published;
      const catalogItems=isPlayers?playerItems:items;
      const activePosts=isPlayers?playerPosts:posts;
      const publishing = logged ? {teamId:'mine',teamName:'Marx&Mises',canPublish:!alreadyPublished,reason:alreadyPublished?'browser':'ready',message:alreadyPublished?'Ya has publicado una tierlist desde este navegador.':'Publicando como Marx&Mises.'} : {canPublish:false,reason:'login',message:'Inicia sesión con tu equipo para publicar.'};
      if (url.pathname === '/api/tierlists') {
        let offset = Number(url.searchParams.get('offset') || 0);
        if (request.method() === 'POST') {
          if (failPublish) return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudo guardar la tierlist.'})});
          const body = request.postDataJSON(); requests.push({body,auth:request.headers().authorization});
          assert.equal(logged,true);
          assert.equal(alreadyPublished,false);
          assert.equal(body.kind,isPlayers?'players':'teams');
          if(isPlayers)playerPublished=true;else published=true; publishing.canPublish=false; publishing.reason='browser'; publishing.message='Ya has publicado una tierlist desde este navegador.';
          activePosts.unshift({id:isPlayers?'mine-player-post':'mine-post',teamId:'mine',teamName:'Marx&Mises',author:body.author,createdAt:1792001000,tiers:body.tiers});
          offset=0;
        }
        return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,kind:isPlayers?'players':'teams',items:catalogItems,tiers:ranks,posts:activePosts.slice(offset,offset+6),total:activePosts.length,offset,limit:6,publishing})});
      }
      if (url.pathname.startsWith('/api/')) return route.fulfill({contentType:'application/json',body:'{}'});
      const file = url.pathname.slice(1);
      if (!['tierlist.html','tierlist.js','tierlist.css','styles.css','data.js','alerts.js'].includes(file) && ![...items,...playerItems].some(i=>i.image===url.pathname)) return route.fulfill({status:404,body:''});
      const mime = file.endsWith('.png')?'image/png':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html';
      return route.fulfill({contentType:mime,body:fs.readFileSync(path.join(__dirname,file))});
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://pepes.test/tierlist.html');
    await page.waitForSelector('[data-tierlist-post]');
    assert.equal(await page.locator('[data-tierlist-post]').count(),6);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    await page.locator('#tierlist-next').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-page-info').textContent==='Página 2 de 3');
    await page.locator('#tierlist-next').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-page-info').textContent==='Página 3 de 3');
    assert.equal(await page.locator('[data-tierlist-post]').count(),1);
    await page.locator('[data-tierlist-expand]').click();
    assert.equal(await page.locator('#tierlist-detail').isVisible(),true);
    assert.equal(await page.locator('#tierlist-detail .tier-item').count(),9);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tierlist-detail').isVisible(),false);
    await page.locator('[data-tierlist-view=editor]').click();
    await page.waitForSelector('#tierlist-pool [data-tierlist-item]');
    assert.equal(await page.locator('#tierlist-pool [data-tierlist-item]').count(),9);
    assert.equal(await page.locator('#tierlist-publish').isDisabled(),true);
    // Native drag-and-drop plus keyboard reordering inside the row.
    await page.locator(`[data-tierlist-item=${ids[0]}]`).dragTo(page.locator('.tier-items[data-place=S]'));
    await page.locator(`[data-tierlist-item=${ids[1]}]`).dragTo(page.locator('.tier-items[data-place=S]'));
    assert.equal(await page.locator('.tier-items[data-place=S] [data-tierlist-item]').count(),2);
    await page.locator(`[data-tierlist-item=${ids[1]}]`).focus();
    await page.keyboard.press('ArrowLeft');
    // Tap/click selection works without dragging, including on mobile.
    await page.setViewportSize({width:390,height:844});
    for (let i=2;i<ids.length;i++) {
      await page.locator(`[data-tierlist-item=${ids[i]}]`).click();
      await page.locator(`button.tier-label[data-place=${ranks[Math.floor(i/2)]}]`).click();
    }
    assert.equal(await page.locator('#tierlist-pool [data-tierlist-item]').count(),0);
    assert.equal(await page.locator('#tierlist-board [data-tierlist-item]').count(),9);
    assert.equal(await page.locator('#tierlist-publish').isDisabled(),true,'guest can build but cannot publish');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no mobile overflow');
    await page.locator('#tierlist-author').fill('Luis');
    await page.reload();
    await page.waitForSelector('#tierlist-board [data-tierlist-item]');
    assert.equal(await page.locator('#tierlist-board [data-tierlist-item]').count(),9,'draft survives reload');
    assert.equal(await page.locator('#tierlist-author').inputValue(),'Luis');
    await page.evaluate(()=>{sessionStorage.setItem('pepes_player_token','team-session');window.dispatchEvent(new Event('focus'));});
    await page.waitForFunction(()=>!document.getElementById('tierlist-publish').disabled);
    await page.setViewportSize({width:1440,height:1050});
    if(process.env.TIERLIST_EDITOR_SCREENSHOT) await page.locator('main').screenshot({path:process.env.TIERLIST_EDITOR_SCREENSHOT});
    failPublish=true;
    await page.locator('#tierlist-publish').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-form-error').textContent.includes('No se pudo guardar'));
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('pepes_tierlist_draft_v1')).author),'Luis');
    failPublish=false;
    await page.locator('#tierlist-publish').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-feedback').textContent.includes('ya está publicada'));
    assert.equal(requests.length,1);
    assert.equal(requests[0].auth,'Bearer team-session');
    assert.equal(requests[0].body.author,'Luis');
    assert.deepEqual(new Set(Object.values(requests[0].body.tiers).flat()),new Set(ids));
    assert.deepEqual(requests[0].body.tiers.S,[ids[1],ids[0]]);
    assert.match(await page.locator('[data-tierlist-post]').first().textContent(),/Tierlist de Luis.*Marx&Mises/);
    assert.equal(await page.locator('[data-tierlist-post]').count(),6);
    assert.equal(await page.evaluate(()=>localStorage.getItem('pepes_tierlist_draft_v1')),null);
    if(process.env.TIERLIST_GALLERY_SCREENSHOT) await page.locator('main').screenshot({path:process.env.TIERLIST_GALLERY_SCREENSHOT});
    await page.locator('[data-tierlist-view=editor]').click();
    assert.equal(await page.locator('#tierlist-publish').isDisabled(),true);
    assert.match(await page.locator('#tierlist-publishing-status').textContent(),/Ya has publicado/);
    await page.locator('#tierlist-form').dispatchEvent('submit');
    assert.equal(requests.length,1,'used browser cannot publish another tierlist');
    await page.setViewportSize({width:320,height:800});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const images = await page.locator('#tierlist-board img').evaluateAll(list=>list.every(img=>img.complete && img.naturalWidth===400));
    assert.equal(images,true,'original photos load');
    await page.locator('[data-tierlist-kind=players]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#tierlist-pool [data-tierlist-item]').length===18);
    assert.equal(await page.locator('[data-tierlist-kind=players]').getAttribute('aria-pressed'),'true');
    assert.match(await page.locator('#tierlist-description').textContent(),/18 integrantes/);
    assert.match(await page.locator('#tierlist-remaining').textContent(),/18 integrantes pendientes/);
    assert.match(await page.locator('#tierlist-publishing-status').textContent(),/Publicando como/,'team tierlist did not spend player quota');
    assert.equal(new URL(page.url()).searchParams.get('tipo'),'integrantes');
    await page.locator(`[data-tierlist-item="${playerItems[0].id}"]`).click();
    await page.locator('button.tier-label[data-place=S]').click();
    await page.locator('#tierlist-author').fill('Autor de integrantes');
    await page.locator('[data-tierlist-kind=teams]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#tierlist-board [data-tierlist-item]').length===9);
    assert.equal(await page.locator('#tierlist-author').inputValue(),'Luis','team draft remains separate');
    assert.equal(await page.locator('#tierlist-publish').isDisabled(),true,'team quota remains used');
    await page.locator('[data-tierlist-kind=players]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#tierlist-pool [data-tierlist-item]').length===17);
    assert.equal(await page.locator('#tierlist-author').inputValue(),'Autor de integrantes');
    await page.reload();
    await page.waitForFunction(()=>document.querySelectorAll('#tierlist-pool [data-tierlist-item]').length===17);
    assert.equal(await page.locator('#tierlist-author').inputValue(),'Autor de integrantes','player draft and active tab survive reload');
    for(let i=1;i<playerItems.length;i++){
      await page.locator(`[data-tierlist-item="${playerItems[i].id}"]`).click();
      await page.locator(`button.tier-label[data-place=${ranks[Math.floor(i/4)]}]`).click();
    }
    assert.equal(await page.locator('#tierlist-board .tier-item').count(),18);
    assert.equal(await page.locator('#tierlist-publish').isEnabled(),true);
    for(const width of [1440,768,390,320]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'player editor fits '+width);
    }
    await page.waitForFunction(()=>[...document.querySelectorAll('#tierlist-board img')].every(img=>img.complete&&img.naturalWidth===400));
    if(process.env.TIERLIST_PLAYERS_SCREENSHOT)await page.locator('main').screenshot({path:process.env.TIERLIST_PLAYERS_SCREENSHOT});
    await page.locator('#tierlist-publish').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-feedback').textContent.includes('ya está publicada'));
    assert.equal(requests.length,2);
    assert.equal(requests[1].body.kind,'players');
    assert.equal(requests[1].body.author,'Autor de integrantes');
    assert.deepEqual(new Set(Object.values(requests[1].body.tiers).flat()),new Set(playerItems.map(i=>i.id)));
    assert.equal(await page.locator('[data-tierlist-post]').count(),1,'player gallery is independent');
    assert.equal(await page.locator('[data-tierlist-post] .tier-item').count(),18);
    assert.equal(await page.evaluate(()=>localStorage.getItem('pepes_tierlist_players_draft_v1')),null);
    await page.locator('[data-tierlist-expand]').click();
    assert.equal(await page.locator('#tierlist-detail .tier-item').count(),18);
    await page.keyboard.press('Escape');
    await page.locator('[data-tierlist-kind=teams]').click();
    await page.waitForFunction(()=>document.getElementById('tierlist-count').textContent==='14 tierlists publicadas');
    assert.equal(await page.locator('[data-tierlist-post]').count(),6);
    assert.equal(await page.locator('[data-tierlist-post]').first().locator('.tier-item').count(),9,'team posts still render all original teams');
    assert.deepEqual(errors,[]);
    console.log('Tierlist browser checks passed: public gallery, pagination, modal, XSS, drag and drop, keyboard/tap, draft, login, failed save, author, immutable publication, two independent catalogs/quotas/drafts and mobile.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
