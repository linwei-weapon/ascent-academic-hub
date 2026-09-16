<template>
  <el-dialog :model-value="open" title="讨论稿预览" class="research-material-dialog" width="min(980px, 96vw)" append-to-body @update:model-value="$emit('update:open', $event)">
    <p v-if="busy" role="status">正在整理所选版本的讨论稿……</p>
    <template v-if="material">
      <div v-if="material.stale" class="stale">这份材料形成于较早的研究版本。原稿保持不变，使用前请对照后续变化；可以关闭后重新整理。</div>
      <article v-if="material.snapshot.discussion_memo" class="paper memo-paper"><h1>{{ material.snapshot.discussion_memo.title || material.title }} · 讨论稿</h1><p class="meta">形成时间：{{ researchDate(material.created_at) }} · 本稿仅供研究讨论</p>
        <section v-for="(section, index) in material.snapshot.discussion_memo.sections" :key="section.title" :data-memo-section="index"><h2>{{ section.title }}</h2><p v-for="(text, i) in section.paragraphs" :key="i" class="body">{{ text }}</p></section>
        <details class="memo-appendix"><summary>附录：完整课程清单与计算资料（按需展开）</summary><section v-for="table in material.snapshot.discussion_memo.appendix_tables" :key="table.id"><details><summary>{{ table.title }} · {{ table.rows.length }}项</summary><div class="table-scroll" tabindex="0" :aria-label="table.title"><table><thead><tr><th v-for="column in table.columns" :key="column.key">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row, index) in table.rows" :key="index"><td v-for="column in table.columns" :key="column.key">{{ cell(row[column.key]) }}</td></tr></tbody></table></div><small>{{ table.note }}</small></details></section>
          <h3>资料来源</h3><p v-for="(source, i) in material.snapshot.discussion_memo.sources" :key="i">{{ source.file }} · {{ source.detail }}</p><h3>计算说明</h3><p v-for="method in material.snapshot.discussion_memo.methods" :key="method">{{ method }}</p>
        </details>
      </article>
      <article v-else class="paper"><h1>{{ material.title }}</h1><p class="meta">已保存讨论稿<br>{{ material.snapshot.result.scope_label }}<br>{{ material.snapshot.result.data_time_note }} {{ researchDate(material.snapshot.result.data_time) }}<br>形成时间：{{ researchDate(material.created_at) }}</p>
        <h2>一、目前可以明确的情况</h2><h3>{{ material.snapshot.result.headline }}</h3><p class="body">{{ material.snapshot.result.body || material.snapshot.result.management_note }}</p>
        <section v-for="table in material.snapshot.result.tables || []" :key="table.id"><h3>{{ table.title }}</h3><div class="table-scroll"><table><thead><tr><th v-for="column in table.columns" :key="column.key">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row, index) in table.rows" :key="index"><td v-for="column in table.columns" :key="column.key">{{ cell(row[column.key]) }}</td></tr></tbody></table></div><small>{{ table.note }}</small></section>
        <section v-if="material.snapshot.opinion?.text"><h2>当前想法</h2><p class="body">{{ material.snapshot.opinion.text }}</p><small>采用已保存意见版本 {{ material.opinion_revision }}</small></section>
        <section v-if="material.snapshot.questions?.length"><h2>尚需明确的事项</h2><ul><li v-for="question in material.snapshot.questions" :key="question.id">{{ question.text }}（{{ question.status === 'resolved' ? '已明确' : question.status === 'deferred' ? '暂缓' : '待明确' }}）</li></ul></section>
        <section><h2>附：计算口径与来源</h2><ul><li v-for="method in material.snapshot.result.methods || []" :key="method">{{ method }}</li><li v-for="source in material.snapshot.result.sources || []" :key="source.file">{{ source.file }} {{ source.detail }}</li></ul><p v-for="item in material.snapshot.result.limitations || []" :key="item">{{ item }}</p></section>
      </article>
    </template>
    <template #footer><span class="download-note">下载后可在Word中编辑，正式使用前请确认内容。</span><el-button @click="$emit('update:open', false)">返回研究</el-button><el-button type="primary" :disabled="!material" :loading="downloading" @click="download">下载可编辑Word稿</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { downloadResearchMaterial, researchDate, type ResearchMaterial } from '@/utils/expertResearch'
const props = defineProps<{ open: boolean; busy: boolean; material: ResearchMaterial | null }>()
const emit = defineEmits<{ 'update:open': [open: boolean]; error: [error: unknown] }>()
const downloading = ref(false)
const cell = (value: unknown) => value == null || value === '' ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value)
async function download() { if (!props.material || downloading.value) return; downloading.value = true; try { await downloadResearchMaterial(props.material.id) } catch (error) { emit('error', error) } finally { downloading.value = false } }
</script>
<style scoped>
.paper{max-height:64vh;overflow:auto;background:#fff;border:1px solid #e5e6eb;padding:28px 34px;color:#303745;font-size:14px;line-height:1.9}.paper h1{font-size:23px;text-align:center;margin:6px 0 20px}.paper h2{font-size:17px;margin-top:28px}.paper h3{font-size:15px}.meta{font-size:12px;color:#7b8290}.body{white-space:pre-wrap;overflow-wrap:anywhere}.paper section{margin:22px 0}.paper small{font-size:12px;color:#82858e}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #e5e5ec;padding:8px 10px;min-width:75px;text-align:left}th{background:#f7f7fa;font-weight:500}.stale{background:#fff8e6;color:#8b6d35;padding:12px 15px;font-size:13px;line-height:1.8;margin-bottom:15px}.download-note{font-size:12px;color:#818594;margin-right:16px;display:inline-block;margin-bottom:8px}
.meta,.paper small,.download-note{color:#667085}
.memo-appendix{border-top:1px solid #e1dce9;padding-top:18px;margin-top:28px}.memo-paper summary{cursor:pointer;color:#625078;font-weight:550}.memo-paper h1{overflow-wrap:anywhere}
:global(.research-material-dialog){display:flex;flex-direction:column;margin:4vh auto;max-height:92dvh;overflow:hidden}:global(.research-material-dialog .el-dialog__body){min-height:0;overflow:auto}:global(.research-material-dialog .el-dialog__footer){flex-shrink:0}.research-material-dialog .paper{max-height:58dvh}
</style>
