import { chromium } from 'patchright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36';
let browser;
try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
catch { browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
try {
  const ctx = await browser.newContext({ userAgent: UA, locale: 'zh-CN' });
  const page = await ctx.newPage();
  let capUrl = '', capHeaders = null, capBody = null;
  page.on('request', (req) => {
    if (req.url().includes('partition/detail/room/v2')) {
      capUrl = req.url();
      capHeaders = req.headers();
    }
  });
  page.on('response', async (res) => {
    if (res.url().includes('partition/detail/room/v2')) {
      try { capBody = await res.text(); } catch {}
    }
  });
  await page.goto('https://live.douyin.com/categorynew/4_103_1_2_1_1010014', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(10000);

  const cookies = await ctx.cookies();
  const cj = {};
  for (const c of cookies) cj[c.name] = c.value;
  console.log('=== cookies ===');
  console.log(JSON.stringify(cj, null, 1));

  const storage = await page.evaluate(() => {
    const out = { local: {}, session: {} };
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      out.local[k] = String(localStorage.getItem(k)).slice(0, 120);
    }
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      out.session[k] = String(sessionStorage.getItem(k)).slice(0, 120);
    }
    return out;
  });
  console.log('=== localStorage ===');
  console.log(JSON.stringify(storage.local, null, 1));
  console.log('=== sessionStorage ===');
  console.log(JSON.stringify(storage.session, null, 1));
  console.log('=== captured URL ===');
  console.log(capUrl ? capUrl.slice(0, 200) : 'NONE');
  console.log('=== captured request headers (key) ===');
  console.log(capHeaders ? JSON.stringify(Object.keys(capHeaders)) : 'NONE');
  console.log('=== captured a_bogus header ===');
  console.log(capHeaders ? JSON.stringify({ 'a-bogus': (capHeaders['a-bogus']||'').slice(0,80), 'x-bogus': (capHeaders['x-bogus']||'').slice(0,80), msToken: (capHeaders['ms-token']||'').slice(0,40), cookie: (capHeaders['cookie']||'').slice(0,200) }) : '');
  console.log('=== response body head ===');
  console.log(capBody ? capBody.slice(0, 120) : 'NONE');
} finally { await browser.close(); }
