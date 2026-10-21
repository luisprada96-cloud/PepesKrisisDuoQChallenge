const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1100}});
  let wallet=null,fail=false,loseResponse=false,slow=false,conflict=false,quoteSeed=12345;
  const writes=[],errors=[],operations=new Map();
  const allowed=new Set(['tienda.html','tienda.css','tienda.js','navigation.js','styles.css','assets/shop/pepe-shop.webp','assets/shop/pepazo.webp','favicon.ico','favicon.svg']);
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin!=='http://shop.test')return route.abort();
   if(url.pathname==='/api/shop'){
    if(fail)return route.abort();
    const board=()=>({product:{id:'pepazo',name:'Pepazo',unitPrice:70},quoteSeed,wallet});
    if(req.method()==='POST'){
     const body=req.postDataJSON();writes.push(body);
     if(slow)await new Promise(resolve=>setTimeout(resolve,150));
     if(conflict){conflict=false;wallet={...wallet,balance:30};return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'No tienes suficiente oro disponible.'})});}
     if(!req.headers().authorization)return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:'Inicia sesión'})});
     if(!operations.has(body.requestId)){
      if(wallet.balance<body.quantity*70)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'Sin oro'})});
      wallet={...wallet,balance:wallet.balance-body.quantity*70,inventory:wallet.inventory+body.quantity};
      operations.set(body.requestId,{id:'receipt-'+operations.size,quantity:body.quantity,unitPrice:70,total:70*body.quantity});
     }
     if(loseResponse){loseResponse=false;return route.abort();}
     return route.fulfill({contentType:'application/json',body:JSON.stringify({...board(),success:true,purchase:operations.get(body.requestId)})});
    }
    return route.fulfill({contentType:'application/json',body:JSON.stringify(board())});
   }
   const file=url.pathname.slice(1);
   if(!allowed.has(file))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.webp')?'image/webp':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://shop.test/tienda.html');
  await page.waitForFunction(()=>!document.querySelector('#shop-login').hidden);
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  assert.equal(await page.locator('#shop-price').textContent(),'70');
  assert.equal(await page.locator('.shop-backdrop').evaluate(img=>img.complete&&img.naturalWidth>0),true);
  wallet={teamId:'a',teamName:'Marx&Mises',balance:230,reserved:20,inventory:2};
  await page.evaluate(()=>sessionStorage.setItem('pepes_player_token','owner-token'));
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='230');
  assert.equal(await page.locator('#shop-buy').isDisabled(),false);
  assert.match(await page.locator('#shop-reserved').textContent(),/20 oro reservado/);
  await page.locator('#shop-plus').click();
  assert.equal(await page.locator('#shop-total').textContent(),'140');
  assert.equal(await page.locator('#shop-after').textContent(),'90 oro');
  await page.locator('#shop-quantity').fill('1.5');
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  await page.locator('#shop-quantity').fill('4');
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  await page.locator('#shop-quantity').fill('2');
  await page.locator('#shop-buy').click();
  assert.match(await page.locator('#shop-confirm-description').textContent(),/140.*Marx&Mises.*2 pepazos/);
  await page.locator('#shop-cancel').click();assert.equal(writes.length,0);
  async function readCycle(inspectLong=false){
   const result=[];
   for(let i=0;i<52;i++){
    await page.locator('#shop-talk').click();
    const text=await page.locator('#shop-quote').textContent();result.push(text);
    if(inspectLong&&text.startsWith('En realidad no hay limite')){
     assert.ok(text.endsWith('falleciendo en 1925.'));
     assert.ok(!/https?:|\]\(/.test(text),'the supplied monologue is plain text without hyperlinks');
     assert.equal(await page.locator('#shop-quote a').count(),0);
     assert.equal(await page.locator('#shop-speech').evaluate(el=>el.classList.contains('is-rambling')),true);
     for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      assert.equal(await page.locator('#shop-quote').evaluate(el=>el.scrollHeight>el.clientHeight),true);
      assert.equal(await page.locator('#shop-talk').isVisible(),true);
      assert.equal(await page.locator('#shop-buy').isEnabled(),true);
      await page.locator('#shop-quote').focus();await page.keyboard.press('End');
      if(width===390){
       fs.mkdirSync(path.join(__dirname,'preview'),{recursive:true});
       await page.locator('#shop-quote').evaluate(el=>el.scrollTop=0);
       await page.screenshot({path:path.join(__dirname,'preview','tienda-pepe-monologo-mobile.png'),fullPage:true});
      }
     }
     await page.setViewportSize({width:1440,height:1100});
    }
   }
   assert.equal(new Set(result).size,52,'every phrase appears exactly once per cycle');
   return result;
  }
  const cycle=await readCycle(true);
  assert.ok(cycle.includes('Los supports convocan una huelga: cobrar en «gj» ya no paga las wards.'));
  assert.ok(cycle.includes('Has conseguido una pentakill. Pepe te ofrece exactamente el mismo precio.'));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='230');
  assert.deepEqual(await readCycle(),cycle,'the same deployment keeps its shuffled order after reload');
  quoteSeed=67890;
  await page.reload();await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='230');
  const nextCycle=await readCycle();
  assert.notDeepEqual(nextCycle,cycle,'a new deployment reshuffles the phrases');
  assert.deepEqual([...nextCycle].sort(),[...cycle].sort(),'reshuffling neither loses nor duplicates phrases');
  await page.locator('#shop-talk').click();
  if(await page.locator('#shop-speech').evaluate(el=>el.classList.contains('is-rambling')))await page.locator('#shop-talk').click();
  assert.equal(await page.locator('#shop-speech').evaluate(el=>el.classList.contains('is-rambling')),false);
  await page.locator('#shop-quantity').fill('2');
  await page.locator('#shop-buy').click();
  loseResponse=true;
  await page.locator('#shop-confirm-buy').click();
  await page.waitForFunction(()=>!document.querySelector('#shop-error').hidden);
  assert.match(await page.locator('#shop-error').textContent(),/sin duplicar/);
  const requestId=writes[0].requestId;
  // A page reload after an uncertain response retains the same receipt, even
  // though the original debit means there is no longer enough gold for 2.
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#shop-buy').textContent==='Comprobar compra pendiente');
  assert.equal(await page.locator('#shop-quantity').isDisabled(),true);
  assert.equal(await page.locator('#shop-quantity').inputValue(),'2');
  assert.equal(await page.locator('#shop-buy').isDisabled(),false);
  await page.locator('#shop-buy').click();
  assert.match(await page.locator('#shop-confirm-description').textContent(),/sin otro cargo/);
  slow=true;await page.locator('#shop-confirm-buy').click();
  assert.equal(await page.locator('#shop-confirm-buy').isDisabled(),true);
  await page.waitForFunction(()=>!document.querySelector('#shop-confirm').open);slow=false;
  assert.equal(writes.at(-1).requestId,requestId);
  assert.equal(operations.size,1);
  assert.equal(wallet.balance,90);assert.equal(wallet.inventory,4);
  assert.match(await page.locator('#shop-stock').textContent(),/4 pepazos/);
  assert.match(await page.locator('#shop-feedback').textContent(),/2 pepazos por 140/);
  assert.equal(await page.locator('#shop-quote').textContent(),'Pepe mejora sus previsiones económicas.');
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('pepes_shop_pending_a')),null);
  // A purchase that uses the last coins keeps its success quip after refresh.
  wallet={...wallet,balance:70};
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='70');
  await page.locator('#shop-buy').click();await page.locator('#shop-confirm-buy').click();
  await page.waitForFunction(()=>!document.querySelector('#shop-confirm').open);
  assert.equal(wallet.balance,0);
  assert.equal(await page.locator('#shop-quote').textContent(),'Pepe mejora sus previsiones económicas.');
  wallet={...wallet,balance:90};
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='90');
  // Gold used elsewhere between opening the dialog and confirmation is rejected.
  await page.locator('#shop-buy').click();conflict=true;
  await page.locator('#shop-confirm-buy').click();
  await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='30');
  assert.equal(await page.locator('#shop-confirm').evaluate(d=>d.open),false);
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  assert.match(await page.locator('#shop-notice').textContent(),/faltan 40/);
  assert.equal(await page.locator('#shop-quote').textContent(),'Equipo sin oro anuncia que la tienda está carísima.');
  await page.locator('#shop-talk').click();
  const chosenQuote=await page.locator('#shop-quote').textContent();
  assert.notEqual(chosenQuote,'Equipo sin oro anuncia que la tienda está carísima.');
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForTimeout(100);
  assert.equal(await page.locator('#shop-quote').textContent(),chosenQuote,'balance refresh must not interrupt the merchant conversation');
  fail=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#shop-feedback').textContent.includes('no puede consultar'));
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  fail=false;wallet={...wallet,balance:210};
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#shop-balance').textContent==='210');
  assert.equal(await page.locator('#shop-buy').isDisabled(),false);
  assert.equal(await page.locator('#shop-feedback').textContent(),'');
  await page.waitForFunction(()=>document.querySelectorAll('.shop-flying-item,.shop-flying-coin').length===0);
  fs.mkdirSync(path.join(__dirname,'preview'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'preview','tienda-desktop.png'),fullPage:true});
  for(const width of [768,390,320]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`no overflow at ${width}px`);
   await page.locator('#shop-buy').scrollIntoViewIfNeeded();
   assert.equal(await page.locator('#shop-buy').isVisible(),true);
   await page.locator('#shop-buy').click();
   const bounds=await page.locator('#shop-confirm').boundingBox();
   assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width);
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('#shop-confirm').evaluate(d=>d.open),false);
  }
  await page.setViewportSize({width:390,height:900});
  await page.locator('.shop-item-description').click();
  await page.screenshot({path:path.join(__dirname,'preview','tienda-mobile.png'),fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('#shop-item').evaluate(el=>getComputedStyle(el).animationName),'none');
  assert.equal(await page.locator('.shop-mote').first().evaluate(el=>getComputedStyle(el).display),'none');
  // A team switch must not reuse the previous team's pending receipt.
  await page.locator('#shop-buy').click();
  const beforeSwitch=writes.length;
  await page.evaluate(()=>{sessionStorage.setItem('pepes_shop_pending_a',JSON.stringify({teamId:'a',quantity:1,requestId:'old-purchase-request-123'}));sessionStorage.setItem('pepes_player_token','other-token');});
  wallet={teamId:'b',teamName:'ATodoFlash',balance:70,reserved:0,inventory:0};
  await page.locator('#shop-confirm-buy').click();
  await page.waitForFunction(()=>document.querySelector('#shop-team').textContent==='ATodoFlash');
  assert.equal(writes.length,beforeSwitch,'changing session during confirmation cannot charge the other team');
  assert.match(await page.locator('#shop-buy').textContent(),/^Comprar/);
  await page.evaluate(()=>sessionStorage.removeItem('pepes_player_token'));wallet=null;
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>!document.querySelector('#shop-login').hidden);
  assert.equal(await page.locator('#shop-buy').isDisabled(),true);
  assert.equal(await page.locator('#shop-balance').textContent(),'—');
  assert.deepEqual(errors,[]);
  console.log('Shop UI passed: price 70, login, quantity/total, confirm/cancel, shared gold, lost-response retry across reload, concurrent spend, offline recovery, responsive layout, keyboard, reduced motion and team switch.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
