# 抖音直播 m3u 增量更新（GitHub Actions）

每 **4 小时**自动抓取你配置的来源地址，把直播信息增量去重后写入 `douyin_live.m3u`。

- 播放地址格式：`https://douyin-m3u8.pages.dev/room/<房间号>`
  （由 Cloudflare Pages Worker 实时解析最新 m3u8，主播下播返回 404，无需更新列表）
- 抓取策略（每来源三级自动降级）：
  1. **HTTP 接口**（分类接口 / room enter，最快，约 120 房间/分类）
  2. **HTTP 页面解析**（接口被风控时页面仍可用，从内嵌 RSC 数据取约 15 个置顶房间）
  3. **浏览器**（Patchright + Chromium，页面内 webmssdk 自动签名，最后兜底）

## 文件说明

| 文件 | 说明 |
|---|---|
| `sources.txt` | **来源配置**：每行一个直播间页或分类页地址，改成你自己的即可 |
| `update_m3u.py` | 主脚本：解析来源 → 三级抓取（接口/页面/浏览器）→ 增量去重，新房间插到列表最前 |
| `browser_fetch.mjs` | 浏览器兜底（Patchright），仅前两级都失败时被调用 |
| `douyin_live.m3u` | 生成的播放列表，新房间每次插到列表**最前面** |
| `.github/workflows/update-m3u.yml` | 每 4 小时定时 + 手动触发的工作流 |

## 本地运行

```bash
# 1) 安装浏览器兜底依赖（可选，纯 HTTP 方案不需要）
npm install && npx patchright install chromium

# 2) 先试跑（不写文件）
python3 update_m3u.py --dry-run

# 3) 正式更新
python3 update_m3u.py
```

> 本机有系统 Chrome 时浏览器兜底直接使用系统 Chrome；GitHub 运行器会自动安装 Patchright 自带 Chromium。

## 部署到 GitHub

1. 在 [github.com/new](https://github.com/new) 新建公开仓库（推荐公开，Actions 分钟数免费无限；私有仓库每月仅 2000 分钟免费额度，本任务每 4 小时跑一次约 10 分钟，可能超限）
2. 推送本目录：

```bash
cd /Users/star/Downloads/douyin-actions
git init -b main
git add -A && git commit -m "init: 抖音直播 m3u 增量更新"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

3. 推送后立即手动触发一次验证：仓库页面 → **Actions** → **增量更新 m3u** → **Run workflow**
4. 之后会自动每 4 小时运行（北京时间 08:00 / 12:00 / 16:00 / 20:00 / 00:00 / 04:00）

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

- m3u 为**增量累积**（新房间排最前），历史条目不会自动清理；下播房间点播会 404，可定期清理
- 抖音对高频请求有风控（`bdturing-verify`），脚本已做请求间隔 + 分页限量 + 单来源失败自动跳过
- GitHub 数据中心 IP 可能触发风控，此时自动走浏览器方案；连续多次"无新增"请查看 Actions 日志确认抓取是否正常
