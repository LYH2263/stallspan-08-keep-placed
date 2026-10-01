<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

interface RunResp {
  id: number
  created_at?: string
  preserve?: boolean
  baseline_run_id?: number | null
  segment: { id: number; name: string; width_m: number }
  pillars: { position_m: number; thickness_m: number; label?: string }[]
  placements: { vendor_id: number; vendor_name: string; start_m: number; end_m: number; width_m: number; locked?: boolean }[]
  rejected: { vendor_id: number; vendor_name: string; width_m: number; reason: string; lock_conflict?: boolean }[]
  free_spans: { start_m: number; end_m: number }[]
}
interface RunMeta {
  id: number
  created_at: string
  preserve: boolean
  baseline_run_id: number | null
  placed_count: number
  locked_count: number
  rejected_count: number
  lock_conflict_count: number
}

const data = ref<RunResp | null>(null)
const vendors = ref<any[]>([])
const preserve = ref(false)
const busy = ref(false)
const errorMsg = ref('')
const viewingId = ref<number | null>(null)

const runs = ref<RunMeta[]>([])
const drawerOpen = ref(false)

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
// 颜色按摊主 id 固定，连续保留重跑时锁摊色块不漂移。
const colorOf = (vendorId: number) => {
  const idx = vendors.value.findIndex(v => v.id === vendorId)
  const key = idx >= 0 ? idx : Math.abs(vendorId)
  return colors[key % colors.length]
}

const cells = computed(() => {
  if (!data.value) return []
  const width = data.value.segment.width_m
  const out: any[] = []
  for (const p of data.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m / 2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const p of data.value.placements || []) {
    // 是否锁区只认本次结果里的 locked 标志（同源 result_json），与勾选框状态无关。
    out.push({
      type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name,
      locked: !!p.locked, color: colorOf(p.vendor_id),
    })
  }
  return out.sort((a, b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})

async function refreshRuns() {
  runs.value = await api<RunMeta[]>('/allocate/runs?segment_id=1')
}

async function run() {
  if (busy.value) return
  busy.value = true
  errorMsg.value = ''
  try {
    const resp = await api<RunResp>(`/allocate/run?segment_id=1&preserve=${preserve.value ? 'true' : 'false'}`, { method: 'POST' })
    data.value = resp
    viewingId.value = resp.id
    await refreshRuns()
  } catch (e: any) {
    // 保留为真但无成功运行 → 409：图与放不下维持原状，禁止半成功。
    errorMsg.value = e?.status === 409
      ? '保留被拒绝：尚无成功运行可保留，请先取消保留跑一次整段分配。'
      : ('分配失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function openRun(id: number) {
  const snap = await api<RunResp>(`/allocate/runs/${id}`)
  // 仅查看旧运行快照：不重算、不写库，旧非保留运行也不会被本次保留结果污染。
  data.value = snap
  viewingId.value = id
  drawerOpen.value = false
}

async function backToLatest() {
  const latest = await api<RunResp>('/allocate/latest?segment_id=1')
  data.value = latest
  viewingId.value = latest.id
}

onMounted(async () => {
  vendors.value = await api('/vendors')
  data.value = await api<RunResp>('/allocate/latest?segment_id=1')
  viewingId.value = data.value.id
  await refreshRuns()
})
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队</p>
    <div class="ss-run-bar">
      <label class="ss-preserve-check" title="勾选后上次成功运行的已落摊起止锁定，本轮只填其余空档">
        <input type="checkbox" v-model="preserve" />
        <span>保留上次已落摊（锁区，不从左挪摊）</span>
      </label>
      <button class="btn" :disabled="busy" @click="run">{{ preserve ? '保留重跑' : '重新分配' }}</button>
      <button class="btn btn-ghost" @click="drawerOpen = !drawerOpen">运行抽屉（{{ runs.length }}）</button>
      <button v-if="viewingId !== null && runs.length && viewingId !== runs[0].id" class="btn btn-ghost" @click="backToLatest">
        返回最新
      </button>
    </div>
    <p v-if="errorMsg" class="ss-error">{{ errorMsg }}</p>

    <transition name="ss-drawer-fade">
      <aside v-if="drawerOpen" class="ss-drawer">
        <div class="ss-drawer-head">
          <strong>历史运行</strong>
          <button class="ss-drawer-close" @click="drawerOpen = false">×</button>
        </div>
        <ul class="ss-drawer-list">
          <li v-for="r in runs" :key="r.id"
              :class="{ active: r.id === viewingId }"
              @click="openRun(r.id)">
            <div class="ss-drawer-title">
              <span class="ss-run-id">#{{ r.id }}</span>
              <span class="badge" :class="r.preserve ? 'badge-warn' : 'badge-ok'">
                {{ r.preserve ? '保留' : '整段重算' }}
              </span>
              <span v-if="r.preserve" class="muted ss-baseline">基于 #{{ r.baseline_run_id }}</span>
            </div>
            <div class="muted ss-run-meta">
              {{ new Date(r.created_at).toLocaleString() }} ·
              已落 {{ r.placed_count }}（锁 {{ r.locked_count }}）·
              放不下 {{ r.rejected_count }}
              <template v-if="r.lock_conflict_count"> · <span class="ss-lock-text">锁区冲突 {{ r.lock_conflict_count }}</span></template>
            </div>
          </li>
          <li v-if="!runs.length" class="muted">尚无运行</li>
        </ul>
      </aside>
    </transition>

    <div class="ss-band-ruler" v-if="data">
      <span>0 m</span>
      <span>
        {{ data.segment.name }} · {{ data.segment.width_m }} m ·
        <span class="badge" :class="data.preserve ? 'badge-warn' : 'badge-ok'">{{ data.preserve ? '保留运行 #' + data.id : '整段重算 #' + data.id }}</span>
      </span>
      <span>{{ data.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="data">
      <div class="ss-street-inner">
        <div
          v-for="(c, i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar', 'ss-locked': c.locked }"
          :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
        >
          <span v-if="c.locked" class="ss-lock-tag">锁</span>{{ c.label }}
        </div>
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
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="p in data.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td>
            <td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
            <td>
              <span v-if="p.locked" class="badge badge-warn">锁定保留</span>
              <span v-else class="badge badge-ok">本轮新落</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card" v-if="data && data.rejected.length">
      <h2 class="ss-card-title">放不下（{{ data.rejected.length }}）</h2>
      <table>
        <thead><tr><th>摊主</th><th>需求宽度</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="r in data.rejected" :key="r.vendor_id">
            <td>{{ r.vendor_name }}</td>
            <td>{{ r.width_m }}</td>
            <td>
              <span class="badge" :class="r.lock_conflict ? 'badge-bad' : 'badge-warn'">
                {{ r.lock_conflict ? '锁区冲突' : '空档不够' }}
              </span>
              {{ r.reason }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
