# Verifying a prototype

## Layers (cheapest first)

1. `node --check <file>` for every script (catches syntax before a browser run).
2. `test/check.mjs`: core vs real source, no browser. Useful checks:
   - every edge endpoint exists in the index
   - sampled import `file:line` lands on an `import|export` line; sampled call line contains the callee name (allow ~2% for multi-line calls)
   - rule outputs (drift etc.) each point at a line that really imports the target
   - caps never exceeded, tests excluded when policy says so, stable group order
   - agent-facing text under its byte/char budget (report max + median)
   - generated blocks regenerate byte-identical
3. `test/smoke.mjs`: headless browser over `file://.../index.html`.
4. Screenshot review with vision.

## Smoke harness pattern (playwright-core, no test runner)

```js
const pw = require(process.env.X_PW || 'playwright-core');
// bundled browser builds can lag the playwright-core version: prefer an installed Chrome
const chrome = [process.env.X_CHROME, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p => p && fs.existsSync(p));
const browser = await pw.chromium.launch(chrome ? { executablePath: chrome, headless: true } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => m.type() === 'error' && errors.push(m.text()));
await page.goto(fileUrl); await page.waitForFunction(() => !!window.__app);
// drive state through the app's own router, then assert on rendered text
await page.evaluate(() => window.__app.go({ tab: 'panel', step: 'end', host: 'hermes' }));
```

- Drive deep states with `window.__app.go(...)`; drive real interactions (click, keyboard, select) for the flows the user will actually do.
- Last check: `errors.length === 0`. Print PASS/FAIL per check + count; exit non-zero on failure.
- Write screenshots to the scratch dir, not the repo.
- When a browser test fails because of the browser binary, fix the launch (executablePath / env var); don't drop the browser layer.

## Screenshot review checklist

- lines/arrows hidden behind boxes or crossing labels
- labels truncated where the full name matters (list rows need ellipsis on the name and `flex-shrink:0` on the right column)
- badges on every row (anchor too broad)
- empty-state text wrong for the level ("uses nothing" on a symbol view)
- toasts covering content in screenshots (transient, ignore)
