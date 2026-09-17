<!-- 专家团研究工作区：保留来源提交的业务与交互，归入 AI 管理决策模块。 -->
<template>
  <el-dialog :model-value="open" :title="selected ? selected.name : '选择参与讨论的专家'" width="min(960px, 94vw)" top="5vh" class="expert-picker-dialog" append-to-body @update:model-value="$emit('update:open', $event)" @closed="reset">
    <div v-if="!selected">
      <p class="intro">按你关心的问题选择专家。各位专家在同一场讨论中协作，不必分别建立对话。</p>
      <div class="picker-toolbar">
        <div class="picker-tabs" aria-label="专家范围"><button :class="{ active: !joinedOnly }" :aria-pressed="!joinedOnly" @click="joinedOnly = false">全部专家 <span>{{ experts.length }}</span></button><button :class="{ active: joinedOnly }" :aria-pressed="joinedOnly" @click="joinedOnly = true">本次已加入 <span>{{ participants.filter(p => p.status === 'active').length }}</span></button></div>
        <el-input v-model="query" placeholder="查找专家或问题，例如课程重复" clearable aria-label="搜索专家职责" />
      </div>
      <div class="experts" aria-label="专家卡片列表">
        <article v-for="expert in filtered" :key="expert.id" class="expert-card" :class="{ unavailable: !expert.enabled, joined: state(expert.id) === 'active' }">
          <button class="card-details" :aria-label="expert.name + '，查看详情'" @click="inspect(expert)">
            <div class="expert-heading"><ExpertAvatar :id="expert.id" /><span class="expert-heading-copy"><strong>{{ expert.name }}</strong><small :class="{ available: expert.enabled }">{{ state(expert.id) === 'active' ? '已加入本次讨论' : !expert.enabled ? '资料待准备' : state(expert.id) === 'excluded' ? '已停止自动参与' : '可辅助研究' }}</small></span></div>
            <p>{{ expert.purpose }}</p>
            <div class="skill-tags"><span v-for="scenario in previewScenes(expert)" :key="scenario.id">{{ scenario.name }}</span></div>
            <span class="details-hint">查看职责、适用问题与资料要求 <el-icon><ArrowRight /></el-icon></span>
          </button>
          <div class="card-actions">
            <button v-if="researchId && expert.enabled" class="join-button" :disabled="saving || readonly" @click="$emit('participate', expert.id, state(expert.id) === 'active' ? 'exclude' : 'add')">{{ state(expert.id) === 'active' ? '停止自动参与' : '加入本次讨论' }}</button>
            <small v-else class="card-note">{{ expert.enabled ? '选择后先准备问题' : '可先了解职责与所需资料' }}</small>
            <el-button v-if="expert.enabled" type="primary" plain :disabled="readonly" @click="$emit('direct', expert)">{{ researchId ? '选择他来补充' : '选择这位专家' }}</el-button>
            <el-button v-else @click="inspect(expert)">了解详情</el-button>
          </div>
        </article>
        <div v-if="!filtered.length" class="no-experts"><h3>{{ joinedOnly ? '尚无符合条件的参与专家' : '暂未找到对应专家' }}</h3><p>{{ joinedOnly ? '可以从全部专家中选择，或直接提出问题。' : '换一个专家名称或业务问题试试。' }}</p><el-button @click="query = ''; joinedOnly = false">查看全部专家</el-button></div>
      </div>
    </div>
    <div v-else class="expert-detail">
      <button ref="backButton" class="back-button" @click="backToCards"><el-icon><ArrowLeft /></el-icon> 返回专家列表</button>
      <div class="detail-heading"><ExpertAvatar :id="selected.id" /><div><h3>{{ selected.name }}</h3><p>{{ selected.purpose }}</p></div></div>
      <div class="detail-boundary"><b>{{ selected.enabled ? '当前可以辅助研究' : '暂未开放分析' }}</b><p>{{ selected.availability }}。{{ selected.enabled ? '具体能回答到哪一步，仍取决于本次选择的专业、年级与资料。' : '所需资料准备完成前，不生成正式分析结论。' }}</p></div>
      <h4>适合研究的问题</h4>
      <ul class="scenario-list"><li v-for="scenario in selected.scenarios" :key="scenario.id"><div><b>{{ scenario.name }}</b><small>{{ scenario.release === 'deferred' ? '暂未开放' : '依现有资料研究' }}</small></div><p>{{ scenario.description }}</p><p v-if="scenario.missing?.length" class="missing">还需：{{ scenario.missing.join('；') }}</p></li></ul>
      <section v-if="selected.enabled && selected.question" class="example-question"><h4>可以从这个问题开始</h4><p>{{ selected.question }}</p><small>已有问题文字不会被替换。返回讨论后，可修改问题再发送。</small></section>
    </div>
    <template #footer>
      <div class="picker-footer"><p>{{ readonly ? '本研究已归档，恢复后可以继续讨论。' : '选择后返回讨论区，可修改问题并发送。' }}</p><el-button v-if="selected?.enabled" type="primary" :disabled="readonly" @click="$emit('direct', selected)">{{ researchId ? '选择他来补充' : '选择这位专家' }}</el-button><el-button v-else @click="$emit('update:open', false)">返回讨论</el-button></div>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import type { Research, ResearchExpert } from '@/types/expertResearch'
import ExpertAvatar from './ExpertAvatar.vue'
const props = defineProps<{ open: boolean; experts: ResearchExpert[]; participants: Research['participants']; researchId?: string; saving?: boolean; readonly?: boolean }>()
defineEmits<{ 'update:open': [open: boolean]; participate: [id: string, action: 'add' | 'exclude']; direct: [expert: ResearchExpert] }>()
const query = ref(''), joinedOnly = ref(false), selectedId = ref(''), backButton = ref<HTMLButtonElement>()
const selected = computed(() => props.experts.find(e => e.id === selectedId.value))
const state = (id: string) => props.participants.find(p => p.expert_id === id)?.status
const filtered = computed(() => props.experts.filter(e => (!joinedOnly.value || state(e.id) === 'active') && `${e.name} ${e.purpose} ${e.question} ${e.scenarios.map(s => s.name + s.description).join(' ')}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const previewScenes = (expert: ResearchExpert) => (expert.enabled ? expert.scenarios.filter(s => s.release !== 'deferred') : expert.scenarios).slice(0, 3)
let returnExpertId = ''
async function inspect(expert: ResearchExpert) { returnExpertId = expert.id; selectedId.value = expert.id; await nextTick(); backButton.value?.focus() }
async function backToCards() { selectedId.value = ''; await nextTick(); const cards = document.querySelectorAll<HTMLButtonElement>('.expert-picker-dialog .card-details'); Array.from(cards).find(card => card.getAttribute('aria-label') === props.experts.find(e => e.id === returnExpertId)?.name + '，查看详情')?.focus() }
function reset() { query.value = ''; joinedOnly.value = false; selectedId.value = ''; returnExpertId = '' }
</script>
<style lang="scss">
.expert-picker-dialog{max-height:90dvh;display:flex;flex-direction:column;overflow:hidden;border-radius:16px;padding:24px}.expert-picker-dialog .el-dialog__header{flex-shrink:0;padding-bottom:12px}.expert-picker-dialog .el-dialog__title{font-size:20px;font-weight:600;color:#342c44}.expert-picker-dialog .el-dialog__body{min-height:0;overflow:auto;padding:0}.expert-picker-dialog .el-dialog__footer{flex-shrink:0;padding-top:14px}
@media(max-height:680px){.expert-picker-dialog{padding:16px}.expert-picker-dialog .el-dialog__header{padding-bottom:8px}.expert-picker-dialog .el-dialog__footer{padding-top:8px}}
</style>
<style lang="scss" scoped>
.intro{font-size:14px;line-height:1.8;color:#6b6476;margin:0 0 18px}.picker-toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:18px}.picker-toolbar .el-input{max-width:325px}.picker-tabs{display:flex;gap:5px;flex-shrink:0}.picker-tabs button{border:0;border-radius:7px;background:transparent;padding:9px 11px;font:inherit;color:#6b6476;cursor:pointer;font-size:13px}.picker-tabs button.active{color:#674986;background:#f0ebf7;font-weight:600}.picker-tabs span{margin-left:5px;font-size:12px}
.experts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px;padding:2px}.expert-card{min-width:0;border:1px solid #e4dfeb;border-radius:12px;background:#fff;display:flex;flex-direction:column;overflow:hidden;transition:border-color .15s,box-shadow .15s}.expert-card:hover{border-color:#b8a6cf;box-shadow:0 4px 16px #44315f0a}.expert-card.joined{border-color:#b9a6d1;background:#fdfbff}.card-details{padding:20px 20px 14px;border:0;background:none;text-align:left;cursor:pointer;font:inherit;width:100%;flex:1;color:#52495f}.expert-heading{display:flex;align-items:center;gap:13px}.expert-heading-copy{display:flex;flex-direction:column;gap:6px}.expert-heading strong{font-size:16px;line-height:1.4;font-weight:600;color:#352b45}.expert-heading small{font-size:12px;color:#8b6d38}.expert-heading small.available{color:#6f5b84}.card-details p{font-size:14px;line-height:1.8;margin:16px 0 12px;min-height:50px}.skill-tags{display:flex;flex-wrap:wrap;gap:6px;min-height:27px}.skill-tags span{padding:4px 8px;background:#f4f2f7;border-radius:5px;font-size:12px;color:#686071;line-height:1.5}.details-hint{font-size:12px;color:#746380;display:flex;align-items:center;gap:5px;margin-top:17px}
.card-actions{display:flex;justify-content:space-between;align-items:center;gap:10px;border-top:1px solid #efebf3;margin:0 20px;padding:14px 0}.card-actions .el-button{margin-left:auto}.join-button,.back-button{border:0;background:none;font:inherit;font-size:13px;color:#73588e;cursor:pointer;padding:6px 0}.join-button:disabled{color:#86818d;cursor:not-allowed}.card-note{font-size:12px;line-height:1.6;color:#777080}.unavailable{background:#fcfbfd}.unavailable .expert-avatar{filter:saturate(.55)}button:focus-visible{outline:2px solid #8060a6;outline-offset:-3px}.no-experts{grid-column:1/-1;text-align:center;padding:45px 20px;color:#6b6476}.no-experts h3{font-size:16px}.no-experts p{font-size:14px}.picker-footer{border-top:1px solid #eee9f2;padding-top:14px;display:flex;align-items:center;justify-content:space-between;gap:20px;text-align:left}.picker-footer p{font-size:12px;line-height:1.8;color:#6b6476;margin:0}
.back-button{display:flex;align-items:center;gap:7px;margin-bottom:20px}.detail-heading{display:flex;gap:16px;align-items:center}.detail-heading h3{font-size:20px;color:#352b45;margin:0 0 8px}.detail-heading p{font-size:14px;color:#675e73;line-height:1.8;margin:0}.detail-boundary{padding:14px 16px;margin:20px 0;background:#f7f4fb;border:1px solid #e9e0f2;border-radius:9px;font-size:13px;color:#655673}.detail-boundary p{line-height:1.85;margin:6px 0 0}.expert-detail h4{font-size:14px;color:#4c415b;margin:20px 0 10px}.scenario-list{list-style:none;padding:0;margin:0}.scenario-list li{padding:14px 0;border-bottom:1px solid #eee9f3}.scenario-list li>div{display:flex;gap:16px;align-items:center}.scenario-list b{font-size:14px;color:#51465f}.scenario-list small{font-size:12px;color:#806b8f}.scenario-list p{font-size:14px;line-height:1.85;color:#675e73;margin:7px 0 0}.scenario-list p.missing{font-size:13px;color:#866835}.example-question{background:#f8f7fb;border-radius:9px;padding:1px 16px 16px;margin-top:20px}.example-question p{font-size:14px;line-height:1.9;color:#51465f}.example-question small{font-size:12px;color:#71677c}
@media(max-width:720px){.experts{grid-template-columns:1fr}.picker-toolbar{flex-direction:column;align-items:stretch;gap:12px}.picker-toolbar .el-input{max-width:none}.picker-footer{gap:12px}.card-details p{min-height:0}}@media(prefers-reduced-motion:reduce){.expert-card{transition:none}}
@media(max-height:680px){.intro{margin-bottom:10px;font-size:13px}.picker-toolbar{margin-bottom:10px}.card-details{padding:14px 16px 10px}.card-details p{min-height:0;margin:10px 0;line-height:1.65}.details-hint{margin-top:10px}.card-actions{margin:0 16px;padding:10px 0}.picker-footer{padding-top:8px}.skill-tags{min-height:0}}
.intro,.card-details,.detail-heading p,.scenario-list p,.picker-footer p{color:#475569}.expert-heading strong,.detail-heading h3,.scenario-list b{color:#1e293b}.expert-card{border-color:#e2e8f0}.expert-card:hover,.expert-card.joined{border-color:#a5b4fc}.expert-card.joined{background:#f8faff}.picker-tabs button.active{background:#eef2ff;color:#4f46e5}.skill-tags span{background:#f1f5f9;color:#475569}.details-hint,.join-button,.back-button,.expert-heading small.available{color:#4f46e5}.join-button,.back-button{min-height:36px;font-size:14px}.card-note,.picker-footer p,.expert-heading small,.details-hint{font-size:13px}.detail-boundary{background:#f8fafc;border-color:#e2e8f0;color:#475569}.example-question{background:#f8fafc}.card-actions{border-color:#e2e8f0}button:focus-visible{outline-color:#4f46e5}
</style>
