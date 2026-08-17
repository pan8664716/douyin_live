# 抖音直播 m3u 更新器

抓取抖音**分类页/直播间**的在播房间，增量去重生成播放列表 `douyin_live.m3u`，
播放地址优先使用抖音 CDN 直链（`douyincdn.com` 的 m3u8）。

> 当前状态：**GitHub Actions 已停用**（2026-08-16 删除了 workflow），
> 可在本地手动运行 `python3 update_m3u.py` 更新。

## 功能与行为

- **播放地址**：从分类接口响应自带的 `stream_url.hls_pull_url_map` 提取最高清 CDN 直链
  （`FULL_HD1 → HD1 → SD1 → SD2`，hls 优先、flv 兜底、自动转 https）。
  CDN 直链带签名时效，重新运行时自动刷新本轮在播房间的地址。
- **标题格式**：`用户昵称-房间名`（昵称或房间名缺失时退化为另一者，都没有则用房间号）。
- **分组**：`group-title` 自动取来源对应的类目名（如 英雄联盟 / 舞蹈 / 音乐），
  页面动态提取失败时回退静态映射 `CATEGORY_NAMES`。
- **增量合并（核心）**：
  - 本轮抓到的房间全部插到列表最前面（按 `sources.txt` 顺序）
  - 旧文件中同房间号的重复条目自动删除（全局唯一，以 `tvg-id` 去重）
  - 本轮未抓到的历史条目按原顺序保留在后面
- **抓取策略（每来源三级降级）**：
  1. **HTTP 接口**（默认主路径，无需浏览器）：分类接口 URL 带 `a_bogus` 参数即放行
     （服务端只校验参数存在、不校验取值，固定值 `'a'*188` 实测 60/60 通过），
     每分类最多 14 页约 210 房间；直播间用 `room/web/enter`。16 来源 4 线程并发约 1 分钟
  2. **浏览器**（Patchright，接口风控时兜底）：打开分类页滚动加载，拦截带签名的接口响应
  3. **HTTP 页面解析**（最后兜底）：从页面内嵌 RSC 数据取约 15 个置顶房间

## 文件说明

| 文件 | 说明 |
|---|---|
| `sources.txt` | **来源配置**：每行一个直播间页或分类页地址 |
| `update_m3u.py` | 主脚本（纯 Python 标准库）：抓取 → 提取 CDN → 增量去重 → 写 m3u |
| `browser_fetch.mjs` | 浏览器兜底（Node + Patchright），仅接口风控时被调用 |
| `douyin_live.m3u` | 生成的播放列表 |
| `package.json` / `node_modules` | 浏览器兜底依赖（可选，纯 HTTP 不需要） |
| `AGENTS.md` | **AI 接管指引**：实现细节、常见坑、修改指南，新接手的 AI 先读它 |

## 本地运行

```bash
# 依赖：Python 3.10+（仅标准库）；浏览器兜底可选，需 Node + patchright
# npm install && npx patchright install chromium   # 可选：装浏览器兜底

# 试跑（只打印统计，不写文件）
python3 update_m3u.py --dry-run

# 正式更新（写入 douyin_live.m3u）
python3 update_m3u.py
```

输出示例：
```
共 16 个来源
ttwid 初始化完成, status=200
  [接口] 4_103_1_3: 200 个, group="单机游戏"
抓取统计: {'接口': 16, '浏览器': 0, '页面': 0}，失败来源: 0 个
完成: 新增 990 条, 置顶刷新 1612 条, 删除旧重复 1612 条, 保留历史 5797 条, 合计 8399 条
```

- 退出码：**0 = 成功**（即使个别来源失败，只要 m3u 已更新）；仅完全没抓到任何房间才返回 1。
- 部分来源失败只打印告警，不影响整体（接口偶发抖动已内置 3 次重试）。

## 修改抓取来源

编辑 `sources.txt`，支持三种写法：

```
# 直播间页
https://live.douyin.com/745350622378

# 纯房间号
745350622378

# 分类页
https://live.douyin.com/categorynew/4_105
https://live.douyin.com/categorynew/4_103_1_2_1_1010014
```

新增分类后建议在 `update_m3u.py` 的 `CATEGORY_NAMES` 里补静态名称映射（类别名兜底）。

## 播放列表使用

- 下载 `douyin_live.m3u` 导入 PotPlayer / VLC / 其他 IPTV 播放器
- 每条 `#EXTINF` 带 `tvg-logo`（头像）、`group-title`（分类）、`tvg-id`（房间号，去重用）

## 恢复 GitHub Actions（可选）

如需恢复定时调度，重新添加 `.github/workflows/update-m3u.yml`（参考历史版本或 Git 历史），
调度 cron 用 `0 * * * *`（每小时整点，UTC）。注意公开仓库分钟数免费无限，私有仓库每月限 2000 分钟。

## 注意事项

- m3u 为**增量累积**：本轮在播房间用 CDN 直链（有签名时效，重跑即刷新）；
  历史保留房间的标题/头像只在它再次被本轮抓到时才更新（历史数据不再单独重新抓取）。
- 抖音对高频请求有风控（`bdturing-verify` / whirl），脚本已做：请求间隔 + 分页限量 +
  来源级重试 + 三级降级 + 部分失败不阻塞。
- 分类接口偶发返回空属正常抖动，已内置重试；长时间大量"空数据"请检查是否被封 IP。
