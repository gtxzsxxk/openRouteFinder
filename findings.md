# OpenRouteFinder 全项目扫描发现

## 问题汇总

### 严重（影响正确性/安全/可用性）

| # | 模块 | 问题 | 证据 | 建议 |
|---|---|------|------|------|
| ~~1~~ | ~~`core/airport.py` / 文档~~ | ~~CLAUDE.md 仍要求过滤合成标记 `^D\d+[A-Z]?$`，但代码与测试已确认 Fenix 数据中 D-prefixed 为真实航路点，不过滤~~ | ~~339-354 行注释明确说 "No name-based filtering is applied"；测试 `_is_synthetic_marker` 仅检查空名~~ | ~~更新 CLAUDE.md、docs/claude/sid-star.md、docs/claude/testing.md，保持代码不变~~ |
| ~~2~~ | ~~`core/airport.py`~~ | ~~`_add_network_bridges` 存在但从未被调用；`build_sid`/`build_star` 实际调用 `_add_boundary_bridges`，文档描述的方法名全部错误~~ | ~~118-260 行方法存在，1310/1741 行调用的是 `_add_boundary_bridges`~~ | ~~清理死代码 `_add_network_bridges`，或确认 `_add_boundary_bridges` 已覆盖全部场景后删除旧方法；同步更新所有文档~~ |
| ~~3~~ | ~~`core/dijkstra.py`~~ | ~~`forbidden_names` 范围过大：禁止 airway 经过任何与 procedure point 同名的节点，同名不同坐标的 airway node 被误禁~~ | ~~1509-1525 行收集所有 procedure point 名称~~ | ~~按 `(name, lat, lon)` 精确匹配 forbidden，或仅禁止同一坐标点~~ |
| ~~4~~ | ~~`core/dijkstra.py`~~ | ~~`_build_forbidden` 可能将 SID/STAR 同名 airway node 加入 forbidden，误伤合法航路~~ | ~~272-296 行 `_find_node_for_point` 先查全局 `_node_index`~~ | ~~精确匹配坐标后再加入 forbidden~~ |
| ~~5~~ | ~~`core/dijkstra.py`~~ | ~~fallback 逻辑在 `star_entry` 指定但找不到路径时自动放宽为任意 STAR，违背用户显式选择~~ | ~~305-320 行~~ | ~~当用户显式指定 filter 时不应 fallback，应返回明确错误~~ |
| ~~6~~ | ~~`core/storage/registry.py`~~ | ~~`get()` 返回的 `MmappedNavData` 引用在锁释放后被使用，热重载下可能出现 use-after-close（段错误/ValueError）~~ | ~~41-50 行~~ | ~~将引用计数或不可变快照引入 registry；或让 `get()` 返回深拷贝元数据~~ |
| ~~7~~ | ~~`api.py`~~ | ~~`/api/admin/navdata/upload` 未限制上传文件大小，未校验 zip 内容（zip bomb、路径穿越）~~ | ~~723 行无大小限制；735-757 行解压逻辑~~ | ~~配置 `UploadFile` 大小上限；限制压缩比；校验 `ZipInfo.filename`~~ |
| ~~8~~ | ~~`api.py`~~ | ~~`_valid_codes` 全局内存字典无 TTL/清理，攻击者可请求大量验证码耗尽内存~~ | ~~169 行~~ | ~~增加过期时间、定期清理或限制总量~~ |
| ~~9~~ | ~~`api.py`~~ | ~~`DELETE /api/admin/navdata/{cycle}` 删除文件前未检查该 cycle 是否正被请求使用，删除后正在进行的 `/api/route` 可能访问已关闭的 mmap~~ | ~~590 行~~ | ~~增加引用计数或标记为待删除，延迟清理~~ |
| ~~10~~ | ~~`api.py`~~ | ~~验证码校验 `del _valid_codes[req.validToken]` 在并发下可能触发 KeyError~~ | ~~414-418 行~~ | ~~使用 `pop()` 或加锁~~ |
| ~~11~~ | ~~`core/storage/builder.py`~~ | ~~ILS 频率 BCD 解码 `.rstrip("0")` 错误截断末尾 0，如 108.00 -> 108 -> 10.8~~ | ~~675-692 行~~ | ~~直接按 5 位 BCD 解析：`digits = f"{int(raw_freq):010X}"`~~ |
| ~~12~~ | ~~`core/storage/builder.py`~~ | ~~`_build_nodes` 中 `(row["ID"] or 1) - 1` 假设 ID 连续无空洞，若存在删除则 IID 映射错误，后续 Edge 也指向错误节点~~ | ~~403-420 行~~ | ~~使用显式 `ID -> IID` 字典映射~~ |
| ~~13~~ | ~~`core/storage/builder.py`~~ | ~~`_build_procedure_legs` 未对 leg 行排序，依赖 SQLite 返回顺序~~ | ~~748-805 行~~ | ~~显式 `ORDER BY SeqNumber` 或类似字段~~ |
| ~~14~~ | ~~`core/graph.py`~~ | ~~`great_circle_distance_km` 使用 `asin(sqrt(a))` 对浮点误差敏感；`PI` 精度低于 `math.pi`；`EARTH_RADIUS` 使用赤道半径而非平均半径~~ | ~~6-7 行，14-26 行~~ | ~~改用 `atan2` 公式；使用 `math.pi`；使用 6371.0 km~~ |
| ~~15~~ | ~~`webFinder/src/composables/useMap.ts`~~ | ~~`initMap` 中 `MutationObserver` 和 `matchMedia` 注册后未保存引用，组件卸载时无法移除，内存泄漏~~ | ~~59-111 行~~ | ~~保存引用并在 cleanup 中移除~~ |
| ~~16~~ | ~~`webFinder/src/views/AdminView.vue`~~ | ~~`attachProgress` 中 `activeEsCleanup` 为单例，多 build 时前一个 SSE 被静默覆盖且无法清理~~ | ~~441-463 行~~ | ~~用 Map<buildId, cleanup> 管理~~ |
| ~~17~~ | ~~`webFinder/src/components/AirportAutocomplete.vue`~~ | ~~`debounceTimer` 为模块级变量，多实例同时存在时互相覆盖~~ | ~~57 行~~ | ~~改为组件实例级 ref~~ |

### 中等（性能/可维护性/代码异味）

| # | 模块 | 问题 | 证据 | 建议 |
|---|---|------|------|------|
| ~~18~~ | ~~`core/dijkstra.py`~~ | ~~`search()` 维护两套独立路径（`_mixed_graph_astar` + phase-separated），行为容易不一致~~ | ~~115-409 / 1481-1802 行~~ | ~~已提取 `_build_route_response()` 共享 helper~~ |
| 19 | `core/dijkstra.py` | T-route 过滤逻辑：当节点同时有 T 和非 T 边时，T 边被完全禁用，可能丢失最优解 | 611-621 行 | 重新评估 T-route 策略，或仅在高空航路时跳过 T 边 |
| 20 | `core/dijkstra.py` | 候选剪枝 top 50 按到对端机场距离排序，可能丢弃综合最优解 | 1529-1545 行 | 增加说明注释，或改用 procedure 实际长度加权排序 |
| ~~21~~ | ~~`core/dijkstra.py`~~ | ~~负 IID 映射通过遍历 `node_list` 按名称找对应 airway node，O(N) 且未处理同名多节点~~ | ~~1556-1564 行~~ | ~~已改用 `_node_index` O(1) 精确匹配~~ |
| ~~22~~ | ~~`core/dijkstra.py`~~ | ~~内联启发式计算与 `graph.py` 重复，使用局部 `_PI`/`_R`，修改不同步~~ | ~~1596-1600 行~~ | ~~已统一调用 `graph.heuristic_km`~~ |
| ~~23~~ | ~~`core/dijkstra.py`~~ | ~~移除 airway 循环时丢弃重复 IID 后续节点，可能破坏路径连续性~~ | ~~1685-1698 行~~ | ~~已改为回溯到首次出现点并截断循环~~ |
| ~~24~~ | ~~`core/airport.py`~~ | ~~`_find_nearest_connected_node` 线性扫描所有节点，O(N)~~ | ~~61-85 行~~ | ~~预建空间索引（如 KD-tree）或按网格分区~~ |
| 25 | `core/airport.py` | `_truncate_approach_path` 使用欧几里得距离而非大圆距离 | 1826-1865 行 | 改用 `great_circle_distance_km` |
| 26 | `core/airport.py` | `_collect_approach_bridges` 中 `proc_name` 和 `trans_name` 被解码但从未使用 | 1347-1350, 1398-1401 行 | 删除死变量 |
| 27 | `core/airport.py` | `build_sid` 内部导入 `from collections import defaultdict`（1100 行），应在模块顶部导入 | 1100 行 | 移到文件顶部 |
| 28 | `core/airport.py` | Legacy `AirportConnector` 类（1868-2463 行）与 `FlatbuffersAirportConnector` 并存，大量重复逻辑 | 1868-2463 行 | 评估是否可以删除 legacy 类，或标记为 deprecated |
| ~~29~~ | ~~`core/storage/reader.py`~~ | ~~zstd 解压异常时临时文件未被删除~~ | ~~36-48 行 finally 块~~ | ~~异常时清理临时文件~~ |
| 30 | `core/storage/reader.py` | `_build_indices` 未处理重复 IID，后出现的静默覆盖先出现的 | 64-73 行 | 记录重复并告警 |
| ~~31~~ | ~~`core/storage/reader.py`~~ | ~~`close()` 非幂等，第二次调用抛异常~~ | ~~196-200 行~~ | ~~添加 `self._closed` 标志~~ |
| 32 | `core/storage/registry.py` | 文件名正则 `fb\|fb\.zst` 优先级导致 `navdata_1234.fb.zst` 匹配为 `.fb` | 13 行 | 改为 `^navdata_(\d{4})\.((?:fb\.zst)\|(?:fb))$` |
| 33 | `core/storage/builder.py` | `ILSAddRunwayEnd` 写入 runway end 名；经确认消费端按 end name 使用，当前语义正确 | 476-493 行 | 无需修改，已在代码中保留 end name |
| ~~34~~ | ~~`core/storage/builder.py`~~ | ~~`_runway_base_name` 对非标准后缀（如 `T`、`W`）返回空 `opp_suffix`，导致 `18T/18T`~~ | ~~652-672 行~~ | ~~未知后缀保留原后缀~~ |
| 35 | `core/storage/builder.py` | `RunwayEndAddHeading` 写入 `TrueHeading`；地图渲染需要真北向，当前语义正确 | 575-579 行 | 无需修改，已在注释说明为真航向 |
| ~~36~~ | ~~`core/storage/builder.py`~~ | ~~`_build_grid_mora` 用 `SELECT *` 硬编码 30 列，表结构变化会静默出错~~ | ~~1029-1057 行~~ | ~~已改为动态读取 `mora*` 列~~ |
| ~~37~~ | ~~`core/data_loader.py`~~ | ~~`_sid_cache` / `_star_cache` 无大小限制，长时间运行无限增长~~ | ~~358-360 行~~ | ~~设置 LRU 或 maxlen~~ |
| 38 | `core/data_loader.py` | `_parse_airport_detail` 依赖 legacy `NavGraph.airport_maps`，modern 路径未使用，代码已死 | 291-332 行 | 清理死代码 |
| ~~39~~ | ~~`core/data_loader.py`~~ | ~~`_init_registry()` 未加锁，多线程同时初始化可能创建多个 Registry~~ | ~~117-131 行~~ | ~~加锁保护~~ |
| ~~40~~ | ~~`core/admin.py`~~ | ~~`unique_ips` 已改用 OrderedDict 实现 O(1) 检查/淘汰；`total_requests` 仍无限增长~~ | ~~18, 30-31 行~~ | ~~已改为 `deque(maxlen=2000)` 窗口~~ |
| 41 | `utils/metar.py` | `fetch_metar` 中 `requests.get` 成功后先写文件再更新内存，写文件失败则内存不更新 | 21-31 行 | 先更新内存或统一事务 |
| ~~42~~ | ~~`utils/metar.py`~~ | ~~`read_metar` fallback 读文件未加锁，与 `fetch_metar` 写文件可能并发读到半写文件~~ | ~~56 行~~ | ~~加锁或临时文件+重命名~~ |
| ~~43~~ | ~~`utils/metar.py`~~ | ~~`start_metar_updater` 线程在应用关闭时无法优雅停止~~ | ~~68-80 行~~ | ~~使用 `threading.Event` 控制退出~~ |
| ~~44~~ | ~~`utils/validcode.py`~~ | ~~`_get_font` 每次调用重新加载字体文件~~ | ~~11-20 行~~ | ~~缓存字体对象~~ |
| ~~45~~ | ~~`utils/validcode.py`~~ | ~~使用 `random` 而非 `secrets` 生成验证码~~ | ~~25-35 行~~ | ~~改用 `secrets`~~ |
| ~~46~~ | ~~`config.py`~~ | ~~`navdat_full_path` / `apdat_full_path` 未处理用户配置绝对路径的情况~~ | ~~31-36 行~~ | ~~判断路径是否为绝对路径~~ |
| 47 | `config.py` | `navdat_path` / `apdat_path` 默认指向 legacy pickle 文件，但项目已转向 FlatBuffers | 23-24 行 | 默认改为 FlatBuffers 路径或明确文档说明 |
| 48 | `api.py` | `admin` 接口在每个端点重复写相同的密钥校验，未使用 `Depends` | 537/546/562/577/590/723/813 行 | 抽取 `verify_admin_key` 依赖 |
| 49 | `api.py` | `ThreadPoolExecutor(max_workers=4)` 与 `asyncio.Semaphore(8)` 组合不一致，第 5-8 个任务阻塞事件循环 | 165 行 | 统一信号量与线程池大小 |
| ~~50~~ | ~~`api.py`~~ | ~~`_do_build_navdata` 中压缩后数据直接 `write_bytes`，写入中断留下损坏文件~~ | ~~689-694 行~~ | ~~先写临时文件再原子重命名~~ |
| ~~51~~ | ~~`api.py`~~ | ~~`_airport_prefix_index` 在 navdata 热更新后未重建~~ | ~~172-173 行~~ | ~~在 Registry 注册/注销 cycle 后触发索引重建~~ |
| 52 | `api.py` | `loop.run_in_executor(None, ...)` 使用默认线程池，与 `_dijkstra_pool` 不一致 | 790 行 | 统一使用 `_dijkstra_pool` |
| ~~53~~ | ~~`webFinder/src/composables/useMap.ts`~~ | ~~`nodes.length === 0` 时提前 return 未重置 `isUpdating`，地图卡死~~ | ~~231-235 行~~ | ~~当前代码已有 try/finally，`isUpdating` 会被正确重置~~ |
| ~~54~~ | ~~`webFinder/src/composables/useMap.ts`~~ | ~~`fitBounds` 每次更新都执行 1.5s 动画，用户正在平移/缩放时强制拉回~~ | ~~792-813 行~~ | ~~已增加 `isMoving()` 检测与首次动画~~ |
| ~~55~~ | ~~`webFinder/src/composables/useMap.ts`~~ | ~~五个 `watch` 在 `routeResult` 大对象变更时都触发 `scheduleUpdate`~~ | ~~832-836 行~~ | ~~已合并为单个数组 watcher~~ |
| ~~56~~ | ~~`webFinder/src/stores/routeStore.ts`~~ | ~~`_matchProcedureIndex` / `_matchTransitionIndex` 逻辑重复~~ | ~~106-154 行~~ | ~~已提取 `_scoreMatch` 共享 helper~~ |
| ~~57~~ | ~~`webFinder/src/stores/routeStore.ts`~~ | ~~`routeResult` 原始 ref 直接暴露，外部可绕过 `setRouteResult` 修改~~ | ~~239-271 行~~ | ~~已改用 `shallowReadonly` 暴露~~ |
| ~~58~~ | ~~`webFinder/src/views/HomeView.vue`~~ | ~~`queryTime` 计时器使用 `setInterval(10ms)` 精度浪费~~ | ~~131-162 行~~ | ~~用 `performance.now()` 单次计算~~ |
| ~~59~~ | ~~`webFinder/src/views/HomeView.vue`~~ | ~~Waypoints 列表使用 `:key="i"`（索引作为 key）~~ | ~~86-107 行~~ | ~~已改为 `node.name + i`~~ |
| ~~60~~ | ~~`webFinder/src/components/SearchForm.vue`~~ | ~~`canSubmit` 仅校验 ICAO 长度为 4，用户可输入 `!!!!`~~ | ~~142-144 行~~ | ~~增加正则 `/^[A-Z0-9]{4}$/`~~ |
| ~~61~~ | ~~`webFinder/src/components/ProcedureSelector.vue`~~ | ~~404 时设置 `options = []` 但不设置 error，用户无法区分"无数据"和"机场不存在"~~ | ~~64-104 行~~ | ~~404 时显示特定提示~~ |
| 62 | `webFinder/src/components/SIDSelector.vue` | `selectedIndex` setter 接收 string（Vue 自动转换），类型存在隐式转换风险 | 45-48 行 | 显式 `Number(val)` |
| ~~63~~ | ~~`webFinder/src/i18n/locales/en.ts`~~ | ~~`weather.light/heavy` 值带尾部空格 `"Light "` / `"Heavy "`~~ | ~~en.ts~~ | ~~移除尾部空格~~ |

### 轻微（风格/文档/建议）

| # | 模块 | 问题 | 证据 | 建议 |
|---|---|------|------|------|
| 64 | `core/dijkstra.py` | 分阶段搜索的交替优化最多 5 次，收敛条件只比较名称和 transition，不比较 boundary | 199-255 行 | 增加 boundary 比较或确认收敛充分 |
| 65 | `core/dijkstra.py` | `_sort_route` 对空 airway name 的 bridge 段输出空字符串，route string 出现连续空格 | 1440-1446 行 | 空 name 时输出占位符或跳过 |
| ~~66~~ | ~~`core/dijkstra.py`~~ | ~~`sid_info[1]` 和 `star_info[1]` 作为表达式无实际作用~~ | ~~1720 / 1725 行~~ | ~~已删除无效表达式~~ |
| 67 | `core/graph.py` | `_haversine_a` 与 `great_circle_distance_km` 重复计算，未被任何调用方使用 | 29-39 行 | 删除死代码 |
| 68 | `core/airport.py` | `_collect_procedures` 注释返回类型与实际不符（文档说 dict/dict/dict，实际是 list/dict/list） | 612-616 行注释 | 修正注释 |
| 69 | `core/storage/builder.py` | `flatbuffers.Builder(1024 * 1024)` 初始 1MB 对大型 navdata 可能频繁扩容 | 258 行 | 根据数据量估算初始容量 |
| 70 | `core/storage/builder.py` | `sum(counts.values())` 结果未使用 | 276 行 | 删除 |
| 71 | `core/storage/builder.py` | `_progress` 回调未捕获异常，外部回调抛错中断构建 | 279-281 行 | 包装 `try/except` |
| 72 | `core/storage/builder.py` | `_build_procedure_transitions` 为每个 transition 独立遍历全部 legs，O(T * L) | 808-841 行 | 预按 transition 分组 |
| 73 | `api.py` | 静态文件挂载路径基于 `settings.navdat_full_path.parent.parent`，配置为绝对路径时可能定位错误 | 849 行 | 统一使用 `PROJECT_ROOT` |
| 74 | `api.py` | `admin_logging` 中间件未处理 `request.client` 为 None，且 `x-forwarded-for` 可伪造 | 260 行 | IP 规范化并限制长度 |
| 75 | `api.py` | SSE 端点 `while True` + `asyncio.sleep(1)`，连接断开后不会立即感知 | 813 行 | 增加 `request.is_disconnected()` 检查 |
| 76 | `api.py` | `startup` 中 `start_metar_updater()` 放在 `_build_airport_index()` 之后，启动失败时 METAR 线程仍可能启动 | 854 行 | 将 METAR 启动放最后并处理异常 |
| 77 | `app.py` | `uvicorn.run` 直接运行模块级 `app`，缺少生产参数 | 9 行 | 通过 CLI 或配置启动 |
| ~~78~~ | ~~`config.py`~~ | ~~`env_file=".env"` 是相对路径，取决于工作目录~~ | ~~12 行~~ | ~~改为 `PROJECT_ROOT / ".env"`~~ |
| 79 | `config.py` | `metar_full_path` 硬编码为 `data/metar.txt` | 39-41 行 | 可配置化 |
| 80 | `utils/metar_parser.py` | `"NOT" in tokens and "AVAILABLE" in tokens` 过于宽松 | 85-86 行 | 匹配完整短语 |
| 81 | `utils/metar_parser.py` | 能见度只解析单个 token，未处理 `1 1/2SM` 等 | 114-118 行 | 扩展解析 |
| 82 | `utils/metar_parser.py` | 天气现象正则过于宽泛，可能误匹配 `TEMPO`、`BECMG` | 137-139 行 | 限制为已知天气代码集合 |
| 83 | `webFinder/vite.config.ts` | PWA `manifest.icons` 仅含 `favicon.ico`，缺少多尺寸图标 | 16-36 行 | 补充 PNG/icon maskable 图标 |
| 84 | `webFinder/vite.config.ts` | 缺少 `sourcemap` 配置，生产调试困难 | 52-55 行 | 增加 sourcemap 配置 |
| 85 | `webFinder/package.json` | `version: "0.0.0"` 未维护 | 4 行 | 与实际版本对齐 |
| 86 | `webFinder/package.json` | 缺少 `lint`、`test`、`typecheck` 脚本 | 7-9 行 | 补充脚本 |
| 87 | `webFinder/package.json` | 缺少 `eslint`/`prettier`，代码风格无统一约束 | 23-30 行 | 引入 biome 或 eslint + prettier |

## 文档对齐问题

| 文档 | 状态 | 说明 |
|------|------|------|
| `CLAUDE.md` | ❌ 过时 | `core/dijkstra.py` 描述为 "single mixed-graph A*"，实际有 fallback 到 phase-separated 搜索 |
| `CLAUDE.md` | ❌ 过时 | `core/data_loader.py` 描述 `NavGraph` singleton 为活跃路径，实际 modern 路径通过 `get_nav_registry()` |
| `docs/claude/backend.md` | ❌ 端点缺失 | 缺少 `GET /api/admin`、`GET /api/admin/navdata`、`DELETE /api/admin/navdata/{cycle}` 等 |
| `docs/claude/backend.md` | ❌ 路径错误 | `/api/admin/build/progress/{build_id}` 应为 `/api/admin/navdata/build-progress/{build_id}` |
| `docs/claude/backend.md` | ❌ 模型错误 | `RouteRequest` 中 `validCode`/`validToken` 实际为必填（无默认值） |
| `docs/claude/backend.md` | ❌ 字段缺失 | `config.py` 中 `navdat_cycle` 字段实际不存在 |
| `docs/claude/backend.md` | ❌ 描述错误 | dijkstra.py "0.5× multiplier for SID/STAR edges" 实际代码中未出现 |
| `docs/claude/sid-star.md` | ❌ 流程错误 | `build_sid()` 第 4 步 "airport → runway exit points (first point)" 错误，实际是 last point (network-side exit) |
| `docs/claude/sid-star.md` | ❌ 流程错误 | `build_star()` 第 10 步 "last point to airport" 错误，实际是 first point (network-side entry) |
| `docs/claude/sid-star.md` | ~~❌ 代码片段过时~~ ✅ 已修复 | ~~`_leg_to_point()` 代码片段显示过滤 D-前缀标记，实际代码已不再过滤~~ |
| `docs/claude/sid-star.md` | ~~❌ 方法名错误~~ ✅ 已修复 | ~~`_add_network_bridges()` 文档描述，实际代码调用的是 `_add_boundary_bridges()`~~ |
| `docs/claude/sid-star.md` | ❌ 类型错误 | `_collect_procedures()` 返回值文档描述为 dict/dict/dict，实际是 list/dict/list |
| `docs/claude/api-endpoints.md` | ❌ Admin 端点不全 | 同 backend.md，仅列出 upload 和 build/progress（路径还错） |
| `docs/claude/api-endpoints.md` | ❌ Response 格式错误 | `POST /api/route` 的 `nodes` 示例为数组列表，实际返回对象列表 |
| `docs/claude/api-endpoints.md` | ❌ Response 字段缺失 | `POST /api/route` 缺少 `weather`、`parsedWeather`、`airportDetails` 示例 |
| `docs/claude/api-endpoints.md` | ❌ Response 过度丰富 | `GET /api/airports/{icao}` 示例含 `elevation`/`runways`，实际只返回 icao/name/lat/lon |
| `docs/claude/api-endpoints.md` | ❌ 字段名错误 | `GET /api/version` 示例字段为 `cycle`，实际为 `version` |
| `docs/claude/testing.md` | ✅ 基本准确 | 测试文件列表和描述基本正确，但需补充 builder/registry 测试的 navdata 依赖说明 |
| `docs/claude/data-formats.md` | ❓ 待确认 | `NavData.fbs` 路径需确认文件是否存在；`MmappedNavData` 索引需确认与实际一致 |
| `README.md` | ❌ 端点不全 | 缺少 `/api/cycles`、`/api/airports/{icao}/procedures`、`/api/admin/*` 等 |
| `webFinder/README.md` | ❌ 模板未改 | 仍是 Vite 模板默认内容，无项目特定信息 |

## 测试问题

| 测试文件 | 状态 | 说明 |
|----------|------|------|
| `tests/test_graph.py` | ⚠️ 覆盖不足 | 未测试 `node_key()`、`_haversine_a`、`heuristic_km` 精度、Edge 默认值 |
| `tests/test_dijkstra.py` | ⚠️ 覆盖不足 | 未测试 `_astar_airway`、`_mixed_graph_astar`、`_select_procedure`、`_assemble_route` 等核心方法 |
| `tests/test_dijkstra.py` | ⚠️ 断言弱 | `test_route_engine_search_accepts_constraint_params` 仅断言 `result is not None` |
| `tests/test_airport.py` | ⚠️ legacy 测试 | 测试的是 legacy `AirportConnector`，项目已迁移到 FlatBuffers |
| `tests/test_airport.py` | ⚠️ 覆盖不足 | 未测试 `_leg_to_point`、bridge edge、transition splitting 等核心逻辑 |
| `tests/test_data_loader.py` | ⚠️ 覆盖不足 | 大量生产代码未测试（`_parse_airport_detail`、`_get_airport_detail_from_fb` 等） |
| `tests/test_storage_reader.py` | ❌ CI 无法运行 | 硬编码 Fenix 路径，CI 必 skip |
| `tests/test_storage_registry.py` | ❌ CI 无法运行 | 同上；无并发/热重载测试 |
| `tests/test_storage_builder.py` | ❌ CI 无法运行 | 同上；仅验证字节长度 >0，未验证转换正确性 |
| `tests/test_procedure_integrity.py` | ⚠️ 逻辑矛盾 | `_is_synthetic_marker()` 仅检查 `not name`，与文档要求的 `^D\d+[A-Z]?$` 过滤矛盾 |
| `tests/test_procedure_integrity.py` | ⚠️ 策略不一致 | `test_no_runway_all_when_specific_exists` 与 `test_post_route_no_runway_all_when_specific_exists` 对 `ALL` 的处理策略不同 |
| `tests/test_integration_routes.py` | ⚠️ xfail 不一致 | `ZBAA->RKSI` 在 `STANDARD_ROUTES` 中标记 xfail，但在 `AIRPORT_PAIRS` 中未标记，导致部分测试硬失败 |
| `tests/test_integration_routes.py` | ⚠️ skip 过多 | `test_exhaustive_sid_star_combinations` 在 `not sid_exits or not star_entries` 时 skip，违背 CLAUDE.md 原则 |
| `tests/test_integration_routes.py` | ⚠️ 静默跳过 | `test_walk_complete_route_all_sid_exits` 和 `all_star_entries` 对非 200/`No result.` 使用 `continue` 而非 `pytest.fail` |
| 跨文件 | ⚠️ 重复 helper | `_point_dist_km` 在 `test_procedure_integrity.py` 和 `test_integration_routes.py` 中都有定义 |
| 跨文件 | ⚠️ navdata 依赖 | 大量测试依赖 `data/navdata_2604.fb.zst`，缺失时 skip 或失败，建议分离为集成测试 |

## 待确认事项

1. ~~✅ 已确认：`_leg_to_point` 不过滤 D-前缀标记是有意变更。文档（CLAUDE.md、sid-star.md、testing.md）已同步更新。~~
2. `_add_network_bridges` 是否已被 `_add_boundary_bridges` 完全替代？确认后可删除。
3. `ZBAA->RKSI` 的 xfail 是算法特性还是 bug？需在代码注释或文档中明确。
4. `tests/test_procedure_integrity.py` 中 `_is_synthetic_marker()` 的宽松逻辑是否与数据现实一致？
5. 前端 `useTheme` 的 `system` 模式是否已实现？当前代码中 `system` 实际上不可用。

## 引用

- 所有代码路径与行号均来自实际代码审查，详见上方表格。
