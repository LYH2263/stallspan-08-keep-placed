<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const runInfo = ref<any>(null)
onMounted(async () => {
  const data = await api('/allocate/latest?segment_id=1')
  runInfo.value = data
  rows.value = data.rejected || []
})
const isLockConflict = (reason: string) => (reason || '').includes('锁区冲突')
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">无法在连续空档内安置且不跨越挡柱的摊位</p>
  <p v-if="runInfo" class="ss-run-meta-line">
    运行 #{{ runInfo.id }} ·
    <span class="badge" :class="runInfo.keep_placed ? 'badge-warn' : 'badge-ok'">
      {{ runInfo.keep_placed ? '保留已落' : '整段重算' }}
    </span>
  </p>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
          <td>
            <span v-if="isLockConflict(r.reason)" class="badge badge-bad">{{ r.reason }}</span>
            <template v-else>{{ r.reason }}</template>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>
</template>
