const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
 try{
  const context=await browser.newContext();
  await context.addInitScript(()=>{
   const fetchOriginal=window.fetch;
   window.fetch=(url,options)=>url!=='/api/player/events'?fetchOriginal(url,options):Promise.resolve(new Response(new ReadableStream({start(c){
    window.sendAttack=attack=>c.enqueue(new TextEncoder().encode('data: '+JSON.stringify({team:{id:'receiver',name:'Equipo receptor real'},attacks:[attack]})+'\n\n'));
    options.signal.addEventListener('abort',()=>{try{c.close();}catch(_){}});
   }}),{headers:{'Content-Type':'text/event-stream'}}));
  });
  await context.route('**/*',route=>{
   const url=new URL(route.request().url());if(url.origin!=='http://sender.test')return route.abort();
   if(url.pathname==='/api/duos')return route.fulfill({json:[{id:'receiver',teamName:'Equipo receptor real'}]});
   if(url.pathname==='/api/overlay/effects')return route.fulfill({json:{effects:[]}});
   if(url.pathname==='/api/overlay/login')return route.fulfill({json:{success:true,sessionToken:'obs_test-session'}});
   if(url.pathname==='/api/overlay/session')return route.fulfill({json:{success:true,teamId:'receiver',teamName:'Equipo receptor real'}});
   if(url.pathname==='/api/overlay/state')return route.fulfill({json:{success:true,duo:{id:'receiver',pendingShellAttacks:[]}}});
   if(url.pathname.startsWith('/api/overlay/media/'))return route.fulfill({body:fs.readFileSync(path.join(__dirname,'test_fixtures/overlay-sample.webm')),contentType:'video/webm'});
   const file=path.join(__dirname,url.pathname.slice(1));
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.mp3')?'audio/mpeg':'text/html'});
  });
  const page=await context.newPage();await page.goto('http://sender.test/overlay.html?team=receiver');
  await page.locator('#password').fill('test');await page.locator('#submit').click();
  await page.waitForFunction(()=>!!window.sendAttack);await page.locator('#hide').click();
  for(const [id,name] of [['one','Emisor real uno'],['two','Emisor real dos']]){
   await page.evaluate(({id,name})=>window.sendAttack({id,attackerName:name,overlayEffect:{kind:'video',url:'/api/overlay/media/'+'a'.repeat(64),durationMs:1200,senderRevealMs:200}}),{id,name});
   await page.waitForFunction(()=>document.querySelector('#alert').classList.contains('video-sender'));
   assert.equal(await page.locator('#attacker').textContent(),name);
   assert.equal(await page.locator('#target').textContent(),'Equipo receptor real');
   assert.equal(await page.locator('#effect-video').isVisible(),true);
   assert.equal(await page.locator('.message').evaluate(el=>getComputedStyle(el).opacity),'1');
   assert.equal(await page.locator('#alert').evaluate(el=>el.classList.contains('video-hold')),false);
   await page.waitForFunction(()=>document.querySelector('#alert').hidden,{}, {timeout:4000});
  }
  console.log('PASS: two real sender names appear over the playing video; no post-video hold or leaked names.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
