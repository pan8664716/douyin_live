#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音直播 m3u 增量更新器

流程：
  1. 读取 sources.txt，逐条解析来源（直播间页 / 分类页 / 纯房间号）
  2. 每个来源按三级策略抓取直播间信息：
       ① HTTP 接口（分类接口 / room enter，最快）
       ② HTTP 页面 HTML 内嵌 RSC 数据（接口被风控时仍可用，每分类约 15 个置顶房间）
       ③ 浏览器（browser_fetch.mjs，Patchright，最后兜底）
  3. 增量去重：读取现有 douyin_live.m3u 的房间号集合，
     把"新出现"的房间追加到文件末尾，已有条目保持不变

用法：
  python3 update_m3u.py             # 正常更新
  python3 update_m3u.py --dry-run   # 只打印将要新增的内容，不写文件
"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
M3U_PATH = os.path.join(BASE_DIR, 'douyin_live.m3u')
SOURCES_PATH = os.path.join(BASE_DIR, 'sources.txt')
BROWSER_SCRIPT = os.path.join(BASE_DIR, 'browser_fetch.mjs')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')

MAX_PAGES = 8            # 每个分类最多拉 8 页(15/页 ≈ 120 房间)
PAGE_SLEEP = 3.0         # 页面请求间隔，避免触发风控
SOURCE_SLEEP = 2.0       # 来源之间的间隔
BROWSER_TIMEOUT = 300    # 单个来源浏览器兜底超时(秒)


class Session:
    """带 CookieJar 的 HTTP 会话，用于 ttwid 注册与接口请求"""

    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(self, url, referer=None, accept=None, timeout=30):
        hdr = {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'}
        if accept:
            hdr['Accept'] = accept
        if referer:
            hdr['Referer'] = referer
        req = urllib.request.Request(url, headers=hdr)
        r = self.op.open(req, timeout=timeout)
        return r.status, r.read(), dict(r.headers)

    def warm(self, category_path):
        """注册正式 ttwid：访问分类页拿临时 cookie，再调 union register 升级"""
        self.get('https://live.douyin.com/categorynew/' + category_path)
        body = json.dumps({
            'region': 'cn', 'aid': 6383, 'needFid': False,
            'service': 'live.douyin.com',
            'migrate_info': {'tier': '', 'from_model': 'pc'},
        }).encode()
        hdr = {'User-Agent': UA, 'Content-Type': 'application/json',
               'Accept': 'application/json'}
        req = urllib.request.Request(
            'https://ttwid.bytedance.com/ttwid/union/register/',
            data=body, headers=hdr)
        r = self.op.open(req, timeout=30)
        return r.status


def split_category(path):
    """从分类页路径推导 partition / partition_type
    例: 4_105              -> partition=105, partition_type=4
        4_103_1_2_1_1010014 -> partition=1010014, partition_type=1
    """
    seg = [s for s in path.split('_') if s]
    if len(seg) < 2:
        raise ValueError(f'无法识别分类路径: {path}')
    return seg[-1], seg[-2]


def parse_source(line):
    """把一行来源解析为 (kind, target)
    kind: 'room' / 'category'
    """
    t = line.strip()
    m = re.match(r'https?://live\.douyin\.com/categorynew/([\d_]+)', t)
    if m:
        return 'category', m.group(1)
    m = re.match(r'https?://live\.douyin\.com/(\d+)', t)
    if m:
        return 'room', m.group(1)
    if re.fullmatch(r'\d{6,15}', t):
        return 'room', t
    raise ValueError(f'无法识别的来源: {line}')


def load_sources():
    out = []
    if not os.path.exists(SOURCES_PATH):
        raise SystemExit(f'缺少来源配置文件 {SOURCES_PATH}')
    for line in open(SOURCES_PATH, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        out.append(parse_source(line))
    if not out:
        raise SystemExit('sources.txt 中没有有效来源')
    return out


def api_params(partition, partition_type, offset, count=15):
    return {
        'aid': '6383', 'app_name': 'douyin_web', 'live_id': '1',
        'device_platform': 'web', 'language': 'zh-CN',
        'cookie_enabled': 'true', 'screen_width': '1280', 'screen_height': '720',
        'browser_language': 'zh-CN', 'browser_platform': 'Windows',
        'browser_name': 'Chrome', 'browser_version': '151.0.0.0',
        'os_name': 'Windows', 'os_version': '10',
        'count': str(count), 'offset': str(offset),
        'partition': partition, 'partition_type': partition_type, 'req_from': '2',
    }


def check_risk(headers, body, where):
    if 'bdturing-verify' in headers or not body:
        raise RuntimeError(f'触发风控({headers.get("bdturing-verify", "empty body")}) @ {where}')


def parse_category_item(it):
    """从分类接口单条记录取出 (rid, title, avatar, nickname)"""
    room = it.get('room') or {}
    owner = it.get('owner') or {}
    rid = str(it.get('web_rid') or room.get('web_rid') or room.get('webRid') or '').strip()
    if not (rid.isdigit() and 6 <= len(rid) <= 15):
        return None
    title = (room.get('title') or '').strip()
    nick = (owner.get('nickname') or owner.get('nick_name') or '').strip()
    avatar = ''
    av = it.get('avatar') or owner.get('avatar_thumb') or owner.get('avatar') or {}
    if isinstance(av, dict):
        ul = av.get('url_list') or []
        if ul:
            avatar = str(ul[0])
    elif isinstance(av, str):
        avatar = av
    return {'rid': rid, 'title': title, 'avatar': avatar, 'nickname': nick}


def http_fetch_category(sess, path):
    """① 纯 HTTP 接口拉取分类页下的直播间列表"""
    partition, ptype = split_category(path)
    rooms = []
    for page in range(MAX_PAGES):
        offset = page * 15
        url = ('https://live.douyin.com/webcast/web/partition/detail/room/v2/?'
               + urllib.parse.urlencode(api_params(partition, ptype, offset)))
        st, body, headers = sess.get(url, referer='https://live.douyin.com/categorynew/' + path)
        check_risk(headers, body, f'分类接口 p{page}')
        j = json.loads(body)
        items = (j.get('data') or {}).get('data') or []
        for it in items:
            r = parse_category_item(it)
            if r:
                rooms.append(r)
        if len(items) < 15:
            break
        time.sleep(PAGE_SLEEP)
    return rooms


def http_fetch_room(sess, rid):
    """① 纯 HTTP 接口拉取单个直播间信息（标题/主播/头像）"""
    sess.get(f'https://live.douyin.com/{rid}', referer='https://www.google.com/')
    params = {
        'aid': '6383', 'app_name': 'douyin_web', 'live_id': '1',
        'device_platform': 'web', 'language': 'zh-CN', 'enter_from': 'link_share',
        'cookie_enabled': 'true', 'screen_width': '1280', 'screen_height': '720',
        'browser_language': 'zh-CN', 'browser_platform': 'Windows',
        'browser_name': 'Chrome', 'browser_version': '151.0.0.0',
        'os_name': 'Windows', 'os_version': '10',
        'web_rid': rid, 'room_id_str': '', 'enter_source': '',
        'is_need_double_stream': 'false', 'insert_task_id': '', 'live_reason': '',
    }
    url = 'https://live.douyin.com/webcast/room/web/enter/?' + urllib.parse.urlencode(params)
    st, body, headers = sess.get(
        url, referer=f'https://live.douyin.com/{rid}',
        accept='application/json, text/plain, */*')
    check_risk(headers, body, 'enter 接口')
    j = json.loads(body)
    d0 = (j.get('data') or {}).get('data') or [None]
    if not d0 or not d0[0]:
        return []
    d = d0[0]
    user = d.get('user') or d.get('owner') or {}
    title = (d.get('title') or '').strip()
    nick = (user.get('nickname') or user.get('nick_name') or '').strip()
    avatar = ''
    av = user.get('avatar_thumb') or user.get('avatar') or {}
    if isinstance(av, dict):
        ul = av.get('url_list') or []
        if ul:
            avatar = str(ul[0])
    return [{'rid': rid, 'title': title, 'avatar': avatar, 'nickname': nick}]


def parse_page_html(html):
    """② 解析页面 HTML 内嵌的 RSC 数据（self.__pace_f.push 块）
    接口被风控时页面 GET 仍可用；分类页约 15 个置顶房间，直播间页单个
    返回 [{'rid', 'title', 'avatar', 'nickname'}]
    """
    parts = []
    for m in re.finditer(r'self\.__pace_f\.push\(\[1,"', html):
        s = m.end()
        e = html.find('"])</script>', s)
        if e < 0:
            break
        try:
            parts.append(json.loads('"' + html[s:e] + '"'))
        except Exception:
            continue
    blob = ''.join(parts)
    if not blob:
        raise RuntimeError('页面中未找到 RSC 数据')

    def extract_obj(idx):
        depth = 0
        start = idx
        for i in range(idx - 1, -1, -1):
            c = blob[i]
            if c == '}':
                depth += 1
            elif c == '{':
                if depth == 0:
                    start = i
                    break
                depth -= 1
        depth = 0
        for i in range(start, len(blob)):
            c = blob[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return start, i + 1
        return None

    rooms, seen = [], set()
    for m in re.finditer(r'"web_rid":"(\d{6,15})"', blob):
        rid = m.group(1)
        if rid in seen:
            continue
        span = extract_obj(m.start())
        if not span:
            continue
        try:
            obj = json.loads(blob[slice(*span)])
        except Exception:
            continue
        rm = obj.get('room') or obj
        owner = rm.get('owner') or obj.get('owner') or obj.get('user') or {}
        title = (rm.get('title') or '').strip()
        nick = (owner.get('nickname') or owner.get('nick_name') or '').strip()
        avatar = ''
        av = owner.get('avatar_thumb') or owner.get('avatar') or {}
        if isinstance(av, dict):
            ul = av.get('url_list') or []
            if ul:
                avatar = str(ul[0])
        elif isinstance(av, str):
            avatar = av
        rooms.append({'rid': rid, 'title': title, 'avatar': avatar, 'nickname': nick})
        seen.add(rid)
    return rooms


def http_fetch_page(kind, target, sess):
    """② 纯 HTTP 拉页面并解析 RSC 数据"""
    url = f'https://live.douyin.com/categorynew/{target}' if kind == 'category' \
        else f'https://live.douyin.com/{target}'
    referer = 'https://www.google.com/' if kind == 'room' else None
    _st, body, _headers = sess.get(url, referer=referer)
    return parse_page_html(body.decode('utf-8', 'ignore'))


def browser_fetch(kind, target):
    """③ 浏览器兜底：调用 browser_fetch.mjs（Patchright）
    返回 [{'rid', 'title', 'avatar', 'nickname'}]
    """
    url = (f'https://live.douyin.com/categorynew/{target}' if kind == 'category'
           else f'https://live.douyin.com/{target}')
    r = subprocess.run(
        ['node', BROWSER_SCRIPT, url],
        capture_output=True, text=True, timeout=BROWSER_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError('浏览器兜底失败: ' + (r.stderr.strip() or r.stdout.strip())[-300:])
    rooms = json.loads(r.stdout)
    if not isinstance(rooms, list):
        raise RuntimeError('浏览器兜底返回格式错误')
    return rooms


def fetch_source(kind, target, sess):
    """按 ①接口 -> ②页面 -> ③浏览器 三级抓取，返回 (rooms, used_method)"""
    if kind == 'category':
        try:
            rooms = http_fetch_category(sess, target)
            if rooms:
                return rooms, '①接口'
            print(f'  [①接口] {target}: 空列表, 换页面解析')
        except Exception as e:
            print(f'  [①接口] {target}: {e}')
    else:
        try:
            rooms = http_fetch_room(sess, target)
            if rooms:
                return rooms, '①接口'
            print(f'  [①接口] {target}: 未开播/空数据, 换页面解析')
        except Exception as e:
            print(f'  [①接口] {target}: {e}')
    try:
        rooms = http_fetch_page(kind, target, sess)
        if rooms:
            return rooms, '②页面'
    except Exception as e:
        print(f'  [②页面] {target}: {e}')
    rooms = browser_fetch(kind, target)
    return rooms, '③浏览器'


def read_existing_m3u():
    """解析现有 m3u：保留文件头 + 按顺序去重后的条目列表
    返回 (header, [(rid, extinf_line, url_line)])，重复 rid 只保留最先出现的一条
    """
    header = '#EXTM3U\n'
    entries = []
    seen = set()
    if os.path.exists(M3U_PATH):
        lines = open(M3U_PATH, encoding='utf-8').read().splitlines()
    else:
        lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if i == 0 and l.startswith('#EXTM3U'):
            header = l + '\n'
            i += 1
            continue
        if l.startswith('#EXTINF') and i + 1 < len(lines) and lines[i + 1].startswith('http'):
            m = re.search(r'/room/(\d+)', lines[i + 1])
            if m:
                rid = m.group(1)
                if rid not in seen:
                    seen.add(rid)
                    entries.append((rid, lines[i], lines[i + 1]))
            i += 2
            continue
        i += 1
    return header, entries, seen


def clean_text(s):
    return re.sub(r'["\r\n]', '', s or '').replace(',', '，').strip()


def render_entry(room, group_name=''):
    t = clean_text(room['title']) or clean_text(room['nickname']) or room['rid']
    logo = room.get('avatar') or ''
    if not logo.startswith('http'):
        logo = ''
    g = clean_text(group_name) if group_name else '抖音'
    return (f'#EXTINF:-1 tvg-logo="{logo}" group-title="{g}", {t}',
            f'https://douyin-m3u8.pages.dev/room/{room["rid"]}')


def main():
    dry_run = '--dry-run' in sys.argv
    sources = load_sources()
    print(f'共 {len(sources)} 个来源')

    sess = Session()
    http_ok = True
    try:
        first = sources[0][1] if sources[0][0] == 'category' else '4_105'
        st = sess.warm(first)
        print(f'ttwid 初始化完成, status={st}')
    except Exception as e:
        http_ok = False
        print(f'⚠ ttwid 初始化失败({e})，跳过 ①接口 层级')

    new_rooms = []        # 本轮新发现的房间（去重）
    seen_new = set()
    failed = []
    counts = {'①接口': 0, '②页面': 0, '③浏览器': 0}
    for kind, target in sources:
        try:
            rooms, method = fetch_source(kind, target, sess) if http_ok \
                else (http_fetch_page(kind, target, sess), '②页面')
            if not rooms and method == '②页面':
                rooms = browser_fetch(kind, target)
                method = '③浏览器'
        except Exception as e:
            failed.append(target)
            print(f'  [全部失败] {target}: {e}')
            continue
        counts[method] += 1
        print(f'  [{method}] {target}: {len(rooms)} 个')
        for r in rooms:
            if r['rid'] not in seen_new:
                seen_new.add(r['rid'])
                new_rooms.append(r)
        time.sleep(SOURCE_SLEEP)

    header, old_entries, old_seen = read_existing_m3u()
    added = [r for r in new_rooms if r['rid'] not in old_seen]

    print(f'\n抓取统计: {counts}，失败来源: {len(failed)} 个')

    if dry_run:
        print(f'[DRY-RUN] 将新增 {len(added)} 个房间：')
        for r in added[:30]:
            t = clean_text(r['title']) or clean_text(r['nickname']) or r['rid']
            print(f'  {r["rid"]}  {t[:40]}')
        if len(added) > 30:
            print(f'  ... 等共 {len(added)} 个')
        return 0

    if not added:
        print(f'没有新增房间（共 {len(old_entries)} 条已有，本轮发现 {len(new_rooms)} 个均已在列表）')
        return 0 if not failed else 1

    lines = []
    for _rid, extinf, url in old_entries:
        lines.append(extinf)
        lines.append(url)
    for r in added:
        extinf, url = render_entry(r)
        lines.append(extinf)
        lines.append(url)
    with open(M3U_PATH, 'w', encoding='utf-8') as f:
        f.write(header + '\n'.join(lines) + '\n')

    print(f'完成: 新增 {len(added)} 个房间, 列表现有 {len(old_entries) + len(added)} 条')
    for r in added[:10]:
        print(f'  + {r["rid"]}  {(clean_text(r["title"]) or clean_text(r["nickname"]))[:40]}')
    if len(added) > 10:
        print(f'  ... 其余 {len(added) - 10} 条略')
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
