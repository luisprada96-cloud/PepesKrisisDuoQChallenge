const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>sessionStorage.setItem('pepes_player_token','test-team-session'));
  const first='2026-10-15',second='2026-10-26';
  let currentWeek=first, writes=0, failArchive=false;
  const period={
   [first]:{startsAt:1792080000,endsAt:1792969200},
   [second]:{startsAt:1792969200,endsAt:1793574000}
  };
  const posts={
   [first]:[{id:'first-clip',title:'La jugada de la primera ronda',slug:'FirstClip',url:'https://clips.twitch.tv/FirstClip',team:'Equipo A',initials:'EA',scene:1,createdAt:1792300000,votes:5,liked:true}],
   [second]:[{id:'second-clip',title:'La segunda ronda',slug:'SecondClip',url:'https://clips.twitch.tv/SecondClip',team:'Equipo A',initials:'EA',scene:1,createdAt:1793000000,votes:0,liked:false}]
  };
  const errors=[];
  const allowed=new Set(['clips.html','clips.css','clips.js','styles.css','navigation.js','data.js','alerts.js']);
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!=='http://clips.test')return route.abort();
   if(url.pathname==='/api/clips'||url.pathname==='/api/clips/like'){
    if(request.method()!=='GET')writes++;
    const week=url.searchParams.get('week')||currentWeek;
    const archived=week!==currentWeek;
    if(failArchive&&archived)return route.abort();
    const result={week,currentWeek,archived,preview:false,clips:posts[week],...period[week],
     weeks:(currentWeek===first?[first]:[second,first]).map(key=>({week:key,...period[key],archived:key!==currentWeek})),
     teams:[{id:'a',name:'Equipo A'}],voting:{teamId:'a',teamName:'Equipo A'},
     weeklyReward:{closed:archived,closesAt:period[week].endsAt-60,award:archived?{status:'AWARDED',shells:3,teamName:'Equipo A',title:'La jugada de la primera ronda',votes:5}:null}};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(result)});
   }
   const filename=url.pathname.slice(1);
   if(!allowed.has(filename))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,filename))});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://clips.test/clips.html');
  await page.locator('[data-clip-id="first-clip"]').waitFor();
  assert.match(await page.locator('#clips-week').textContent(),/15 oct.*25 oct/);
  assert.match(await page.locator('#clips-close-label').textContent(),/25 de octubre.*23:59/);
  assert.equal(await page.locator('[data-vote]').isDisabled(),false);
  await page.locator('[data-seen]').click();
  currentWeek=second;
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.locator('[data-clip-id="second-clip"]').waitFor();
  assert.equal(await page.locator('#clips-week-select option').count(),2);
  failArchive=true;
  await page.selectOption('#clips-week-select',first);
  await page.waitForFunction(()=>!document.getElementById('clips-week-select').disabled);
  assert.equal(await page.locator('#clips-week-select').inputValue(),second,'failed archive reads keep the previous selection');
  assert.equal(await page.locator('[data-clip-id="second-clip"]').count(),1);
  assert.match(await page.locator('#clips-feedback').textContent(),/No se pudieron actualizar/);
  failArchive=false;
  await page.selectOption('#clips-week-select',first);
  await page.locator('[data-clip-id="first-clip"]').waitFor();
  assert.match(await page.locator('#clips-archive-status').textContent(),/archivada.*No admite votos ni publicaciones/);
  assert.equal(await page.locator('[data-vote]').isDisabled(),true);
  assert.equal(await page.locator('#clips-publish').isDisabled(),true);
  assert.equal(await page.locator('#clips-form button[type="submit"]').isDisabled(),true);
  assert.equal(await page.locator('[data-seen]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('.clip-open').first().getAttribute('href'),'https://clips.twitch.tv/FirstClip');
  assert.match(await page.locator('#clips-reward-status').textContent(),/ha ganado.*3 pepazos/);
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForTimeout(200);
  assert.equal(await page.locator('#clips-week-select').inputValue(),first,'poll keeps the selected archive');
  assert.match(page.url(),/week=2026-10-15/);
  await page.reload();await page.locator('[data-clip-id="first-clip"]').waitFor();
  assert.equal(await page.locator('[data-vote]').isDisabled(),true,'deep link remains read-only after reload');
  fs.mkdirSync('preview',{recursive:true});
  await page.screenshot({path:'preview/clips-archive-desktop.png',fullPage:true});
  for(const width of [390,320]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  }
  await page.screenshot({path:'preview/clips-archive-mobile.png',fullPage:true});
  await page.selectOption('#clips-week-select',second);
  await page.locator('[data-clip-id="second-clip"]').waitFor();
  assert.equal(await page.locator('#clips-publish').isDisabled(),false);
  assert.equal(await page.locator('[data-vote]').isDisabled(),false);
  assert.equal(writes,0,'browsing and local seen marks never mutate a round');
  assert.deepEqual(errors,[]);
  console.log('Clip archive UI passed: opening dates, selection, deep links, read-only controls, polling, seen marks, mobile and return to current round.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
