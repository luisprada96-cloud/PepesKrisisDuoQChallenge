// Guest discussions must survive refreshes, connection errors and clip playback.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    let comments = Array.from({length:14},(_,i)=>({id:`comment-${i}`,name:i ? 'Invitado' : '<b>X</b>',
      text:i ? `Comentario ${i}` : '<img src=x onerror="window.badComment=true">',createdAt:1800000000-i}));
    let archived = false, failRead = false, failPost = false, loseReply = false, readCount = 0;
    const writes = [], savedRequests = new Map(), errors = [];
    const clip = {id:'clip-1',title:'Una jugada',slug:'ExampleClip',url:'https://clips.twitch.tv/ExampleClip',team:'Equipo A',initials:'EA',scene:1,createdAt:1800000000,votes:2,liked:false};
    const week = '2026-10-15';
    const commentPage = offset => ({week,clipId:clip.id,comments:comments.slice(offset,offset+10),total:comments.length,offset,limit:10,hasMore:offset+10<comments.length});
    await context.route('**/*',async route => {
      const req=route.request(),url=new URL(req.url());
      if (url.origin !== 'http://comments.test') return route.abort();
      if (url.pathname === '/api/clips/comments') {
        if (req.method() === 'GET') {
          readCount++;
          if (failRead) return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudieron cargar los comentarios.'})});
          return route.fulfill({contentType:'application/json',body:JSON.stringify(commentPage(Number(url.searchParams.get('offset')) || 0))});
        }
        const body=req.postDataJSON(); writes.push({body,authorization:req.headers().authorization});
        if (failPost) { failPost=false; return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'No se pudo guardar el comentario.'})}); }
        let comment=savedRequests.get(body.requestId);
        if (!comment) {
          comment={id:`new-${savedRequests.size}`,name:body.name,text:body.text,createdAt:Date.now()/1000};
          savedRequests.set(body.requestId,comment); comments.unshift(comment);
        }
        if (loseReply) { loseReply=false; return route.abort(); }
        return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,comment,...commentPage(0)})});
      }
      if (url.pathname === '/api/clips') return route.fulfill({contentType:'application/json',body:JSON.stringify({week,archived,
        clips:[{...clip,commentCount:comments.length}],teams:[{id:'a',name:'Equipo A'}],voting:null,weeklyReward:{closed:archived}})});
      if (url.pathname.startsWith('/api/')) return route.fulfill({contentType:'application/json',body:'{}'});
      const filename=url.pathname.slice(1);
      if (!['clips.html','clips.js','clips.css','styles.css','data.js','alerts.js','navigation.js'].includes(filename)) return route.fulfill({status:404,body:''});
      return route.fulfill({contentType:filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,filename))});
    });
    const page=await context.newPage(); page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://comments.test/clips.html');
    const toggle=page.locator('[data-comments-toggle]'),form=page.locator('[data-comment-form]');
    const input=form.locator('input'),textarea=form.locator('textarea'),submit=form.locator('[type="submit"]');
    await toggle.waitFor();
    assert.equal(readCount,0,'comments load lazily');
    assert.equal(await page.locator('[data-vote]').isDisabled(),true,'commenting does not grant voting privileges');
    await toggle.click();
    await page.locator('.clip-comment').first().waitFor();
    assert.equal(await page.locator('.clip-comment').count(),10);
    assert.equal(await page.locator('.clip-comment img, .clip-comment b').count(),0);
    assert.match(await page.locator('.clip-comment').first().textContent(),/<b>X<\/b>.*<img/);
    assert.equal(await input.getAttribute('maxlength'),'15');
    assert.equal(await input.getAttribute('required'),null);
    assert.equal(await textarea.getAttribute('maxlength'),'200');
    await page.locator('[data-comments-more]').click();
    await page.waitForFunction(()=>document.querySelectorAll('.clip-comment').length===14);
    await textarea.fill('¡Buena jugada!');
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent==='Comentario publicado.');
    assert.equal(writes.length,1);
    assert.equal(writes[0].body.name,'');
    assert.equal(writes[0].authorization,undefined,'no login required');
    assert.match(await page.locator('.clip-comment').first().textContent(),/Anónimo.*¡Buena jugada!/);
    assert.equal(await textarea.inputValue(),'');
    await input.fill('NombreDe15Chars');
    await textarea.fill('Borrador pendiente');
    await toggle.click(); await toggle.click();
    assert.equal(await textarea.inputValue(),'Borrador pendiente','collapsing preserves draft');
    await page.locator('[data-play]').click();
    await page.locator('iframe').waitFor();
    await textarea.focus();
    await page.evaluate(()=>{window.savedClipFrame=document.querySelector('iframe');document.querySelector('[data-comment-form] textarea').setSelectionRange(4,4);});
    const refresh=()=>Promise.all([page.waitForResponse(r=>new URL(r.url()).pathname==='/api/clips'),page.evaluate(()=>window.dispatchEvent(new Event('focus')))]);
    comments.unshift({id:'external-comment',name:'Otro jugador',text:'Comentario de otra persona',createdAt:Date.now()/1000});
    await refresh();
    await page.waitForFunction(()=>document.querySelector('.clip-comment').textContent.includes('Comentario de otra persona'));
    assert.equal(await textarea.inputValue(),'Borrador pendiente');
    assert.equal(await textarea.evaluate(node=>node.selectionStart),4);
    assert.equal(await page.evaluate(()=>document.querySelector('iframe')===window.savedClipFrame),true);
    failPost=true;
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent.includes('No se pudo guardar'));
    const retryId=writes.at(-1).body.requestId;
    assert.equal(await textarea.inputValue(),'Borrador pendiente');
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent==='Comentario publicado.');
    assert.equal(writes.at(-1).body.requestId,retryId,'connection retries retain idempotency key');
    assert.equal(await input.inputValue(),'NombreDe15Chars');
    await textarea.fill('Respuesta perdida'); loseReply=true;
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').classList.contains('is-error'));
    const count=comments.length;
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent==='Comentario publicado.');
    assert.equal(comments.length,count,'retry after ambiguous save cannot duplicate comment');
    const writeCount=writes.length;
    await form.evaluate(node=>{node.elements.text.value='x'.repeat(201);node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
    assert.equal(writes.length,writeCount);
    assert.match(await page.locator('[data-comment-feedback]').textContent(),/200 caracteres/);
    await input.fill('X'.repeat(15)); await textarea.fill('x'.repeat(200));
    assert.equal(await form.locator('[data-comment-counter]').textContent(),'200/200');
    await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent==='Comentario publicado.');
    assert.equal(writes.at(-1).body.name.length,15);assert.equal(writes.at(-1).body.text.length,200);
    archived=true;await refresh();
    assert.equal(await page.locator('#clips-publish').isDisabled(),true);
    assert.equal(await submit.isDisabled(),false,'archive discussions stay open independently from likes and prizes');
    await textarea.fill('También en el archivo');await submit.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent==='Comentario publicado.');
    failRead=true;await toggle.click();await toggle.click();
    await page.waitForFunction(()=>document.querySelector('[data-comment-feedback]').textContent.includes('No se pudieron cargar'));
    const reads=readCount;await page.waitForTimeout(250);assert.equal(readCount,reads,'read errors do not cause a retry loop');
    failRead=false;await toggle.click();await toggle.click();
    await page.waitForResponse(r=>new URL(r.url()).pathname==='/api/clips/comments');
    for (const width of [1440,768,540,375,320]) {
      await page.setViewportSize({width,height:1100});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`no overflow at ${width}px`);
      assert.equal(await textarea.evaluate(node=>node.getBoundingClientRect().right<=innerWidth),true);
    }
    if (process.env.COMMENTS_SCREENSHOT) {
      archived=false;
      comments=[{id:'preview-1',name:'Nico',text:'Ese robo de Nashor merece un pepazo extra 😂',createdAt:Date.now()/1000-240},
        {id:'preview-2',name:'',text:'El smite más tranquilo del torneo.',createdAt:Date.now()/1000-600}];
      await page.setViewportSize({width:1280,height:1200});
      await page.reload();await toggle.waitFor();await toggle.click();
      await page.locator('.clip-comment').first().waitFor();
      await page.locator('.clip-post').screenshot({path:process.env.COMMENTS_SCREENSHOT});
    }
    assert.deepEqual(errors,[]);
    console.log('Guest comment browser checks passed: limits, XSS, pagination, no login, drafts, playback, retries, archives and five widths.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
