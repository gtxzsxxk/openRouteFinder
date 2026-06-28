# OpenRouteFinder Frontend

Vue 3 + TypeScript + Vite + Tailwind CSS SPA for the OpenRouteFinder flight route planner.

## Project Setup

```bash
npm install
```

## Development

```bash
npm run dev          # Vite dev server on :5173, proxies /api to :9807
npm run dev:frontend # Vite dev server only
```

## Build

```bash
npm run build        # type-check + production build
npm run typecheck    # type-check only
npm run preview      # preview the production build
```

## Tech Stack

- Vue 3 (Composition API, `<script setup>`)
- TypeScript
- Vite
- Tailwind CSS v4
- MapLibre GL JS
- Pinia
- Vue Query (TanStack)
- Vue I18n
