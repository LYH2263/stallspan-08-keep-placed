<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const run = ref<any>(null)
onMounted(async () => {
  const data = await api('/allocate/latest?segment_id=1')
  run.value = data
  rows.value = data.rejected || []
})
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">
    无法在连续空档内安置且不跨越挡柱的摊位 ·
    最新运行 #{{ run?.id }}
    <span class="badge" :class="run?.preserve ? 'badge-warn' : 'badge-ok'">{{ run?.preserve ? '保留' : '整段重算' }}</span>
  </p>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
          <td>
            <span class="badge" :class="r.lock_conflict ? 'badge-bad' : 'badge-warn'">
              {{ r.lock_conflict ? '锁区冲突' : '空档不够' }}
            </span>
            {{ r.reason }}
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>
</template>
