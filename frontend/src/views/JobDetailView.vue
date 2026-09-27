<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const job = ref(null)
const err = ref('')
const ok = ref('')
const editNominal = ref(null)

async function load() {
  err.value = ''
  job.value = null
  try {
    job.value = await api(`/api/jobs/${route.params.id}`)
    editNominal.value = job.value.nominal_nm
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function saveNominal() {
  err.value = ''
  ok.value = ''
  try {
    await api(`/api/jobs/${route.params.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ nominal_nm: Number(editNominal.value) }),
    })
    ok.value = '标称已更新；标称履历中的旧值保持不变。'
    await load()
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
    <p v-if="ok" style="color:#1a7f37">{{ ok }}</p>
    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>任务详情 #{{ job.id }}</h3>
      <p>灯种：{{ job.lamp }}</p>
      <p>标称 nm：{{ job.nominal_nm }}</p>
      <p>实测 nm：{{ job.measured_nm }}</p>
      <p>状态：{{ job.status }}</p>
      <p>结论：{{ job.verdict }}</p>
      <p>理由：{{ job.reason }}</p>
    </section>
    <section v-if="job && role === 'writer'" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>改行上标称</h3>
      <label>新标称 nm
        <input type="number" step="0.01" v-model.number="editNominal" />
      </label>
      <button type="button" @click="saveNominal">保存标称</button>
      <p style="color:#666; font-size:13px;">
        新标称仍须落在量程闭区间内；修改只追加履历，履历旧值不动。
      </p>
    </section>
  </div>
</template>
