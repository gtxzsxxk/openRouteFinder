# OpenRouteFinder 全项目扫描任务规划

## 任务目标

扫描整个 OpenRouteFinder 项目的代码和文档，识别潜在问题、代码异味、架构不一致、测试漏洞、文档不同步、性能风险、安全风险和可维护性问题。

## 范围

- 后端：`openRouterFinder/` 全部 Python 代码
- 前端：`webFinder/src/` 全部 Vue/TypeScript 代码
- 文档：`CLAUDE.md`、`docs/claude/*.md`、`README.md`、前端 README
- 测试：`tests/` 全部测试文件
- 配置：`package.json`、`requirements.txt`、`.env.example`、vite config 等

## 阶段

### 阶段 1：项目结构与文档对齐
- [ ] 梳理目录结构、依赖版本
- [ ] 核对 CLAUDE.md 与 docs/claude/*.md 是否覆盖当前代码
- [ ] 标记文档缺失、过时、矛盾之处

### 阶段 2：后端代码审查
- [ ] 审查 `api.py` 端点、错误处理、并发控制、安全性
- [ ] 审查 `core/dijkstra.py` 算法正确性、性能、边界情况
- [ ] 审查 `core/airport.py` SID/STAR 构建逻辑
- [ ] 审查 `core/storage/` 数据读写、热重载、线程安全
- [ ] 审查 `core/data_loader.py` 兼容层与全局状态
- [ ] 审查 `config.py` 配置校验与默认值

### 阶段 3：前端代码审查
- [ ] 审查 `src/App.vue`、views、components 结构与状态管理
- [ ] 审查 composables（尤其 `useMap.ts`）
- [ ] 审查 Pinia store、类型定义、API 调用
- [ ] 审查 PWA 配置与构建产物

### 阶段 4：测试与质量
- [ ] 审查测试覆盖范围与断言强度
- [ ] 运行全部测试，记录失败与异常
- [ ] 检查 lint/format 配置与运行结果

### 阶段 5：安全与运维
- [ ] 检查 admin 接口、上传接口、验证码、密钥管理
- [ ] 检查依赖漏洞、CORS、输入校验
- [ ] 检查日志、错误信息是否泄露敏感信息

### 阶段 6：汇总与建议
- [ ] 整理 findings.md
- [ ] 按严重性与模块分类问题
- [ ] 给出修复优先级与具体建议

## 决策记录

| 时间 | 决策 | 原因 |
|------|------|------|
|      |      |      |

## 下一步

进入阶段 1，开始结构梳理与文档对齐。
