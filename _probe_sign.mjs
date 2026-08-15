import { chromium } from 'patchright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36';
let browser;
try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
catch { browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
try {
  const ctx = await browser.newContext({ userAgent: UA, locale: 'zh-CN' });
  const page = await ctx.newPage();
  await page.goto('https://live.douyin.com/categorynew/4_103_1_2_1_1010014', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  const g = await page.evaluate(() => {
    const out = {};
    for (const k of Object.keys(window)) {
      if (/sign|bogus|acrawler|byted|secsdk|msTK|token|helper/i.test(k)) {
        const v = window[k];
        out[k] = typeof v;
      }
    }
    return out;
  });
  console.log('globals:', JSON.stringify(g, null, 1));
  // 探测有名的签名入口
  const t = await page.evaluate(() => {
    const res = {};
    const checks = ['byted_acrawler', '_webmsxyw', 'byted__acrawler', 'window._signature', 'webmssdk'];
    for (const c of checks) {
      const v = eval(c);
      res[c] = v ? (typeof v === 'object' ? Object.keys(v).slice(0,10).join(',') : typeof v) : 'undefined';
    }
    return res;
  });
  console.log('sign entry checks:', JSON.stringify(t, null, 1));
} finally { await browser.close(); }
