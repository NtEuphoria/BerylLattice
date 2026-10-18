const assert = require('node:assert/strict');
const {chromium} = require('/opt/codex/cua_node/lib/node_modules/playwright-core');
(async () => {
 const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const page = await browser.newPage();
  await page.clock.install();
  let workers = 0;
  await page.route('**/worker.js', async route => {
   workers++;
   if(workers !== 1) return route.continue();
   const response = await route.fetch();
   const source = await response.text();
   // Fault injection suppresses only a run response; examples boot the real Python compiler.
   await route.fulfill({response, body:source + '\nconst handler=self.onmessage; self.onmessage=e=>{if(e.data.method!=="run")handler(e);};'});
  });
  await page.goto('http://127.0.0.1:8877/static-site-reviewed/');
  await page.waitForFunction(()=>document.querySelector('#source').value.length>0);
  await page.evaluate(async()=>{
   const transport=await import('./transport.js');
   const request={source:document.querySelector('#source').value,input_mode:'ramp'};
   window.transportTest={transport,request};
   window.failedRun=transport.runDemo(request).then(()=>({unexpected:true}),error=>({error:error.message}));
  });
  await page.clock.fastForward(16000);
  const failure=await page.evaluate(()=>window.failedRun);
  assert.match(failure.error,/time limit/);
  const result=await page.evaluate(()=>window.transportTest.transport.runDemo(window.transportTest.request));
  assert.equal(result.status,'success');
  assert.equal(result.output[0],186);
  assert.equal(workers,2);
  console.log(JSON.stringify({status:'passed',checks:['suppressed Worker response expires','timeout terminates old Worker','retry boots fresh real Python Worker','retry executes matching result'],workers}));
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
