<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()
const job = ref(null)
const history = ref([])
const err = ref('')

function fmt(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString()
}

async function load() {
  err.value = ''
  job.value = null
  history.value = []
  try {
    const [j, h] = await Promise.all([
      api(`/api/jobs/${route.params.id}`),
      api('/api/nominal-history'),
    ])
    job.value = j
    history.value = h.filter((x) => x.job_id === j.id)
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <div>
    <p>
      <button type="button" @click="router.push('/')">返回总览</button>
    </p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>任务详情 #{{ job.id }}</h3>
      <p>灯种：{{ job.lamp }}</p>
      <p>标称 nm：{{ job.nominal_nm }}</p>
      <p>实测 nm：{{ job.measured_nm }}</p>
      <p>状态：{{ job.status }}</p>
      <p>结论：{{ job.verdict }}</p>
      <p>理由：{{ job.reason }}</p>
    </section>
    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>标称履历</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>履历号</th><th>标称原文 nm</th><th>事件</th><th>记录人</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>{{ h.id }}</td>
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
