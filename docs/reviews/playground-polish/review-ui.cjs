const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright-core');
const axe = require('axe-core');
(async () => {
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto('http://127.0.0.1:8765');
    await page.waitForFunction(() => !document.getElementById('run').disabled);
    const reports = [];
    const audit = async (name) => {
      await page.evaluate(axe.source);
      const report = await page.evaluate(() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']}}));
      reports.push({name, violations: report.violations.map(({id, impact, nodes}) => ({id, impact, nodes: nodes.map(n => ({target:n.target, summary:n.failureSummary}))})), incomplete:report.incomplete.map(r=>r.id)});
    };
    await page.screenshot({path:'/workspace/scratch/axiom-playground-polish/desktop-ready.png',fullPage:true});
    await audit('ready');
    await page.locator('#run').click();
    await page.waitForFunction(() => !document.getElementById('run').disabled);
    console.log('After run', await page.locator('#status').innerText(), await page.locator('#diagnostic').textContent());
    await page.screenshot({path:'/workspace/scratch/axiom-playground-polish/after-axe-run.png',fullPage:true});
    assert(await page.locator('#status').evaluate(node=>node.classList.contains('status-success')), 'Run failed after axe audit');
    await audit('success');
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({width, height:1050});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
      await page.screenshot({path:`/workspace/scratch/axiom-playground-polish/result-${width}.png`,fullPage:true});
    }
    await page.locator('#candidate-details').evaluate(node=>node.open=true);
    await page.locator('#input-details').evaluate(node=>node.open=true);
    await page.locator('#run-details').evaluate(node=>node.closest('details').open=true);
    await audit('details expanded');
    await page.screenshot({path:'/workspace/scratch/axiom-playground-polish/desktop-details.png',fullPage:true});
    assert(await page.evaluate(() => document.getElementById('output-section').getBoundingClientRect().top < document.getElementById('selection-summary').getBoundingClientRect().top));
    await page.locator('#input-mode').selectOption('custom');
    await page.locator('#custom-input').fill('[not json]');
    await page.locator('#run').click();
    await audit('invalid custom input');
    await page.locator('#source').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'input-mode');
    await page.emulateMedia({forcedColors:'active',reducedMotion:'reduce'});
    await page.screenshot({path:'/workspace/scratch/axiom-playground-polish/forced-colors.png',fullPage:true});
    const result = {status: reports.every(r=>r.violations.length===0) && !errors.length ? 'passed' : 'failed', reports, errors};
    await fs.writeFile('/workspace/scratch/axiom-playground-polish/accessibility.json', JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result,null,2));
    if (result.status !== 'passed') process.exitCode=1;
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
