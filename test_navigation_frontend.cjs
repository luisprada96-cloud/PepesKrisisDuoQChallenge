// Shared navigation and separate data loading, with isolated API fixtures.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
  try {
    const pages=['index.html','torneo.html','premios.html','clips.html','resumen.html','tierlist.html','porra.html','pickem.html','player.html','admin.html','campeones.html','apuestas.html'];
    const context=await browser.newContext();
    const requests=[],errors=[];
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!=='http://pepes.test')return route.abort();
      if(url.pathname.startsWith('/api/')) {
        requests.push(url.pathname);
        let data={};
        if(url.pathname==='/api/config')data={penaltyCatalog:[{id:'one',name:'Castigo',desc:'Regla',icon:'🎲'}],penaltyWeights:{one:100},shellRewardRules:{inventoryLimit:5,perMatchLimit:2,rules:[{name:'Racha',requirement:'4 victorias consecutivas'}]}};
        if(url.pathname==='/api/trophies')data={status:'provisional',cards:[{id:'champion',title:'Campeón',icon:'🏆',description:'Mayor ELO',entries:[{name:'Equipo ganador',teamName:'Equipo',value:'Gold I · 30 LP'}]},{id:'TOP',title:'Mejor Top',icon:'🏅',description:'KDA en su rol',entries:[]}]};
        return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      }
      const file=url.pathname.slice(1);
      if(![...pages,'navigation.js','data.js','torneo.js','premios.js','styles.css','clips.css','tierlist.css','porra.css','pickem.css','resumen.css','campeones.css'].includes(file))return route.fulfill({status:404,body:''});
      let body=fs.readFileSync(path.join(__dirname,file));
      // Other feature behavior has its own suites; preserve only the scripts under test.
      if(file.endsWith('.html'))body=body.toString().replace(/<script\b[^>]*src="([^"]+)"[^>]*>\s*<\/script>/g,(tag,src)=>['navigation.js','data.js','torneo.js','premios.js'].includes(src)?tag:'');
      return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body});
    });
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    for(const file of pages) {
      await page.setViewportSize({width:1440,height:1000});
      await page.goto('http://pepes.test/'+file);
      const header=page.locator('.site-header');
      assert.equal(await header.locator('#primary-navigation a').count(),10);
      assert.equal(await header.getByRole('link',{name:'Campeones',exact:true}).count(),1);
      assert.equal(await header.getByRole('link',{name:'Torneo',exact:true}).count(),1);
      assert.equal(await header.getByRole('link',{name:'Premios',exact:true}).count(),1);
      const links=await header.locator('#primary-navigation a').evaluateAll(a=>a.map(l=>l.getAttribute('href')));
      assert.equal(links[links.indexOf('tierlist.html')+1],'porra.html');
      assert.equal(await header.locator('[aria-current="page"]').count(),1,'exactly one current section');
      assert.equal(await header.locator('[aria-current="page"]').getAttribute('href'),file);
      assert.equal(await page.locator('#nav-menu-toggle').isVisible(),false);
      assert.equal(await page.locator('#primary-navigation').isVisible(),true);
      for(const width of [768,390,320]) {
        await page.setViewportSize({width,height:900});
        await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        assert.equal(await page.locator('#primary-navigation').isVisible(),false);
        assert.equal(await page.locator('#nav-menu-toggle').isVisible(),true);
        assert.equal(await header.getByRole('link',{name:'Mi Panel',exact:true}).isVisible(),true);
        assert.equal(await header.getByRole('link',{name:'Panel Admin',exact:true}).isVisible(),true);
        const layout=await header.evaluate(el=>({width:el.scrollWidth,height:el.getBoundingClientRect().height}));
        assert.ok(layout.width<=width,`${file}: header fits ${width}px`);
        assert.ok(layout.height<90,`${file}: compact closed header`);
        await page.locator('#nav-menu-toggle').focus();
        await page.keyboard.press('Enter');
        assert.equal(await page.locator('#nav-menu-toggle').getAttribute('aria-expanded'),'true');
        assert.equal(await page.locator('#primary-navigation').isVisible(),true);
        assert.equal(await header.getByRole('link',{name:'Premios',exact:true}).isVisible(),true);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#primary-navigation').isVisible(),false);
        assert.equal(await page.locator('#nav-menu-toggle').evaluate(el=>el===document.activeElement),true);
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    requests.length=0;
    await page.goto('http://pepes.test/torneo.html');
    await page.waitForSelector('#roulette-rules-list article');
    assert.equal(await page.locator('#rules').count(),1);
    assert.equal(await page.locator('#shell-rewards-body tr').count(),1);
    assert.equal(await page.locator('#trophies-grid').count(),0);
    assert.ok(requests.includes('/api/config'));assert.ok(!requests.includes('/api/trophies'));
    requests.length=0;
    await page.getByRole('link',{name:'Premios',exact:true}).click();
    await page.waitForSelector('.trophy-card');
    assert.equal(await page.locator('.trophy-card').count(),2);
    assert.equal(await page.locator('#roulette-rules-list').count(),0);
    assert.ok(requests.includes('/api/trophies'));assert.ok(!requests.includes('/api/config'));
    await page.goto('http://pepes.test/torneo.html#trophies');
    await page.waitForURL('**/premios.html#trophies');
    await page.waitForSelector('.trophy-card');
    // The open menu closes when switching back to desktop and stays closed on return.
    await page.setViewportSize({width:390,height:900});
    await page.locator('#nav-menu-toggle').click();
    await page.setViewportSize({width:1440,height:900});
    await page.waitForFunction(()=>document.getElementById('nav-menu-toggle').getAttribute('aria-expanded')==='false');
    assert.equal(await page.locator('#primary-navigation').isVisible(),true);
    await page.setViewportSize({width:390,height:900});
    assert.equal(await page.locator('#primary-navigation').isVisible(),false);
    await page.locator('#nav-menu-toggle').click();
    await page.locator('h1').click();
    assert.equal(await page.locator('#primary-navigation').isVisible(),false);
    const noJs=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:900}});
    await noJs.route('**/*',route=>{
      const file=new URL(route.request().url()).pathname.slice(1);
      if(!['torneo.html','styles.css'].includes(file))return route.abort();
      return route.fulfill({contentType:file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
    });
    const fallback=await noJs.newPage();await fallback.goto('http://pepes.test/torneo.html');
    assert.equal(await fallback.locator('#primary-navigation').isVisible(),true,'links work without JS');
    assert.equal(await fallback.locator('#nav-menu-toggle').isVisible(),false);
    await noJs.close();
    assert.deepEqual(errors,[]);
    console.log('Navigation checks passed: 12 pages, separate tabs/data, 4 widths, keyboard/menu, resize, legacy trophy link and no-JS fallback.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
