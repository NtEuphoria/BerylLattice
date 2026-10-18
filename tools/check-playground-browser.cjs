#!/usr/bin/env node
/* Optional browser verification. PLAYWRIGHT_MODULE may point to a local install. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const address = process.argv[2];
  if (!address || !/^https?:\/\//.test(address)) throw new Error('Supply the test server URL');
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    proxy: process.env.PLAYWRIGHT_PROXY ? { server: process.env.PLAYWRIGHT_PROXY } : undefined,
    headless: true,
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(address);
    await page.waitForFunction(() => !document.querySelector('#run').disabled, null, { timeout: 120000 });
    const original = await page.locator('#source').inputValue();
    const reset = async () => {
      await page.getByRole('button', { name: 'Reset example', exact: true }).focus();
      await page.keyboard.press('Space');
      assert.equal(await page.locator('#source').inputValue(), original);
      assert.equal(await page.locator('#input-mode').inputValue(), 'ramp');
      assert.equal(await page.locator('#custom-input').inputValue(), '');
      assert.equal(await page.locator('#custom-input-area').isHidden(), true);
      assert.equal(await page.locator('#result-content').isHidden(), true);
      assert.equal(await page.locator('#diagnostic').isHidden(), true);
      assert.equal(await page.locator('#download').isDisabled(), true);
      assert.equal(await page.locator('#run').isEnabled(), true);
      assert.equal(await page.locator('#status-title').innerText(), 'Ready to run');
      assert.equal(await page.locator('#examples button[aria-pressed="true"]').innerText(), 'Fewer calculations');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'reset');
    };
    const run = async () => {
      await page.locator('#run').click();
      await page.waitForFunction(() => !document.querySelector('#run').disabled
        && document.querySelector('#status-title').textContent !== 'Ready when you are', null, { timeout: 30000 });
    };
    await run();
    assert.match(await page.locator('#selected-name').innerText(), /row/i);
    assert.match(await page.locator('#selected-workspace').innerText(), /64/);
    assert.match(await page.locator('#selected-multiplications').innerText(), /48/);
    assert.equal(await page.locator('#output-grid td').count(), 35);
    assert.equal(await page.locator('#output-grid td').first().innerText(), '186');
    assert.equal(await page.locator('#output-grid td').last().innerText(), '7634');
    assert.match(await page.locator('#comparison-label').innerText(), /35/);

    const downloadPromise = page.waitForEvent('download');
    await page.locator('#download').click();
    const download = await downloadPromise;
    const report = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
    const result = report.result || report;
    assert.equal(result.status, 'success');
    assert.equal(result.schema_version, 2);
    assert.equal(result.search.policy_id, 'ranked-proof-v1');
    assert.equal(result.attempts[0].state, 'not_checked_worse_rank');
    assert.equal(result.attempts[0].eligible, null);
    assert.ok(result.lowering.hint_digest);
    assert.equal(result.backend, 'checked-plan-wasm-v2');
    assert.equal(result.timings.reused_compilation, false);
    assert.ok(result.timings.compilation_ms > 0);
    assert.ok(result.timings.execution_ms >= 0);
    assert.ok(result.timings.verification_ms >= 0);
    assert.equal(result.selected.plan_id, 'rows2-v1');
    assert.equal(result.comparison.matches, true);
    await reset();

    await page.locator('#source').fill(original.replace('<= 64', '<= 0'));
    assert.equal(await page.locator('#download').isDisabled(), true);
    assert.equal(await page.locator('#result-content').isHidden(), true);
    await run();
    assert.match(await page.locator('#selected-name').innerText(), /inline/i);
    assert.match(await page.locator('#selected-multiplications').innerText(), /140/);
    assert.equal(await page.locator('#output-grid td').first().innerText(), '186');

    await page.locator('#input-mode').selectOption('zeros');
    await run();
    assert.deepEqual(await page.locator('#output-grid td').allTextContents(), Array(35).fill('4'));
    const repeatedDownloadPromise = page.waitForEvent('download');
    await page.locator('#download').click();
    const repeatedReport = JSON.parse(await fs.readFile(await (await repeatedDownloadPromise).path(), 'utf8'));
    const repeated = repeatedReport.result || repeatedReport;
    assert.equal(repeated.timings.reused_compilation, true);
    assert.equal(repeated.timings.compilation_ms, 0);
    assert.ok(repeated.timings.initial_compilation_ms > 0);
    await page.locator('#source').fill(original.replace('prefer multiplication_ops;', 'prefer plan_workspace_bytes;'));
    await run();
    assert.match(await page.locator('#selected-name').innerText(), /inline/i);
    assert.equal(await page.locator('#selected-workspace').innerText(), '0 B');
    await page.locator('#source').fill(original.replace('shape H = 5', 'shape H = 32').replace('shape W = 7', 'shape W = 32'));
    await run();
    assert.equal(await page.locator('#diagnostic').isVisible(), true);
    assert.equal(await page.locator('#result-content').isHidden(), true);
    await page.locator('#source').fill(original);
    await page.locator('#input-mode').selectOption('custom');
    await page.locator('#custom-input').fill(JSON.stringify([1024, ...Array(47).fill(0)]));
    await run();
    assert.match(await page.locator('#status-title').innerText(), /input|precondition|reject/i);
    assert.equal(await page.locator('#output-grid td').count(), 35);
    assert.deepEqual(await page.locator('#output-grid td').allTextContents(), Array(35).fill('-9'));

    await reset();
    await page.locator('#input-mode').selectOption('custom');
    await page.locator('#custom-input').fill('[');
    await run();
    assert.equal(await page.locator('#diagnostic').isVisible(), true);
    await reset();
    await run();
    assert.equal(await page.locator('#output-grid td').first().innerText(), '186');
    assert.equal(await page.locator('#output-grid td').last().innerText(), '7634');
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1050 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true,
        `Unexpected page overflow at ${width}px`);
    }
    await page.locator('#source').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'input-mode');
    const lifecycle = await page.evaluate(async source => {
      const transport = await import('./transport.js');
      const large = source.replace('H = 5;', 'H = 15;').replace('W = 7;', 'W = 15;');
      const controller = new AbortController();
      const pending = transport.prepareDemo({source: large, input_mode: 'ramp'}, {signal: controller.signal});
      setTimeout(() => controller.abort(), 0);
      let cancelled = false;
      try { await pending; } catch (error) { cancelled = error.name === 'AbortError'; }
      const recovered = await transport.runDemo({source, input_mode: 'zeros'});
      const boundary = await transport.runDemo({source: large, input_mode: 'custom',
        inputs: [...Array(255).fill(0), 1024]});
      return {cancelled, recovered, boundary};
    }, original);
    assert.equal(lifecycle.cancelled, true);
    assert.equal(lifecycle.recovered.status, 'success');
    assert.equal(lifecycle.recovered.timings.reused_compilation, false);
    assert.deepEqual(lifecycle.recovered.output, Array(35).fill(4));
    assert.equal(lifecycle.boundary.status, 'input_precondition_failed');
    assert.equal(lifecycle.boundary.first_bad_index, 255);
    assert.deepEqual(lifecycle.boundary.output, Array(225).fill(-9));
    if (process.env.AXIOM_SCREENSHOT) await page.screenshot({ path: process.env.AXIOM_SCREENSHOT, fullPage: true });
    await page.goto(new URL('benchmarks.html', address).href);
    await page.waitForFunction(() => document.querySelectorAll('#native-rows tr').length === 6, null, {timeout: 30000});
    assert.match(await page.locator('#comparison-compilation').innerText(), /excluded from execution/);
    await page.locator('#benchmark-run').click();
    await page.waitForFunction(() => !document.querySelector('#benchmark-run').disabled, null, {timeout: 120000});
    assert.match(await page.locator('#benchmark-status').innerText(), /^Complete\./);
    assert.equal(await page.locator('#browser-rows tr').count(), 3);
    assert.equal(await page.locator('#browser-rows td').count(), 12);
    assert.match(await page.locator('#browser-rows').innerText(), /All values verified/);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'passed', browser: 'chromium', address,
      checks: ['real rows2 execution', 'report download', 'cap changes selection', 'stale result cleared',
        'zero input', 'objective changes selection', '256-input final invalid boundary', 'real worker cancellation and recovery', 'unsupported shape', 'precondition rejection', 'keyboard reset after report and diagnostic',
        'reset restores defaults and reruns', 'responsive widths', 'keyboard navigation',
        'compiled reuse with visible cold cost', 'saved native comparison', 'compiled browser benchmark', 'no page errors'] }));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
