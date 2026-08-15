import { chromium } from 'patchright';
import { writeFileSync } from 'fs';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36';
let browser;
try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
catch { browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
try {
  const ctx = await browser.newContext({ userAgent: UA, locale: 'zh-CN' });
  const page = await ctx.newPage();
  const seen = [];
  page.on('request', (req) => {
    if (req.url().includes('partition/detail/room/v2')) {
      seen.push({ url: req.url(), headers: req.headers() });
    }
  });
  await page.goto('https://live.douyin.com/categorynew/4_103_1_2_1_1010014', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  const cookies = await ctx.cookies();
  const data = { url: seen[seen.length-1].url, headers: seen[seen.length-1].headers,
                 cookie: cookies.map(c => `${c.name}=${c.value}`).join('; ') };
  writeFileSync('/tmp/replay.json', JSON.stringify(data));
  console.log('saved. urls captured:', seen.length);
  console.log('url:', data.url.slice(0, 220));
} finally { await browser.close(); }
