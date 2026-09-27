<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const isWriter = computed(() => role.value === 'writer')
const range = ref(null)
const jobs = ref([])
const history = ref([])
const err = ref('')
const ok = ref('')
const rangeForm = ref({ min_nm: 500, max_nm: 600 })
const editId = ref(null)
const editValue = ref(0)
const rangeLoaded = ref(false)
let timer

function fmt(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString()
}

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [r, j, h] = await Promise.all([
      api('/api/range'),
      api('/api/jobs'),
      api('/api/nominal-history'),
    ])
    range.value = r
    if (!rangeLoaded.value) {
      rangeForm.value.min_nm = r.min_nm
      rangeForm.value.max_nm = r.max_nm
      rangeLoaded.value = true
    }
    jobs.value = j
    history.value = h
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function saveRange() {
  err.value = ''
  ok.value = ''
  try {
    const r = await api('/api/range', {
      method: 'PUT',
      body: JSON.stringify({
        min_nm: Number(rangeForm.value.min_nm),
        max_nm: Number(rangeForm.value.max_nm),
      }),
    })
    range.value = r
    ok.value = `量程闭区间已保存：[${r.min_nm}, ${r.max_nm}] nm`
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function startEdit(job) {
  editId.value = job.id
  editValue.value = job.nominal_nm
}

function cancelEdit() {
  editId.value = null
}

async function saveNominal(job) {
  err.value = ''
  ok.value = ''
  try {
    await api(`/api/jobs/${job.id}/nominal`, {
      method: 'PUT',
      body: JSON.stringify({ nominal_nm: Number(editValue.value) }),
    })
    editId.value = null
    ok.value = `#${job.id} 标称已改，旧值保留在标称履历`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>量程台</h2>
    <p v-if="err" class="err">{{ err }}</p>
    <p v-if="ok" class="ok">{{ ok }}</p>

    <section class="panel">
      <h3>区间设置（闭区间）</h3>
      <p v-if="range">
        当前量程：<strong>[{{ range.min_nm }}, {{ range.max_nm }}] nm</strong>
        <span class="hint">（{{ range.updated_by }} 设置于 {{ fmt(range.updated_at) }}）</span>
      </p>
      <template v-if="isWriter">
        <label>下限 nm <input type="number" step="0.01" v-model.number="rangeForm.min_nm" /></label>
        <label>上限 nm <input type="number" step="0.01" v-model.number="rangeForm.max_nm" /></label>
        <button type="button" @click="saveRange">保存区间</button>
        <p class="hint">标称波长按闭区间卡量程：端点收下，区间外拒收。</p>
      </template>
      <p v-else class="hint">巡检员可查看区间，不可修改。</p>
    </section>

    <section class="panel">
      <h3>送检标称栏</h3>
      <p class="hint">送检任务的当前标称；校准员可改行上标称，旧值留在标称履历。</p>
      <table border="1" cellpadding="6">
        <thead>
          <tr>
            <th>编号</th><th>灯种</th><th>当前标称 nm</th><th>状态</th><th>结论</th>
            <th v-if="isWriter">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.lamp }}</td>
            <td>
              <input
                v-if="editId === j.id"
                type="number"
                step="0.01"
                v-model.number="editValue"
                style="width: 100px"
              />
              <template v-else>{{ j.nominal_nm }}</template>
            </td>
            <td>{{ j.status }}</td>
            <td>{{ j.verdict }}</td>
            <td v-if="isWriter">
              <template v-if="editId === j.id">
                <button type="button" @click="saveNominal(j)">保存</button>
                <button type="button" @click="cancelEdit">取消</button>
              </template>
              <button v-else type="button" @click="startEdit(j)">改标称</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3>标称履历</h3>
      <p class="hint">送检标称原文进履历；事后改标称只追加新行，履历旧值不动。</p>
      <table border="1" cellpadding="6">
        <thead>
          <tr>
            <th>履历号</th><th>任务</th><th>灯种</th><th>标称原文 nm</th>
            <th>事件</th><th>记录人</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>{{ h.id }}</td>
            <td>#{{ h.job_id }}</td>
            <td>{{ h.lamp }}</td>
            <td>{{ h.nominal_nm }}</td>
            <td>{{ h.event }}</td>
            <td>{{ h.recorded_by }}</td>
            <td>{{ fmt(h.recorded_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.panel {
  margin: 16px 0;
  padding: 12px;
  border: 1px solid #ccc;
}
.panel label {
  display: inline-block;
  margin-right: 12px;
}
.panel table {
  border-collapse: collapse;
  width: 100%;
}
.hint {
  color: #666;
  font-size: 13px;
}
.err {
  color: #b00020;
}
.ok {
  color: #1b7f3b;
}
</style>
