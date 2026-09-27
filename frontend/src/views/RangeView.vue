<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const range = ref(null)
const jobs = ref([])
const history = ref([])
const err = ref('')
const ok = ref('')
const rangeForm = ref({ lower_nm: 500, upper_nm: 600 })
let formTouched = false
let timer

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [r, j, h] = await Promise.all([
      api('/api/range'),
      api('/api/jobs'),
      api('/api/nominal-history'),
    ])
    range.value = r
    jobs.value = j
    history.value = h
    if (!formTouched) {
      rangeForm.value = { lower_nm: r.lower_nm, upper_nm: r.upper_nm }
    }
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function markTouched() {
  formTouched = true
}

async function saveRange() {
  err.value = ''
  ok.value = ''
  try {
    await api('/api/range', {
      method: 'PUT',
      body: JSON.stringify({
        lower_nm: Number(rangeForm.value.lower_nm),
        upper_nm: Number(rangeForm.value.upper_nm),
      }),
    })
    ok.value = '量程闭区间已保存'
    formTouched = false
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function fmtTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 19)
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>量程台</h2>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="ok" style="color:#1a7f37">{{ ok }}</p>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>区间设置（闭区间）</h3>
      <p v-if="range">
        当前量程闭区间：<strong>[{{ range.lower_nm }}, {{ range.upper_nm }}]</strong> nm
        <span style="color:#666; font-size:13px;">
          （{{ range.updated_by }} 更新于 {{ fmtTime(range.updated_at) }}）
        </span>
      </p>
      <template v-if="role === 'writer'">
        <label>下限 nm
          <input type="number" step="0.01" v-model.number="rangeForm.lower_nm" @input="markTouched" />
        </label>
        <label>上限 nm
          <input type="number" step="0.01" v-model.number="rangeForm.upper_nm" @input="markTouched" />
        </label>
        <button type="button" @click="saveRange">保存区间</button>
        <p class="hint">标称波长落在闭区间之外一律拒收。</p>
      </template>
      <p v-else class="hint">巡检员仅可查看区间，不可修改。</p>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>送检标称栏</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>编号</th><th>灯种</th><th>标称 nm</th><th>区间内</th></tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.lamp }}</td>
            <td>{{ j.nominal_nm }}</td>
            <td>
              <template v-if="range">
                {{ j.nominal_nm >= range.lower_nm && j.nominal_nm <= range.upper_nm ? '是' : '否' }}
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>标称履历</h3>
      <p class="hint">送检时标称原文即入履历；事后改行上标称，履历旧值不动。</p>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>序号</th><th>任务编号</th><th>标称 nm</th><th>事件</th><th>记录人</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>{{ h.id }}</td>
            <td>{{ h.job_id }}</td>
            <td>{{ h.nominal_nm }}</td>
            <td>{{ h.event === 'submit' ? '送检' : '改标称' }}</td>
            <td>{{ h.recorded_by }}</td>
            <td>{{ fmtTime(h.recorded_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.hint {
  color: #666;
  font-size: 13px;
}
label {
  margin-right: 12px;
}
</style>
