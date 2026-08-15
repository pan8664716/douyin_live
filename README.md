# 抖音直播 m3u 增量更新（GitHub Actions）

每 **1 小时**自动抓取你配置的来源地址，把直播信息增量去重后写入 `douyin_live.m3u`。

- 播放地址：优先使用抓取时提取的 **CDN 直链**（`douyincdn.com` 的 m3u8，
  分类页/enter 接口自带 `stream_url`，无需逐个房间请求）
  - 本轮抓到的在播房间写 CDN 直链（带签名有效期，每小时自动刷新）
  - 未在本轮抓到、仅保留的历史房间回退 `https://douyin-m3u8.pages.dev/room/<房间号>`
    （由 Cloudflare Pages Worker 动态解析，主播下播再上播仍可播放）
- 增量合并规则：
  - 本轮抓到的房间**全部插到列表最前面**（按来源顺序）
  - 旧列表中与本轮重复的条目**自动删除**（全局去重，每个房间号只出现一次）
  - 本轮未抓到的历史条目按原顺序保留在后面
  - `group-title` 自动使用来源对应的**类目名**（英雄联盟/舞蹈/音乐…，从分类页动态提取）
- 抓取策略（每来源三级自动降级）：
  1. **HTTP 接口**（默认主路径，全程无需浏览器）：分类接口 URL 带 `a_bogus` 参数即可放行
     （服务端只校验参数存在、不校验取值，固定值实测 60/60 全通过），每分类拉 14 页约 210 房间；
     直播间用 `room/web/enter`。13 来源 4 线程并发实测约 1 分钟
  2. **浏览器**（接口风控时的兜底：Patchright 打开分类页**滚动加载**并拦截签名接口响应，
     单分类约 200 房间；直播间页内调 enter）
  3. **HTTP 页面解析**（前两级失败时兜底，从内嵌 RSC 数据取约 15 个置顶房间）

## 文件说明

| 文件 | 说明 |
|---|---|
| `sources.txt` | **来源配置**：每行一个直播间页或分类页地址，改成你自己的即可 |
| `update_m3u.py` | 主脚本：解析来源 → 三级抓取 → 提取 CDN 直链 → 本轮房间置顶 + 全局去重 + 类目名分组 |
| `browser_fetch.mjs` | 浏览器兜底抓取（Patchright）：仅接口风控时启用，分类页滚动+拦截签名响应 |
| `douyin_live.m3u` | 播放列表：本轮房间置顶、重复自动删除、类目名分组 |
| `.github/workflows/update-m3u.yml` | 每小时定时 + 手动触发的工作流 |

## 本地运行

```bash
# 1) 安装浏览器兜底依赖（可选，纯 HTTP 方案不需要）
npm install && npx patchright install chromium

# 2) 先试跑（不写文件）
python3 update_m3u.py --dry-run

# 3) 正式更新
python3 update_m3u.py
```

> 本机有系统 Chrome 时浏览器直接使用系统 Chrome；GitHub 运行器会自动安装 Patchright 自带 Chromium。

## 部署到 GitHub

1. 在 [github.com/new](https://github.com/new) 新建公开仓库（推荐公开，Actions 分钟数免费无限；私有仓库每月仅 2000 分钟免费额度，本任务每小时跑一次约 5 分钟，可能超限）
2. 推送本目录：

```bash
cd /Users/star/Downloads/douyin-actions
git init -b main
git add -A && git commit -m "init: 抖音直播 m3u 增量更新"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

3. 推送后立即手动触发一次验证：仓库页面 → **Actions** → **增量更新 m3u** → **Run workflow**
4. 之后会自动每小时运行（北京时间每个整点）

## 修改抓取来源

编辑 `sources.txt`，支持三类写法：

```
# 直播间页
https://live.douyin.com/745350622378

# 纯房间号
745350622378

# 分类页（拉的是一整个分类下正在直播的房间）
https://live.douyin.com/categorynew/4_105
https://live.douyin.com/categorynew/4_103_1_2_1_1010014
```

## 播放列表使用

- 直接下载仓库里的 `douyin_live.m3u` 导入 PotPlayer / VLC 等
- 或在线获取实时版：`https://douyin-m3u8.pages.dev/api/list.m3u`

## 注意事项

- m3u 为**增量累积**：本轮房间排最前、重复自动删除、未抓到的历史保留；本轮在播房间写 CDN 直链（有签名时效，每小时刷新一次），历史房间用 pages.dev 动态地址兜底
- 抖音对高频请求有风控（`bdturing-verify`），脚本已做请求间隔 + 分页限量 + 单来源失败自动跳过
- GitHub 数据中心 IP 可能触发风控，此时自动走浏览器方案；连续多次"无新增"请查看 Actions 日志确认抓取是否正常
