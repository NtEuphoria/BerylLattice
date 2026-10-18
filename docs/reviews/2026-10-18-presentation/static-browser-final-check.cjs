const {chromium} = require('/opt/codex/cua_node/lib/node_modules/playwright-core');
(async()=>{
 const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const page = await browser.newPage();
 const errors=[]; const requests=[];
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>requests.push(r.url()));
 await page.route('**/worker.js', async route => {
  const response = await route.fetch();
  await route.fulfill({response, headers: {...response.headers(), 'content-security-policy': "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; worker-src 'self'"}});
 });
 await page.goto('http://127.0.0.1:8877/axiom-playground-site/');
 await page.waitForFunction(() => document.querySelector('#source').value.length > 0, {timeout:65000});
 const results=await page.evaluate(async()=>{
  const transport=await import('./transport.js');
  const loaded=await transport.getExamples();
  const rows=[];
  for(const example of loaded.examples){
   const result=await transport.runDemo({source:example.source,input_mode:'ramp'});
   rows.push({id:example.id,status:result.status,selected:result.selected,output:result.output,comparison:result.comparison});
  }
  const malformed=await transport.runDemo({source:'module bad;',input_mode:'ramp'});
  return {rows,malformed};
 });
 console.log(JSON.stringify({results,errors,requests},null,2));
 await browser.close();
 if(errors.length||results.rows.some(r=>r.status!=='success')||results.malformed.status!=='error')process.exit(1);
})().catch(error=>{console.error(error);process.exit(1);});
