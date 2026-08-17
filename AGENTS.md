# AGENTS.md —— 给接手的 AI 看的速览（先读这份）

本项目是一个**抖音直播 m3u 增量更新器**：定期抓取 `sources.txt` 里配置的抖音
分类页/直播间，增量去重后生成 `douyin_live.m3u`。主逻辑**纯 Python 标准库**，
不需要 Docker，也不需要安装任何 Python 依赖；浏览器兜底（可选）只用 Node。

> 当前 GitHub Actions 已按用户要求停用（workflow 已删除），以本地运行为主。
> 如需恢复调度，参考 `README.md` 的「恢复 GitHub Actions（可选）」与 git 历史。

## 一、常用命令

```bash
# 试跑：只打印统计，不写文件（改代码后先跑这个）
python3 update_m3u.py --dry-run

# 正式更新：写入 douyin_live.m3u
python3 update_m3u.py

# 语法自检
python3 -m py_compile update_m3u.py
node --check browser_fetch.mjs

# 生成后校验：m3u 内 tvg-id（房间号）不允许重复，以下输出应为 0
grep -oE 'tvg-id="[0-9]+"' douyin_live.m3u | sort | uniq -d | wc -l
```

浏览器兜底如需启用才装（纯 HTTP 不依赖）：
`npm install && npx patchright install chromium`。

## 二、数据流一览

```
sources.txt ──load_sources()──► [(kind, target), ...]   kind=room|category
                                   │  每来源独立线程（MAX_WORKERS=4）
                                   ▼
                         fetch_source() 三级降级：
                   分类: ①HTTP接口 ─► ②浏览器(滚动) ─► ③页面HTML(RSC)
                   房间: ①HTTP接口 ─► ②页面HTML ─► ③浏览器
                                   ▼
              房间信息 {rid, title, avatar, nickname, url(CDN直链)}
                                   ▼
read_existing_m3u() 读旧文件 → 增量合并（新条目置顶、删旧重复、保留历史）
                                   ▼
                          render_entry() → douyin_live.m3u
```

## 三、代码结构与关键函数（`update_m3u.py`）

| 函数 | 行号 | 作用 |
|---|---|---|
| `Session` | 67 | 带 CookieJar 的 HTTP 会话；`warm()` 先拿 ttwid cookie |
| `split_category` | 101 | 分类路径 `4_103_1_2_1_1010014` → (partition, partition_type) |
| `load_sources` | 128 | 解析 `sources.txt`（支持分类页/直播间页/纯房间号） |
| `api_params` | 142 | 拼分类接口参数，含 `a_bogus` |
| `check_risk` | 156 | 检测风控头（`bdturing-verify`）或空 body |
| `extract_cdn_url` | 164 | 从 `stream_url` 提最高清 CDN 直链 |
| `parse_category_item` | 183 | 分类接口单条 → 房间 dict（注意 owner 在 room 里） |
| `http_fetch_category` | 207 | ①接口主路径：分页拉取，内置 3 次重试 |
| `http_fetch_room` | 243 | ①单个直播间 `room/web/enter` |
| `category_group_name` | 320 | 分类路径 → group-title 名称（三级取值） |
| `parse_page_html` | 338 | ③解析页面内嵌 RSC 数据（约 15 个置顶房间） |
| `browser_fetch` | 425 | ②调 `browser_fetch.mjs`（Node/Patchright，串行锁） |
| `fetch_source` | 444 | 每个来源的三级降级编排 |
| `read_existing_m3u` | 487 | 读旧 m3u，返回 header + 按 tvg-id 去重的条目 |
| `render_entry` | 524 | 生成 `#EXTINF` 行与播放地址 |
| `main` | 567 | 并发抓取 → 增量合并 → 写文件 |

浏览器侧（`browser_fetch.mjs`）：分类页滚动加载并拦截站点带签名的接口响应，
输出 JSON `[{rid, title, avatar, nickname}]` 到 stdout：
`node browser_fetch.mjs <URL>`（支持 `HEADLESS=0` 有头模式）。

## 四、必须知道的关键细节（踩过的坑）

1. **`a_bogus` 只需"存在"**：分类接口校验的是参数存在，不校验取值，
   固定值 `A_BOGUS_PARAM = 'a' * 188`（`api_params` 里）实测 60/60 通过，
   任何分类、任何分页都通用。不要试图去实现真实签名算法。
2. **分类接口 item 里没有 `owner`**：昵称在 `room.owner.nickname`，
   头像在 `room.cover.url_list`；`parse_category_item` 已做多候选兜底。
   改字段取值时保持这种"逐候选"风格，别只取一层。
3. **分类接口偶发返回空数据**（抖动，非风控）：`http_fetch_category`
   已内置 `CATEGORY_RETRY=3` 次整体重试；个别来源失败只告警不阻塞。
4. **去重键 = `tvg-id`（房间号）**：全局唯一。增量合并规则：
   - 本轮抓到的房间**全部插到 m3u 最前面**（按 sources 顺序，房间号去重）
   - 旧文件中同房间号的旧条目**删除**（让位给顶部新条目）
   - 本轮未抓到的历史条目**按原顺序保留在后面**
5. **历史条目不重新抓取**：旧条目的标题/头像/地址只在它再次被本轮抓到时
   才更新；CDN 直链带签名时效，所以"本轮在播"的条目每次重跑都会刷新地址。
6. **播放地址优先级**：CDN 直链（`hls_pull_url_map` 按 `FULL_HD1→HD1→SD1→SD2`，
   hls 优先、flv 兜底、自动转 https），拿不到才回退
   `https://douyin-m3u8.pages.dev/room/<房间id>`。
7. **标题 = `用户昵称-房间名`**（`render_entry`）：昵称或房间名缺失时退化为
   另一者，都没有才用房间号。
8. **`group-title` 三级取值**（`category_group_name`）：页面 RSC 动态提取的
   类目名 → 静态映射 `CATEGORY_NAMES` → 兜底 `抖音`。不要全局写死"抖音"。
9. **退出码语义**：`0` = 成功（即使部分来源失败，只要 m3u 已更新）；
   仅完全没抓到任何房间才返回 `1`（CI 判断失败用它）。
10. **ttwid 初始化失败**时 `http_ok=False`：跳过 ① 接口层，
    分类直接走浏览器、直播间直接走页面（见 `_fetch_one`）。

## 五、常见修改场景

**加/改抓取来源**：编辑 `sources.txt`，每行一个地址，`#` 注释；
新增分类后记得在 `CATEGORY_NAMES` 里补静态类目名（第 47 行附近），
否则风控/页面失败时 group-title 会兜底成"抖音"。

**调抓取量/速度**：`update_m3u.py` 顶部常量——`MAX_PAGES=14`（每分类约 210 房间）、
`MAX_WORKERS=4`（来源并发，越大越快但更容易触发风控）、
`PAGE_SLEEP`/`SOURCE_SLEEP`（请求间隔）、`CATEGORY_RETRY`（重试次数）。

**改标题/分组/地址格式**：`render_entry`（524 行）是唯一出口，改它即可。

## 六、提交前验证清单

1. `python3 -m py_compile update_m3u.py`、`node --check browser_fetch.mjs` 通过
2. `python3 update_m3u.py --dry-run`：注意「抓取统计」里 `接口` 应为多数、
   `失败来源` 应尽量为 0（偶发 1~2 个分类接口抖动属正常）
3. 去重校验输出为 0（见第一节命令）
4. 抽查 m3u 头部与条目：`#EXTM3U` 开头、`#EXTINF` 紧接一行 http 地址、
   标题为「昵称-房间名」、group-title 不是全局"抖音"
5. 提交推送：`git add -A && git commit`（消息风格参考历史：
   `docs:` / `feat:` / `chore: 增量更新 douyin_live.m3u（…UTC）`），
   然后 `git fetch && git rebase origin/main && git push`

> 本仓库是唯一维护点；上级目录 `/Users/star/Downloads/douyin` 是旧备份，不要动。
