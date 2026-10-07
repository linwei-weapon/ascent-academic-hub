<template>
  <section class="rules-view">
    <p class="hint">规则说明用于解释处理口径；实际查询与计算由已登记方法执行。修改说明后仍需保存、测试与发布。</p>
    <template v-if="editable">
      <article v-for="(rule,index) in entries" :key="index" class="rule-editor">
        <div class="rule-fields"><label>分类<el-select :model-value="rule.group" @update:model-value="update(index,'group',$event)"><el-option v-for="group in groups" :key="group.id" :label="group.label" :value="group.id" /></el-select></label><label>标题（可选）<el-input :model-value="rule.title" @update:model-value="update(index,'title',$event)" /></label></div>
        <label>第 {{ index+1 }} 条说明<el-input type="textarea" :autosize="{minRows:2,maxRows:8}" :model-value="rule.text" @update:model-value="update(index,'text',$event)" /></label>
        <el-button text type="danger" @click="remove(index)">移除此条</el-button>
      </article>
      <el-button @click="emit('update:modelValue',[...modelValue,{group:'scope',title:'',text:''}])">添加规则说明</el-button>
    </template>
    <template v-else>
      <section v-for="group in populated" :key="group.id" class="rule-group"><h3>{{ group.label }} <small>{{ group.entries.length }} 条</small></h3><ol><li v-for="rule in group.entries" :key="rule.index"><b v-if="rule.title">{{ rule.title }}</b><p>{{ rule.text }}</p></li></ol></section>
      <p v-if="!entries.length" class="hint">尚未登记规则说明，不能据此推断已具备计算或政策核验能力。</p>
    </template>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {describeContent} from './presentation'
type Rule=string|Record<string,unknown>
const props=withDefaults(defineProps<{modelValue:Rule[];editable?:boolean}>(),{editable:false})
const emit=defineEmits<{ 'update:modelValue':[value:Rule[]] }>()
const groups=[{id:'scope',label:'适用范围'},{id:'metric',label:'指标与公式'},{id:'selection',label:'筛选与排序'},{id:'unknown',label:'异常与未知'},{id:'boundary',label:'结果与边界'},{id:'evidence',label:'依据与确认'}]
// Legacy text is only grouped for reading; its original content is not rewritten.
function legacyGroup(text:string){if(/^未知|未映射|缺失对象|样本不足|冲突行|缺项|零记录/.test(text))return 'unknown';if(/分母|分子|first_attempts|first_pass|failures|students|公式|人次|比例/.test(text))return 'metric';if(/排序|降序|升序|筛选|纳入|排除|TOP|前\d/.test(text))return 'selection';if(/工具运行完成|人工检查|确认业务结果/.test(text))return 'evidence';if(/身份|权限|范围|对象|授权/.test(text))return 'scope';if(/来源|确认|核对|证据|版本/.test(text))return 'evidence';return 'boundary'}
const entries=computed(()=>props.modelValue.map((original,index)=>{const text=describeContent(original),record=typeof original==='object'?original:{};return {index,original,text,title:typeof record.title==='string'?record.title:'',group:groups.some(g=>g.id===record.group)?String(record.group):legacyGroup(text)}}))
const populated=computed(()=>groups.map(g=>({...g,entries:entries.value.filter(e=>e.group===g.id)})).filter(g=>g.entries.length))
function update(index:number,key:'group'|'title'|'text',value:string){const next=[...props.modelValue],old=entries.value[index];if(!old)return;const record:Record<string,unknown>=typeof old.original==='object'?{...old.original}:{text:old.text};if(key==='text'){const textKey=['text','description','statement'].find(k=>typeof record[k]==='string')||'text';record[textKey]=value}else record[key]=value;record.group??=old.group;next[index]=record;emit('update:modelValue',next)}
function remove(index:number){emit('update:modelValue',props.modelValue.filter((_,i)=>i!==index))}
</script>
<style scoped>.rules-view{line-height:1.8}.hint{color:#64748b;font-size:13px}.rule-group{margin:20px 0;border-top:1px solid #e2e8f0;padding-top:16px}.rule-group h3{font-size:15px;margin:0 0 10px;color:#304768}.rule-group small{font-size:12px;color:#64748b;font-weight:400;margin-left:8px}.rule-group ol{list-style:decimal!important;padding-left:26px!important;margin:0}.rule-group li{display:list-item!important;padding:7px 4px;margin:0}.rule-group li::marker{color:#526b94;font-weight:600}.rule-group p{white-space:pre-wrap;overflow-wrap:anywhere;margin:2px 0}.rule-editor{border:1px solid #dce3ed;border-radius:6px;padding:14px;margin:12px 0}.rule-fields{display:grid;grid-template-columns:170px 1fr;gap:14px}.rule-editor label{display:flex;flex-direction:column;gap:6px;margin-bottom:12px;color:#526176;font-size:13px}@media(max-width:600px){.rule-fields{grid-template-columns:1fr}}</style>
