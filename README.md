# Airway Route Finder (openRouteFinder)

`Airway Route Finder` 是一个开源的由 Python 编写的模拟飞行航路查询工具。
`Airway Route Finder` is an open-source flight route finder for flight simulation, written in Python.

本项目使用 Dijkstra 算法求解两个机场之间的最短航路。
It uses Dijkstra algorithm to find the shortest airway between two airports.

## v2.0 全新重构 / v2.0 Complete Refactor

2026 年，本项目进行了全面技术栈升级：
In 2026, the project underwent a complete tech stack upgrade:

- **前端 / Frontend**: Vue 3 + TypeScript + Vite + Tailwind CSS + MapLibre GL JS
- **PWA 支持 / PWA Support**: 离线可用，可安装到桌面/手机 / Works offline, installable on desktop/mobile
- **后端 / Backend**: FastAPI 替代手写 socket / FastAPI replaces hand-written socket HTTP server
- **地图 / Map**: OpenStreetMap via MapLibre，**无需 API Key，完全免费** / No API key required, free forever
- **组件化 UI / Component UI**: 模块化、类型安全、可维护 / Modular, type-safe, maintainable

---

## 特性 / Features

- 可以静态调用算法实现，也可以直接提供航路查询的 Web API
  Can be used as a library or via Web API
- 提供了前端页面，提供完整的航路查询网站服务
  Provides a complete web interface for route queries
- **目前唯一的，能够允许用户选择进离场程序的，在线航路查询服务**
  **The only online service that allows users to select SID/STAR procedures**
- **在我们的前端网页，你可以自由选择进离场程序，并且在地图上规划它们**
  **On our frontend, you can freely select SID/STAR procedures and visualize them on the map**

## 在线演示 / Online Demo

~~by HKYFLY 社区 / by HKYFLY Community: https://route.hkyfly.com/~~
Not Available

---

## 快速开始 / Quick Start

### 环境要求 / Prerequisites

- Node.js 20+（前端 / for frontend）
- Python 3.10+ with pip（后端 / for backend）
- 导航数据文件 / Navigation data files: `airport_2206.air`, `navidata_2206.map`

### 开发环境 / Development

```bash
# 安装 Python 依赖 / Install Python dependencies
pip install -r requirements.txt

# 安装 Node 依赖 / Install Node dependencies
cd webFinder && npm install

# 同时启动前后端 / Start both frontend and backend
npm run dev
# 或分别启动 / Or separately:
npm run dev:frontend  # Vite dev server on :5173
npm run dev:backend   # FastAPI on :9807
```

### 生产部署（树莓派/服务器）/ Production (Raspberry Pi / Server)

```bash
# 构建前端 / Build frontend
cd webFinder && npm run build

# 启动后端（同时提供 API + 静态文件）/ Start backend (serves API + static files)
cd openRouterFinder && uvicorn api:app --host 0.0.0.0 --port 9807
```

访问 / Visit: `http://localhost:9807/`

---

## API 接口 / API Endpoints

| Method | Path | 中文说明 | Description |
|--------|------|----------|-------------|
| GET | `/api/version` | 导航数据周期 | Navigation data cycle |
| GET | `/api/cycles` | 可用导航数据周期 | Available navdata cycles |
| GET | `/api/airports?q=` | 机场搜索 | Airport search |
| GET | `/api/airports/{icao}` | 机场基本信息 | Airport basic info |
| GET | `/api/airports/{icao}/procedures` | 机场进离场程序 | Airport SID/STAR procedures |
| POST | `/api/route` | 计算航路 | Calculate route |
| GET | `/api/metar/{icao}` | METAR 天气 | METAR weather |
| GET | `/api/validcode` | 获取验证码 | Get captcha |
| GET | `/health` | 健康检查 | Health check |
| GET | `/api/admin` | 管理统计 | Admin statistics |
| POST | `/api/admin/navdata/upload` | 上传 Fenix 导航数据 | Upload Fenix navdata |
| GET | `/api/admin/navdata/build-progress/{build_id}` | 构建进度 SSE | Build progress SSE |

---

## 导航数据的预处理 / Navigation Data Preprocessing

本项目需要对 `aerosoft` 提供的导航数据进行预处理。
This project requires preprocessing of `aerosoft` navigation data.

`aerosoft` 提供的导航数据存储在磁盘上，如果直接使用 Dijkstra 算法查询，由于涉及 IO 读写，效率会非常低。
The raw data is stored on disk; direct I/O would be too slow for Dijkstra queries.

因此我们需要将航路全部加载进内存并组织结构。预处理由 `openRouterFinder/scripts/pack_data.py` 完成。
We load all airways into memory and organize them. Preprocessing is done by `openRouterFinder/scripts/pack_data.py`.

在使用前，请先配置好 `.env` 或环境变量：
Before using, configure `.env` or environment variables:

```bash
LOCAL_ASDATA_PATH="/path/to/aerosoft/data"
```

接着执行 / Then run:
```bash
$ python3 openRouterFinder/scripts/pack_data.py
Read Airports' data?(y/n strictly):
```

输入 `y` 预处理机场数据（输出到 `airport_$(navCycle).air`），输入 `n` 预处理全球航路（输出到 `navidata_$(navCycle).map`）。
Type `y` to preprocess airport data (output to `airport_$(navCycle).air`), `n` for global airways (`navidata_$(navCycle).map`).

注意：预处理可能花费分钟级别的时间。
Note: Preprocessing may take several minutes.

---

## 项目架构 / Architecture

```
openRouteFinder/
├── openRouterFinder/  # FastAPI + 核心算法 / FastAPI + core algorithm
│   ├── api.py         # FastAPI 应用 / FastAPI application
│   ├── app.py         # Uvicorn 入口 / Uvicorn entry point
│   ├── config.py      # 配置 / Configuration
│   ├── core/
│   │   ├── graph.py          # 图数据结构 / Graph data structures
│   │   ├── airport.py        # 机场/SID/STAR 解析 / Airport parser
│   │   ├── dijkstra.py       # A* 路由引擎 / A* route engine
│   │   └── data_loader.py    # 数据加载 / Data loading
│   ├── utils/
│   │   ├── validcode.py      # 验证码 / Captcha
│   │   └── metar.py          # METAR 天气 / METAR weather
│   └── scripts/
│       ├── pack_data.py      # 数据预处理 / Data preprocessing
│       └── demo.py           # CLI 演示 / CLI demo
├── webFinder/         # Vue 3 SPA
│   ├── src/
│   │   ├── components/       # SearchForm, RouteMap, etc.
│   │   ├── composables/      # useMap, useRouteQuery
│   │   ├── stores/           # Pinia 状态管理 / Pinia state management
│   │   └── types/            # TypeScript 类型定义 / TypeScript definitions
│   └── dist/                 # 构建产物 / Build output
├── data/              # 导航数据文件 / Navigation data files
└── docs/              # 设计文档 / Design specs
```

---

## 关于代码 / About the Code

> 代码是本人在高中时期编写的，代码写的比较乱，命名也不规范，很多代码还没来得及格式化，现在也很少有时间再来维护，但是本分支不会放弃维护，仍然欢迎任何形式的贡献。
>
> The code was written during high school. It's messy, naming is inconsistent, and much of it wasn't formatted. There's little time for maintenance now, but this branch won't be abandoned. Any form of contribution is welcome.

2026 年的重构保留了核心算法（`RouteFinderLib.py`），将手写 socket HTTP 服务器替换为 FastAPI，前端从单文件 HTML 升级为 Vue 3 组件化架构。
The 2026 refactor preserves the core algorithm (`RouteFinderLib.py`), replaces the hand-written socket HTTP server with FastAPI, and upgrades the frontend from a single HTML file to a Vue 3 component architecture.

---

## 关于 / About

本项目使用十分宽松的 MIT 协议，特此授予任何人免费获得本软件和相关文档文件（"软件"）副本的许可，不受限制地处理本软件，包括但不限于使用、复制、修改、合并、发布、分发、再许可的权利。

This project is licensed under the permissive MIT license. Anyone is granted permission, free of charge, to obtain a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense.

而且，**你不需要注明作者、来源等信息，你可以自由地使用、修改我的代码**。

**You do not need to attribute the author or source. You are free to use and modify my code.**

## 遇到问题 / Issues

请直接提 issue。 / Please open an issue directly.
