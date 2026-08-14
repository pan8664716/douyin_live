#!/usr/bin/env node
/**
 * 浏览器兜底抓取（Patchright）
 *
 * 纯 HTTP 拿不到数据（风控等）时，用真实浏览器打开直播间/分类页，
 * 让页面里的 webmssdk 完成 ttwid / msToken 注册并自动给接口请求补 a_bogus 签名。
 *
 * 用法:
 *   node browser_fetch.mjs https://live.douyin.com/745350622378
 *   node browser_fetch.mjs https://live.douyin.com/categorynew/4_105
 * 环境变量:
 *   HEADLESS=0  有头模式（个别情况更稳）
 *
 * 输出: JSON 数组 [{rid, title, avatar, nickname}]
 */
import { chromium } from 'patchright';

const TARGET = process.argv[2]?.trim();
if (!TARGET) {
  console.error('用法: node browser_fetch.mjs <直播间或分类页URL>');
  process.exit(2);
}

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36';

let browser;
try {
  // 本机有系统 Chrome 时优先使用；CI 上没有则走下面的 Patchright 自带 Chromium
  browser = await chromium.launch({
    channel: 'chrome',
    headless: process.env.HEADLESS !== '0',
  });
} catch {
  browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox'],
  });
}

try {
  const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN' });
  const page = await context.newPage();

  const category = TARGET.match(/categorynew\/([\d_]+)/);
  const room = TARGET.match(/live\.douyin\.com\/(\d+)/);
  if (!category && !room) {
    console.error('无法识别的 URL: ' + TARGET);
    process.exit(2);
  }

  console.error('[browser] 打开 ' + TARGET + ' ...');
  await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  // 等 webmssdk 初始化、种下 ttwid / msToken
  await page.waitForTimeout(8000);

  let rooms;
  if (category) {
    rooms = await page.evaluate(async ({ path, maxPages }) => {
      const nav = navigator;
      const seg = path.split('_');
      const partition = seg[seg.length - 1];
      const partitionType = seg.length >= 2 ? seg[seg.length - 2] : '4';
      const base = {
        aid: '6383', app_name: 'douyin_web', live_id: '1',
        device_platform: 'web', language: 'zh-CN',
        cookie_enabled: String(nav.cookieEnabled),
        screen_width: String(screen.width), screen_height: String(screen.height),
        browser_language: nav.language, browser_platform: nav.platform,
        browser_name: 'Chrome',
        browser_version: (nav.userAgent.match(/Chrome\/(\S+)/) || [])[1] || '151.0.0.0',
        os_name: 'Windows', os_version: '10',
        count: '15', partition, partition_type: partitionType, req_from: '2',
      };
      const out = [];
      for (let pageNo = 0; pageNo < maxPages; pageNo++) {
        const qs = Object.entries({ ...base, offset: String(pageNo * 15) })
          .map(([k, v]) => `${k}=${encodeURIComponent(v ?? '')}`)
          .join('&');
        const res = await fetch(
          `https://live.douyin.com/webcast/web/partition/detail/room/v2/?${qs}`,
          { headers: { accept: 'application/json' } });
        const txt = await res.text();
        let j;
        try { j = JSON.parse(txt); }
        catch { throw new Error('分类接口返回非JSON(status=' + res.status + '): ' + txt.slice(0, 120)); }
        const items = j?.data?.data || [];
        for (const it of items) {
          const roomItem = it.room || {};
          const owner = it.owner || {};
          const rid = String(it.web_rid || roomItem.web_rid || roomItem.webRid || '').trim();
          if (!/^\d{6,15}$/.test(rid)) continue;
          const title = (roomItem.title || '').trim();
          const nickname = (owner.nickname || owner.nick_name || '').trim();
          let avatar = '';
          const av = it.avatar || owner.avatar_thumb || owner.avatar || {};
          if (av && typeof av === 'object') {
            const ul = av.url_list || [];
            if (ul.length) avatar = String(ul[0]);
          } else if (typeof av === 'string') {
            avatar = av;
          }
          out.push({ rid, title, avatar, nickname });
        }
        if (items.length < 15) break;
        await new Promise((r) => setTimeout(r, 1000));
      }
      return out;
    }, { path: category[1], maxPages: 8 });
  } else {
    // 直播间：页面主世界调 room/web/enter，webmssdk 自动补 a_bogus 签名
    rooms = await page.evaluate(async (rid) => {
      const html = document.documentElement.innerHTML;
      const m1 = html.match(/"roomId":"(\d+)"/);
      const m2 = html.match(/roomId&quot;:&quot;(\d+)&quot;/);
      const roomIdStr = (m1 && m1[1]) || (m2 && m2[1]) || '';

      const nav = navigator;
      const params = {
        aid: '6383', app_name: 'douyin_web', live_id: '1',
        device_platform: 'web', language: 'zh-CN', enter_from: 'link_share',
        cookie_enabled: String(nav.cookieEnabled),
        screen_width: String(screen.width), screen_height: String(screen.height),
        browser_language: nav.language, browser_platform: nav.platform,
        browser_name: 'Chrome',
        browser_version: (nav.userAgent.match(/Chrome\/(\S+)/) || [])[1] || '151.0.0.0',
        os_name: 'Windows', os_version: '10',
        web_rid: rid, room_id_str: roomIdStr,
        enter_source: '', is_need_double_stream: 'false',
        insert_task_id: '', live_reason: '',
      };
      const qs = Object.entries(params)
        .map(([k, v]) => `${k}=${encodeURIComponent(v ?? '')}`)
        .join('&');
      const res = await fetch(`https://live.douyin.com/webcast/room/web/enter/?${qs}`, {
        headers: { accept: 'application/json' },
      });
      const txt = await res.text();
      let j;
      try { j = JSON.parse(txt); }
      catch { throw new Error('enter接口返回非JSON(status=' + res.status + '): ' + txt.slice(0, 120)); }
      const d = j?.data?.data?.[0];
      if (!d) return [];
      const user = d.user || d.owner || {};
      let avatar = '';
      const av = user.avatar_thumb || user.avatar || {};
      if (av && typeof av === 'object') {
        const ul = av.url_list || [];
        if (ul.length) avatar = String(ul[0]);
      } else if (typeof av === 'string') {
        avatar = av;
      }
      return [{
        rid,
        title: d.title || '',
        avatar,
        nickname: user.nickname || user.nick_name || '',
      }];
    }, room[1]);
  }

  console.log(JSON.stringify(rooms));
  if (!rooms || rooms.length === 0) {
    console.error('[browser] 未取到任何房间数据');
    process.exit(1);
  }
} finally {
  await browser.close();
}
