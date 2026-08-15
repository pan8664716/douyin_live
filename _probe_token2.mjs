import { chromium } from 'patchright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36';
let browser;
try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
catch { browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
try {
  const ctx = await browser.newContext({ userAgent: UA, locale: 'zh-CN' });
  const page = await ctx.newPage();
  let capUrl = '', capHeaders = null;
  page.on('request', (req) => {
    if (req.url().includes('partition/detail/room/v2')) {
      capUrl = req.url();
      capHeaders = req.headers();
    }
  });
  await page.goto('https://live.douyin.com/categorynew/4_103_1_2_1_1010014', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  const u = new URL(capUrl);
  console.log('path:', u.pathname);
  console.log('query keys:', [...u.searchParams.keys()].join(','));
  console.log('a_bogus param:', u.searchParams.get('a_bogus') ? 'YES len=' + u.searchParams.get('a_bogus').length : 'NONE');
  console.log('msToken param:', u.searchParams.get('msToken') ? 'YES len=' + u.searchParams.get('msToken').length : 'NONE');
  console.log('X-Bogus?', u.searchParams.get('X-Bogus') ? 'YES' : 'NONE');
  console.log('full URL:', capUrl);
} finally { await browser.close(); }
