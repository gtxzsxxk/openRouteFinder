# Frontend Architecture

Frontend lives in `webFinder/`. Vue 3 SPA with TypeScript, Vite, Tailwind CSS v4, MapLibre GL JS, Pinia.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Vue 3 (Composition API, `<script setup>`) |
| Build | Vite 8, `vue-tsc` for type checking |
| Styling | Tailwind CSS v4 with `@tailwindcss/vite` plugin |
| State | Pinia 3 |
| Data Fetching | TanStack Vue Query (`@tanstack/vue-query`) |
| Map | MapLibre GL JS 5 |
| Icons | `@lucide/vue` |
| Utilities | `@vueuse/core` |
| i18n | `vue-i18n` (zh + en) |
| PWA | `vite-plugin-pwa` with auto-update |

## Vite Config

- Dev server: port 5173, host `0.0.0.0`
- Proxy: `/api` and `/health` → `http://127.0.0.1:9807`
- Path alias: `@` → `./src`
- PWA manifest: name "OpenRouteFinder", theme `#1a1a2e`, standalone display
- Workbox caches JS/CSS/HTML/ICO/PNG/SVG
- Build output: `dist/`

## Directory Structure

```
webFinder/src/
├── components/          # Vue SFC components
│   ├── SearchForm.vue       # Main search form (airports, procedures, captcha)
│   ├── RouteMap.vue         # MapLibre map with route visualization
│   ├── RouteHero.vue        # Route summary display
│   ├── ProcedureSelector.vue # SID/STAR dropdown selector
│   ├── SIDSelector.vue      # SID-specific selector
│   ├── STARSelector.vue     # STAR-specific selector
│   ├── AirportAutocomplete.vue # Airport search with autocomplete
│   ├── AirportInfo.vue      # Airport detail card
│   ├── AirportSection.vue   # Airport info section in results
│   ├── WeatherSection.vue   # METAR weather display
│   ├── WeatherCard.vue      # Individual weather card
│   ├── CaptchaModal.vue     # CAPTCHA verification modal
│   └── BentoCell.vue        # Bento grid cell wrapper
├── composables/         # Vue composables
│   ├── useMap.ts            # MapLibre integration (largest file)
│   ├── useRouteQuery.ts     # Route search mutation
│   ├── useCycles.ts         # Navdata cycle fetching
│   ├── useAdmin.ts          # Admin API operations
│   ├── useNavData.ts        # Airport/navdata queries
│   ├── useLocale.ts         # i18n locale management
│   ├── useTheme.ts          # Dark/light theme
│   └── useClipboard.ts      # Clipboard utilities
├── stores/
│   └── routeStore.ts        # Pinia store for route state & auto-selection
├── views/
│   ├── HomeView.vue         # Main search page (bento grid layout)
│   └── AdminView.vue        # Admin dashboard (login + stats + upload)
├── i18n/
│   ├── index.ts             # i18n setup (zh default, en fallback)
│   └── locales/
│       ├── zh.ts
│       └── en.ts
├── types/
│   └── index.ts             # TypeScript interfaces
├── main.ts                  # App entry
└── style.css                # Global styles + Tailwind directives
```

## Key Components

### SearchForm.vue

- Two `AirportAutocomplete` inputs (departure/arrival) with swap button
- Navdata cycle selector (dropdown if multiple cycles available)
- Procedure selectors (SID/STAR) shown when both airports are 4 chars
- Search button with loading state
- CAPTCHA modal (conditionally skipped when `disableCaptcha` is true)
- Emits `search` event with `{ orig, dest, validCode, validToken, sidExit, starEntry, cycle }`

### RouteMap.vue

- Initializes MapLibre GL with CARTO basemaps (Positron/Dark Matter)
- Watches for theme changes via `MediaQueryList` + `MutationObserver`
- Displays: route line, SID path, STAR path, airports, waypoints
- Uses CSS custom properties (`--color-route-line`, `--color-accent`) with dark/light fallbacks
- Map centered on `[113.22, 28.19]` (China), zoom 4

### ProcedureSelector.vue

- Type prop: `"sid"` or `"star"`
- Fetches procedures from `/api/airports/{icao}/procedures`
- Groups by exit (SID) or entry (STAR) points
- Displays runway + transition information

## State Management (routeStore.ts)

```typescript
// State refs
routeResult: RouteResult | null
selectedSIDIndex: number
selectedSTARIndex: number
selectedSIDTransitionIndex: number   // -1 = none
selectedSTARTransitionIndex: number  // -1 = none
isLoading: boolean
error: string | null

// Auto-selection logic (setRouteResult)
_matchProcedureIndex(): Scores procedures by counting point names in route node set
_matchTransitionIndex(): Scores transitions similarly
// Respects activeSIDTransition / activeSTARTransition from backend if present
```

## Data Fetching Patterns

- **Cycles**: `useCycles()` uses `@tanstack/vue-query` with `refetchInterval: 30000`
- **Route**: `useRouteQuery()` uses `useMutation` for POST `/api/route`
- **Airport/Procedures**: `useNavData()` uses `useQuery` with caching
- **Admin**: `useAdmin()` handles login state + SSE progress stream

## i18n

- Default locale: zh (read from `localStorage` key `orf-locale`)
- Fallback: zh
- All UI text uses `$t('key')` or `t('key')`
- Translation files: `src/i18n/locales/zh.ts`, `en.ts`

## Theme

- Dark mode: `data-theme="dark"` on `<html>`
- Light mode: default
- Map basemap switches between CARTO Positron (light) and Dark Matter (dark)
- CSS custom properties defined in `style.css`
