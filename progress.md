# OpenRouteFinder 全项目扫描会话日志

## 2026-06-11

- 启动全项目扫描任务。
- 创建规划文件 `task_plan.md`、`findings.md`、`progress.md`。
- 确认项目结构：后端 Python + 前端 Vue3/TS，FlatBuffers 导航数据。
- 计划按阶段 1 → 6 推进。

## 2026-06-12

- ✅ 阶段 1：项目结构与文档对齐 — 完成。梳理全部目录、依赖、文档。发现 docs/claude/*.md 大量与代码不同步。
- ✅ 阶段 2：后端代码审查 — 完成。审查 api.py、config.py、data_loader.py、admin.py、utils、dijkstra.py、graph.py、airport.py、storage/registry.py、storage/reader.py、storage/builder.py。
- ✅ 阶段 3：前端代码审查 — 完成。审查全部 Vue/TS 文件、vite.config.ts、package.json。
- ✅ 阶段 4：测试与质量 — 完成。审查全部 13 个测试文件，识别覆盖盲区、CI 不可运行、断言弱点。
- ✅ 阶段 5：安全与运维 — 完成。审查 admin 接口、上传、验证码、并发、资源清理。
- ✅ 阶段 6：汇总与建议 — 完成。整理 `findings.md`，按严重/中等/轻微分类 87 项发现，列出 20 项文档对齐问题、15 项测试问题、5 项待确认事项。

## 关键发现摘要

- **最严重**：`airport.py` `_leg_to_point` 不再过滤合成标记，与 CLAUDE.md 硬性规则矛盾；`_add_network_bridges` 死代码；`dijkstra.py` `forbidden_names` 范围过大误伤合法航路。
- **高频问题**：文档与代码严重不同步（backend.md、sid-star.md、api-endpoints.md 多处错误）；测试过度依赖外部 navdata，CI 无法运行；前端内存泄漏（useMap、AdminView SSE、AirportAutocomplete 共享 timer）。
- **待确认**：D-前缀标记过滤是否为有意变更；ZBAA→RKSI xfail 根因；system 主题模式是否已实现。

## 下一步建议

1. 优先修复严重问题（#1-#17）。
2. 同步更新所有文档（CLAUDE.md、docs/claude/*.md）。
3. 引入最小化测试固件或 mock，让存储测试可在 CI 运行。
4. 前端修复内存泄漏和表单校验。
5. 清理 legacy `AirportConnector` 死代码。
