const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  const teams=[{id:'a',name:'Marx&Mises',players:[{key:'player1',name:'Luis'},{key:'player2',name:'Pepe'}]},
               {id:'b',name:'ATodoFlash',players:[{key:'player1',name:'Markel'},{key:'player2',name:'Guille'}]}];
  let wallet=null,markets=[],history=[],fail=false,loseResponse=false;
  const writes=[],errors=[],operations=new Map();
  const allowed=new Set(['apuestas.html','apuestas.css','apuestas.js','data.js','navigation.js','styles.css','alerts.js']);
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin!=='http://bets.test')return route.abort();
   if(url.pathname==='/api/bets'){
    if(fail)return route.abort();
    let data={teams,markets:url.searchParams.get('view')==='history'?history:markets,wallet,total:markets.length,rules:{waitSeconds:1200}};
    if(req.method()==='POST'){
     const body=req.postDataJSON();writes.push(body);
     if(!req.headers().authorization)return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:'Inicia sesión'})});
     if(!operations.has(body.requestId)){
      const now=Date.now()/1000;
      wallet={...wallet,balance:wallet.balance-body.amount,reserved:wallet.reserved+body.amount};
      const market=body.action==='create'?{id:'market-'+operations.size,targetId:body.targetId,teamName:teams.find(t=>t.id===body.targetId).name,
       metric:body.metric,playerKey:body.playerKey||null,playerName:teams.find(t=>t.id===body.targetId).players.find(p=>p.key===body.playerKey)?.name,
       lineHalf:body.line?Number(body.line.replace(',','.'))*2:null,createdAt:now,status:'OPEN',participants:1,
       sides:body.metric==='result'?{WIN:body.amount,LOSS:0}:{OVER:body.side==='OVER'?body.amount:0,UNDER:body.side==='UNDER'?body.amount:0},mine:[]}
       :markets.find(m=>m.id===body.marketId);
      market.mine.push({id:'my-bet-'+operations.size,amount:body.amount,side:body.metric==='result'?'WIN':body.side,createdAt:now,eligibleAt:now+1200,status:'PENDING'});
      if(body.action==='create')markets.unshift(market);
      operations.set(body.requestId,'ok');
     }
     data={...data,wallet,markets,total:markets.length,success:true,betId:'confirmed'};
     if(loseResponse){loseResponse=false;return route.abort();}
    }
    return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
   }
   const file=url.pathname.slice(1);
   if(!allowed.has(file))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,file))});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://bets.test/apuestas.html');
  await page.waitForFunction(()=>document.querySelector('#bet-target').options.length===3);
  assert.equal(await page.locator('#bet-create').isDisabled(),true);
  assert.equal(await page.locator('#bets-login').isVisible(),true);
  assert.equal(await page.locator('#bet-player-fields').isVisible(),false);
  assert.equal(await page.locator('#bet-line-fields').isVisible(),false);
  wallet={teamId:'a',teamName:'Marx&Mises',balance:10,reserved:0};
  await page.evaluate(()=>{sessionStorage.setItem('pepes_player_token','session');document.dispatchEvent(new Event('player-session-changed'));});
  await page.waitForFunction(()=>!document.querySelector('#bet-create').disabled);
  await page.selectOption('#bet-metric','deaths');
  await page.selectOption('#bet-target','a');
  assert.deepEqual(await page.locator('#bet-player option').allTextContents(),['Selecciona un integrante','Luis','Pepe']);
  await page.selectOption('#bet-target','b');
  assert.deepEqual(await page.locator('#bet-player option').allTextContents(),['Selecciona un integrante','Markel','Guille']);
  await page.selectOption('#bet-target','a');await page.selectOption('#bet-player','player1');
  assert.equal(await page.locator('#bet-line').getAttribute('placeholder'),'5,5');
  await page.locator('#bet-line').fill('a8,5');
  assert.equal(await page.locator('#bet-line').inputValue(),'8,5');
  await page.locator('#bet-line').fill('50,5');await page.locator('#bet-amount').fill('5');
  await page.locator('#bet-create').click();
  assert.equal(await page.locator('#bet-confirm').isVisible(),false);
  assert.match(await page.locator('#bet-form-error').textContent(),/49,5/);
  await page.locator('#bet-line').fill('8,5');await page.selectOption('#bet-side','OVER');
  await page.locator('#bet-create').click();
  assert.match(await page.locator('#bet-confirm-description').textContent(),/Marx&Mises.*Luis.*Más de 8,5 muertes/);
  assert.match(await page.locator('#bet-confirm-time').textContent(),/20 minutos/);
  await page.locator('#bet-confirm-cancel').click();assert.equal(writes.length,0);
  await page.locator('#bet-create').click();
  loseResponse=true;
  await page.locator('#bet-confirm-submit').click();
  await page.locator('#bet-confirm-error').waitFor({state:'visible'});
  assert.match(await page.locator('#bet-confirm-error').textContent(),/no se cobrará dos veces/);
  await page.locator('#bet-confirm-submit').click();
  await page.waitForFunction(()=>!document.querySelector('#bet-confirm').open);
  assert.equal(writes[0].requestId,writes[1].requestId);
  assert.equal(wallet.balance,5);assert.equal(wallet.reserved,5);
  assert.match(await page.locator('.bet-mine').textContent(),/Puede contar desde/);
  assert.equal(writes[0].line,'8,5');assert.equal(writes[0].playerKey,'player1');
  assert.match(await page.locator('.bet-card h3').textContent(),/Luis: 8,5 muertes/);
  fs.mkdirSync('preview',{recursive:true});
  await page.screenshot({path:'preview/apuestas-desktop.png',fullPage:true});
  await page.locator('[data-side="UNDER"]').click();
  await page.locator('#bet-join-amount').fill('2');await page.locator('#bet-confirm-submit').click();
  await page.waitForFunction(()=>!document.querySelector('#bet-confirm').open);
  assert.equal(writes.at(-1).action,'join');assert.equal(writes.at(-1).side,'UNDER');
  assert.equal(wallet.balance,3);
  await page.selectOption('#bet-metric','result');
  assert.equal(await page.locator('#bet-player-fields').isVisible(),false);
  assert.equal(await page.locator('#bet-line-fields').isVisible(),false);
  await page.locator('#bet-amount').fill('1');await page.locator('#bet-create').click();
  assert.match(await page.locator('#bet-confirm-description').textContent(),/WIN/);
  await page.locator('#bet-confirm-submit').click();await page.waitForFunction(()=>!document.querySelector('#bet-confirm').open);
  assert.equal(writes.at(-1).metric,'result');assert.equal(writes.at(-1).playerKey,undefined);assert.equal(writes.at(-1).line,undefined);
  history=[{...markets[0],id:'closed',status:'CLOSED',lastRound:{status:'SETTLED',winner:'WIN',pool:10,matchId:'EUW1_TEST',receivedAt:Date.now()/1000},mine:[]}];
  await page.locator('[data-bets-view="history"]').click();await page.locator('[data-market="closed"]').waitFor();
  assert.equal(await page.locator('[data-market="closed"] [data-bet-join]').first().isDisabled(),true);
  assert.match(await page.locator('.bet-result').textContent(),/Bote repartido: 10/);
  await page.locator('[data-bets-view="open"]').click();await page.locator('[data-market="market-0"]').waitFor();
  fail=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.getElementById('bets-feedback').textContent.includes('últimos datos'));
  assert.equal(await page.locator('.bet-card').count(),2);
  fail=false;
  for(const width of [768,390,320]){
   await page.setViewportSize({width,height:1000});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`fits ${width}`);
  }
  await page.screenshot({path:'preview/apuestas-mobile.png',fullPage:true});
  const before=writes.length;
  await page.locator('[data-bet-join]').first().click();await page.locator('#bet-join-amount').fill('100');
  await page.locator('#bet-confirm-submit').click();assert.equal(writes.length,before);
  assert.match(await page.locator('#bet-confirm-error').textContent(),/suficiente oro/);
  await page.locator('#bet-confirm-cancel').click();
  assert.deepEqual(errors,[]);
  console.log('Betting UI passed: conditional form, teams/players, numeric half-lines, gold, confirmation, create/join, 20-minute notice, retry, history, offline and mobile.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
