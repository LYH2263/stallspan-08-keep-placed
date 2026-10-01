<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const data = ref<any>(null)
const vendors = ref<any[]>([])
const keepPlaced = ref(false)
const error = ref('')
const drawerOpen = ref(false)
const runs = ref<any[]>([])

function errText(e: any): string {
  try {
    const j = JSON.parse(e?.message || '')
    if (j?.detail) return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
  } catch { /* 非 JSON 错误体 */ }
  return e?.message || '分配失败'
}

async function loadLatest() {
  data.value = await api('/allocate/latest?segment_id=1')
}

async function run() {
  error.value = ''
  try {
    // 每次运行整体替换 data：保留/重算两种结果不混用，锁区只来自本次响应
    data.value = await api(`/allocate/run?segment_id=1&keep_placed=${keepPlaced.value}`, { method: 'POST' })
  } catch (e: any) {
    // 拒绝（如尚无成功运行）时图与放不下保持不变
    error.value = errText(e)
  }
}

async function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
  if (drawerOpen.value) runs.value = await api('/allocate/runs?segment_id=1')
}

async function openRun(id: number) {
  // 历史运行整体替换当前视图，不与本次结果混用
  data.value = await api(`/allocate/runs/${id}`)
  drawerOpen.value = false
}

onMounted(async () => {
  vendors.value = await api('/vendors')
  await loadLatest()
})

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
// 颜色按摊主固定：同一摊跨运行不漂色
const colorFor = (id: number) => colors[Math.abs(id) % colors.length]
const cells = computed(() => {
  if (!data.value) return []
  const width = data.value.segment.width_m
  const out: any[] = []
  for (const p of data.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const p of data.value.placements || []) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, locked: !!p.locked, color: colorFor(p.vendor_id) })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
const lockedCount = computed(() => (data.value?.placements || []).filter((p: any) => p.locked).length)
const fmtTime = (s?: string | null) => (s ? s.replace('T', ' ').slice(0, 19) : '')
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队</p>
    <div class="ss-run-bar">
      <label class="ss-keep-toggle">
        <input type="checkbox" v-model="keepPlaced" />
        保留已落摊（上次成功运行起止锁定）
      </label>
      <button class="btn" @click="run">重新分配</button>
      <button class="btn btn-ghost" @click="toggleDrawer">运行记录</button>
    </div>
    <p v-if="error" class="ss-error">{{ error }}</p>
    <p v-if="data" class="ss-run-meta-line">
      运行 #{{ data.id }} · {{ fmtTime(data.created_at) }} ·
      <span class="badge" :class="data.keep_placed ? 'badge-warn' : 'badge-ok'">
        {{ data.keep_placed ? '保留已落' : '整段重算' }}
      </span>
      <span v-if="lockedCount" class="badge badge-warn">锁区 {{ lockedCount }}</span>
    </p>
    <div class="ss-band-ruler" v-if="data">
      <span>0 m</span>
      <span>{{ data.segment.name }} · {{ data.segment.width_m }} m</span>
      <span>{{ data.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="data">
      <div class="ss-street-inner">
        <div
          v-for="(c,i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar', 'ss-locked': c.locked }"
          :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
        >{{ c.locked ? '🔒 ' : '' }}{{ c.label }}</div>
      </div>
    </div>
    <div class="ss-vendor-queue">
      <div v-for="v in vendors" :key="v.id" class="ss-vendor-chip">
        <strong>{{ v.name }}</strong>
        <span>需 {{ v.stall_width_m }} m · 优先 {{ v.priority }}</span>
      </div>
    </div>
    <div class="card" v-if="data">
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th><th>锁定</th></tr></thead>
        <tbody>
          <tr v-for="p in data.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
            <td>{{ p.locked ? '🔒' : '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="ss-drawer-mask" v-if="drawerOpen" @click="drawerOpen = false"></div>
    <aside class="ss-drawer" :class="{ open: drawerOpen }">
      <div class="ss-drawer-head">
        <strong>运行记录</strong>
        <button class="btn btn-ghost" @click="drawerOpen = false">收起</button>
      </div>
      <div
        v-for="r in runs" :key="r.id"
        class="ss-run-item"
        :class="{ active: data && data.id === r.id }"
        @click="openRun(r.id)"
      >
        <div class="ss-run-title">#{{ r.id }} · {{ fmtTime(r.created_at) }}</div>
        <div class="ss-run-meta">
          <span class="badge" :class="r.keep_placed ? 'badge-warn' : 'badge-ok'">
            {{ r.keep_placed ? '保留已落' : '整段重算' }}
          </span>
          <span>落 {{ r.placed }}</span>
          <span v-if="r.locked">锁 {{ r.locked }}</span>
          <span>拒 {{ r.rejected }}</span>
        </div>
      </div>
      <p v-if="!runs.length" class="muted">暂无运行</p>
    </aside>
  </div>
</template>
