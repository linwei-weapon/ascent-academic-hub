<template>
  <el-drawer class="resource-package-drawer" direction="rtl" v-model="visible" :title="resource?'更新技能包':'导入技能包'" size="min(900px,94vw)" :close-on-click-modal="true" :before-close="close">
    <el-steps :active="step" finish-status="success" simple><el-step title="技能包" /><el-step title="基本信息" /></el-steps>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <template v-if="step===0">
      <p class="notice">技术人员提供技能包，产品经理核对用途与规则。可先<a href="/templates/business-skill-template.zip" download>下载技能包模板</a>，填写说明和契约后打包；模板本身不提供运行能力。已有技能可从列表“更多维护操作”复制为草稿。</p>
      <el-upload class="package-upload" drag :auto-upload="false" :show-file-list="false" accept=".zip" :disabled="busy" :on-change="readFile"><div class="package-icon">▣</div><h3>点击或拖拽技能包 ZIP 到此处</h3><p>上传后立即校验结构与解析 front matter</p></el-upload>
      <p class="muted">SKILL.md 位于 ZIP 根目录或唯一子目录根；front matter 必须包含 name / version / description。包仅解析与保存，不执行上传代码。</p><p v-if="filename" class="muted">{{ filename }} {{ busy?' · 正在校验':'' }}</p>
    </template>
    <template v-else-if="inspection">
      <div class="fields"><label><span>名称 *</span><el-input v-model="name" /></label><label><span>技能编码</span><el-input :model-value="inspection.frontMatter.name" disabled /></label><label><span>版本</span><el-input :model-value="inspection.frontMatter.version" disabled /></label><label><span>类型分类</span><el-select v-model="category" filterable allow-create default-first-option clearable placeholder="选择或填写分类"><el-option v-for="value in categories" :key="value" :label="value" :value="value" /></el-select></label><label class="full"><span>描述</span><el-input :model-value="inspection.frontMatter.description" type="textarea" :rows="3" disabled /><small>描述来自技能包，需要修改时重新导入修订后的包。</small></label></div>
      <div v-for="warning in inspection.warnings||[]" :key="warning" class="notice">{{ warning }}</div>
      <h3>文件预览 · {{ inspection.files.length }} 项</h3><div class="file-preview"><nav><button v-for="file in inspection.files" :key="file.path" :class="{active:selectedFile===file.path}" @click="selectedFile=file.path">{{ file.path }} <small>{{ file.size }} B</small></button></nav><pre>{{ currentFile?.text ?? '请选择文件查看内容。' }}</pre></div>
      <p class="notice">{{ resource?'更新包需保持编码一致并提高版本；保存后不会继承原执行状态。':'保存后为待接入草稿。' }}代码技能、提示词技能均须匹配实际运行能力并验证，上传完成不代表可以执行。</p>
    </template>
    <template #footer><el-button :disabled="busy" @click="close()">取消</el-button><el-button v-if="step===1" :disabled="busy" @click="step=0">上一步</el-button><el-button v-if="step===0" type="primary" :disabled="!inspection||busy" @click="step=1">下一步</el-button><el-button v-else type="primary" :loading="busy" :disabled="busy||!name.trim()" @click="save">保存草稿</el-button></template>
  </el-drawer>
</template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import {expertResourcesApi as api} from '@/api/aiDecision/expertResources'
import type {ExpertResource} from '@/types/expertResources'
const visible=defineModel<boolean>({required:true})
const props=defineProps<{categories:string[];resource?:ExpertResource|null}>()
const emit=defineEmits<{created:[resource:ExpertResource]}>()
const step=ref(0),busy=ref(false),error=ref(''),filename=ref(''),zipBase64=ref(''),name=ref(''),category=ref(''),selectedFile=ref('')
const inspection=ref<Awaited<ReturnType<typeof api.inspectPackage>>|null>(null)
const currentFile=computed(()=>inspection.value?.files.find(file=>file.path===selectedFile.value))
watch(visible,value=>{if(value){step.value=0;error.value='';filename.value='';zipBase64.value='';inspection.value=null;name.value='';category.value=props.resource?.category||'';selectedFile.value=''}})
async function mayLeave(){if(busy.value)return false;if(!filename.value)return true;try{await ElMessageBox.confirm('技能包尚未保存，离开将丢失本次上传与填写。','离开技能包导入',{confirmButtonText:'放弃并离开',cancelButtonText:'继续填写',type:'warning'});return true}catch{return false}}
async function close(done?:()=>void){if(!await mayLeave())return;visible.value=false;if(typeof done==='function')done()}
defineExpose({mayLeave,busy})
async function readFile(upload:{raw?:File;name?:string}){if(!upload.raw||busy.value)return;busy.value=true;error.value='';inspection.value=null;try{if(upload.raw.size>2*1024*1024)throw new Error('技能包不能超过2 MB');const data=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(upload.raw!)});filename.value=upload.raw.name;zipBase64.value=data;inspection.value=await api.inspectPackage({filename:filename.value,zipBase64:data});if(props.resource&&inspection.value.frontMatter.name!==props.resource.id){inspection.value=null;throw new Error('更新包的front matter name必须与现有技能编码一致')}name.value=props.resource?.name||inspection.value.frontMatter.name;selectedFile.value=inspection.value.files.find(file=>file.path.endsWith('SKILL.md'))?.path||inspection.value.files[0]?.path||''}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function save(){if(!inspection.value||busy.value)return;busy.value=true;error.value='';try{const resource=await api.package({filename:filename.value,zipBase64:zipBase64.value,resourceId:props.resource?.id,revision:props.resource?.draft.revision,displayName:name.value.trim(),category:category.value});emit('created',resource);visible.value=false}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
</script>
<style scoped>:global(.resource-package-drawer){color:#28364b;--el-color-primary:#344b77}:global(.resource-package-drawer .el-drawer__header){margin-bottom:0;padding:20px 24px;border-bottom:1px solid #dfe5ed}:global(.resource-package-drawer .el-drawer__body){padding:24px;overscroll-behavior:contain}:global(.resource-package-drawer .el-drawer__footer){border-top:1px solid #dfe5ed;padding:16px 24px}@media(max-width:700px){:global(.resource-package-drawer){width:100%!important}:global(.resource-package-drawer .el-drawer__body){padding:16px}}.package-upload{margin-top:25px}.package-icon{font-size:48px;color:#52678f}.package-upload h3{font-size:20px;font-weight:500}.package-upload p,.muted,small{color:#64748b;line-height:1.8}.fields{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}.fields label{display:flex;flex-direction:column;gap:8px}.full{grid-column:1/-1}.file-preview{display:grid;grid-template-columns:230px 1fr;border:1px solid #dfe5ed;border-radius:6px;max-height:300px;overflow:hidden}.file-preview nav{overflow:auto;border-right:1px solid #dfe5ed}.file-preview button{display:block;width:100%;border:0;background:white;padding:12px;text-align:left;overflow-wrap:anywhere;cursor:pointer}.file-preview button.active{background:#edf2f8}.file-preview pre{margin:0;overflow:auto;white-space:pre-wrap;padding:15px;font-size:12px;background:#fafbfd}.notice{padding:13px;background:#f3f6fa;border-radius:6px;margin-top:15px;line-height:1.8}.error{background:#fff1f2;color:#a92e38}@media(max-width:700px){.fields,.file-preview{grid-template-columns:1fr}}</style>
