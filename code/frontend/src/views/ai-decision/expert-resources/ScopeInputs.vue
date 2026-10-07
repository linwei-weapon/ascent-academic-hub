<template>
  <fieldset class="scope-fields" :aria-busy="loading" :disabled="disabled">
    <label v-for="[key, field] in primaryFields" :key="key" class="scope-field">
      <span>{{ fieldTitle(key,field) }}<em v-if="schema?.required?.includes(key)"> *</em></span>
      <el-select-v2 v-if="isOptionField(key)" :model-value="selectValue(key)" :options="optionsFor(key).map(option=>({label:option.name,value:option.id}))" filterable clearable :loading="fieldLoading(key)" :disabled="disabled || fieldLoading(key) || !optionsFor(key).length" :placeholder="placeholder(key,field)" @update:model-value="set(key, $event)" />
      <div v-else-if="field.enum?.length===1" class="fixed-value">{{ field.enum[0]==='all_course_ids'?'按全部课程编号去重比较':String(field.enum[0]) }}</div>
      <el-select v-else-if="field.enum" :model-value="selectValue(key)" :disabled="disabled" clearable placeholder="请选择" @update:model-value="set(key, $event)"><el-option v-for="value in field.enum" :key="value" :label="value==='all_course_ids'?'按全部课程编号去重比较':String(value)" :value="value" /></el-select>
      <el-input-number v-else-if="field.type === 'integer' || field.type === 'number'" :model-value="Number(modelValue[key] ?? field.default ?? 20)" :disabled="disabled" :min="1" :max="200" @update:model-value="set(key, $event)" />
      <el-input v-else :model-value="String(modelValue[key] ?? '')" :disabled="disabled" clearable :placeholder="field.description || '请输入'" @update:model-value="set(key, $event)" />
      <small v-if="hints[key] || field.description">{{ hints[key] || field.description }}</small>
    </label>
    <details v-if="advancedFields.length" class="display-options">
      <summary>展示设置（当前 {{ modelValue.previewLimit ?? modelValue.limit ?? 50 }} 条）</summary>
      <label v-for="[key,field] in advancedFields" :key="key" class="scope-field">
        <span>{{ fieldTitle(key,field) }}</span>
        <el-input-number :model-value="Number(modelValue[key] ?? field.default ?? 50)" :disabled="disabled" :min="1" :max="200" @update:model-value="set(key,$event)" />
        <small>只改变预览条数，计算范围和保存证据保持完整。</small>
      </label>
    </details>
    <p v-if="!fields.length" class="scope-note">本方法按当前登录身份的授权范围查询，无需额外参数。</p>
  </fieldset>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { ResourceOptions, ResourceSchema } from '@/types/expertResources'
import { schemaFieldLabel } from './presentation'
const props = defineProps<{ modelValue: Record<string, unknown>; schema?: ResourceSchema; options: ResourceOptions; loading?: boolean; failed?: boolean; disabled?: boolean; compact?:boolean; courseLoading?:boolean; courseError?:string }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()
const hints: Record<string,string> = {plan_id:'可输入名称或适用年级检索当前授权范围内的方案。',target_plan_id:'选择需要对照的另一份培养方案。',semester_id:'仅显示当前已有分析数据的学期。',college_id:'不选择时，按当前身份已获授权的范围查询。',course_id:'按课程名称或编号检索；留空查看所选范围全部课程。',limit:'控制本次明细展示条数，不改变指标计算范围。'}
const fields = computed(() => Object.entries(props.schema?.properties || {}).filter(([key]) => !['skill_id', 'question'].includes(key)))
const advancedFields=computed(()=>props.compact?fields.value.filter(([key])=>['previewLimit','limit'].includes(key)):[])
const primaryFields=computed(()=>fields.value.filter(([key])=>!advancedFields.value.some(([advanced])=>advanced===key)).sort(([a],[b])=>Number(props.schema?.required?.includes(b))-Number(props.schema?.required?.includes(a))))
const fieldTitle=(key:string,field:ResourceSchema)=>key==='course_id'&&props.options.courses!==undefined?(props.schema?.required?.includes(key)?'指定课程':'指定课程（可选）'):schemaFieldLabel(key,field,props.schema?.required?.includes(key))
const fieldLoading=(key:string)=>props.loading||(key==='course_id'&&props.courseLoading)
function placeholder(key:string,field:ResourceSchema){if(key==='course_id'&&!props.modelValue.semester_id)return '先选择分析学期';if(fieldLoading(key))return '正在加载可选范围';if(props.failed||key==='course_id'&&props.courseError)return '范围加载失败，请重试';return optionsFor(key).length?`检索并选择${fieldTitle(key,field)}`:`暂无可选${fieldTitle(key,field)}`}
function set(key: string, value: unknown) { const next = { ...props.modelValue }; if (value === '' || value == null) delete next[key]; else next[key] = value; emit('update:modelValue', next) }
function selectValue(key: string): string | number | undefined { const value = props.modelValue[key]; return typeof value === 'string' || typeof value === 'number' ? value : undefined }
const isOptionField = (key:string) => ['plan_id','target_plan_id','semester_id','college_id'].includes(key)||key==='course_id'&&props.options.courses!==undefined
function optionsFor(key: string) { return ['plan_id', 'target_plan_id'].includes(key) ? (props.options.plans || []).map(item=>({...item,name:`${item.name}${item.grade == null || item.grade === '' ? '' : ` · ${item.grade}级`}`})) : key === 'semester_id' ? props.options.semesters || [] : key === 'college_id' ? props.options.colleges || [] : key==='course_id'?(props.options.courses||[]).map(item=>({...item,name:`${item.name} · ${item.id}`})):[] }
</script>
<style scoped>
.scope-fields{padding:0;margin:0;border:0;min-width:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.scope-field{display:flex;flex-direction:column;gap:7px;font-size:14px;color:#334155}.scope-field em{font-style:normal;color:#b54708}.scope-field small,.scope-note{font-size:12px;color:#64748b;line-height:1.6}.scope-field .el-select,.scope-field .el-select-v2,.scope-field .el-input-number{width:100%}.fixed-value{padding:7px 11px;background:#f5f7fa;border:1px solid #e2e8f0;border-radius:4px;font-size:13px}.scope-note{grid-column:1/-1;margin:0}.display-options{grid-column:1/-1;color:#64748b;font-size:12px}.display-options summary{cursor:pointer}.display-options label{margin-top:10px}summary:focus-visible{outline:2px solid #344b77;outline-offset:3px}@media(max-width:650px){.scope-fields{grid-template-columns:1fr}}
</style>
