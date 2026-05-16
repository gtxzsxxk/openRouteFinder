<template>
  <div v-if="store.routeResult" class="bg-surface border border-border rounded-xl p-6 space-y-4">
    <div>
      <h3 class="text-lg font-semibold text-white mb-2">查询结果</h3>
      <div class="bg-primary rounded-lg p-4 font-mono text-sm text-text break-all leading-relaxed">
        {{ store.routeResult.route }}
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div class="bg-primary rounded-lg p-3">
        <span class="text-xs text-text-muted block mb-1">计算距离</span>
        <span class="text-white font-medium">{{ store.routeResult.distance }}</span>
      </div>
      <div class="bg-primary rounded-lg p-3">
        <span class="text-xs text-text-muted block mb-1">服务端耗时</span>
        <span class="text-white font-medium">{{ store.routeResult.total_time }}s</span>
      </div>
    </div>

    <div class="text-xs text-text-muted">
      数据版本: {{ store.routeResult.data_version }}
    </div>

    <!-- Waypoint List -->
    <div class="border-t border-border pt-4">
      <h4 class="text-sm font-medium text-white mb-3">航路详情</h4>
      <div class="max-h-64 overflow-y-auto">
        <table class="w-full text-sm">
          <thead class="text-text-muted text-xs sticky top-0 bg-surface">
            <tr>
              <th class="text-left py-2 pr-4">航点</th>
              <th class="text-right py-2">纬度</th>
              <th class="text-right py-2 pl-4">经度</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="(node, i) in store.routeResult.nodes" :key="i" class="hover:bg-primary transition-colors">
              <td class="py-2 pr-4 font-mono" :class="i === 0 || i === store.routeResult.nodes.length - 1 ? 'text-highlight font-semibold' : 'text-text'">
                {{ node.name }}
              </td>
              <td class="text-right py-2 font-mono text-text-muted">
                {{ node.lat.toFixed(4) }}
              </td>
              <td class="text-right py-2 pl-4 font-mono text-text-muted">
                {{ node.lon.toFixed(4) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouteStore } from '@/stores/routeStore'

const store = useRouteStore()
</script>