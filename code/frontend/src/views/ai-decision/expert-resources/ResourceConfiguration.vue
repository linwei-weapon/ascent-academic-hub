<template>
  <template v-if="kind==='experts'">
    <div class="config-grid">
      <label><span>图标</span><el-select v-model="value.icon" clearable placeholder="选择图标"><el-option v-for="icon in icons" :key="icon" :label="icon" :value="icon" /></el-select></label>
      <label><span>运行方式 *</span><el-select v-model="value.executionMode"><el-option label="已登记业务方法（确定性）" value="deterministic" /><el-option label="模型专家（需要真实模型）" value="llm" /></el-select></label>
      <label class="full"><span>模型配置{{ value.executionMode==='llm'?' *':'' }}</span><el-select v-if="value.executionMode==='llm'" v-model="value.modelId" placeholder="选择真实启用的模型"><el-option v-for="model in models" :key="model.id" :value="model.id" :label="model.label || model.name || model.id" :disabled="model.available===false" /></el-select><el-input v-else model-value="不适用：使用已登记业务方法" disabled /><small>{{ models.length?'仅显示服务端登记且实际接通的模型':'当前没有实际启用模型，模型专家不可运行' }}</small></label>
      <label v-if="value.executionMode==='llm'"><span>模型迭代上限</span><el-input-number v-model="value.maxIters" :min="1" :max="1000" /></label>
      <label v-if="value.executionMode==='llm'"><span>启用沙箱（尚未接入）</span><el-switch v-model="value.sandboxEnabled" disabled /><small>仅保存运行要求，沙箱执行尚未接入。</small></label>
      <label v-if="value.executionMode==='llm' || value.expertType==='orchestrator'" class="full"><span>专家类型 *</span><el-radio-group v-model="value.expertType"><el-radio value="single">单专家（使用绑定技能）</el-radio><el-radio value="orchestrator" disabled>编排专家（关联子专家）</el-radio></el-radio-group></label>
      <label v-if="value.expertType==='orchestrator'" class="full"><span>关联子专家</span><el-select v-model="value.childExpertIds" multiple filterable><el-option v-for="expert in experts.filter(item=>item.id!==resourceId)" :key="expert.id" :label="expert.name" :value="expert.id" /></el-select><small>编排执行尚未接入，当前配置保存为草稿。</small></label>
      <label v-if="showSkillBinding" class="full"><span>绑定技能</span><el-select v-model="value.skillIds" multiple filterable clearable placeholder="选择已发布技能"><el-option v-for="skill in boundChoices" :key="skill.id" :label="`${skill.name}${skill.published?'':'（原有未发布关联）'}`" :value="skill.id" :disabled="(!skill.published||!skill.enabled)&&!value.skillIds?.includes(skill.id)" /></el-select><small>技能自带MCP依赖，仅选择已发布且启用的技能。</small></label>
      <div v-if="showSkillBinding" class="full derived"><b>关联MCP（由技能自动带出，只读）</b><div v-for="server in derivedServers" :key="server.id">{{ server.name }} <small>{{ server.tools.join('、') }}</small></div><p v-if="!derivedServers.length">尚未选择技能，暂无关联MCP。</p></div>
      <label v-if="value.executionMode==='llm'" class="full"><span>模型人设与回答要求</span><el-input v-model="value.personaPrompt" type="textarea" :rows="5" /><small>确定性方法仍按登记算法执行。模型人设在模型接入后生效。</small></label>
      <label class="full"><span>欢迎语</span><el-input v-model="value.welcomeMessage" type="textarea" :rows="2" /></label>
    </div>
  </template>
  <template v-else-if="kind==='mcps'">
    <div class="config-grid">
      <div v-if="value.accessType!=='internal'" class="full warning" role="status">当前仅保存外部连接草稿，尚不可执行、测试成功或发布。可运行工具请使用内部已登记服务。</div>
      <label class="full"><span>接入类型 *</span><el-radio-group v-model="value.accessType" @change="accessChanged"><el-radio value="internal">内部已登记工具</el-radio><el-radio value="native">原生MCP（仅登记）</el-radio><el-radio value="http">HTTP接口转MCP（仅登记）</el-radio></el-radio-group></label>
      <label class="full"><span>服务地址{{ value.accessType!=='internal'?' *':'' }}</span><el-input v-model="value.serviceUrl" :disabled="value.accessType==='internal'" :placeholder="value.accessType==='internal'?'由服务端生成':value.accessType==='http'?'https://example.com/api':'https://example.com/mcp'" /></label>
      <label><span>连接方式 *</span><el-select v-model="value.transport" :disabled="value.accessType==='internal'"><el-option v-if="value.accessType==='internal'" label="内部调用" value="internal" /><el-option label="SSE" value="sse" /><el-option label="Streamable HTTP" value="streamable-http" /><el-option v-if="value.accessType==='http'" label="HTTP接口" value="http" /></el-select></label>
      <div v-if="value.accessType!=='internal'" class="full"><b>请求头</b><div v-for="(header,index) in value.requestHeaders || []" :key="index" class="header-row"><el-input v-model="header.name" placeholder="请求头名称，例如 Authorization" /><el-input v-model="header.value" type="password" show-password :placeholder="header.hasValue?'已保存，留空保持原值':'请求头值'" /><el-button @click="value.requestHeaders?.splice(index,1)">删除</el-button></div><el-button @click="addHeader">＋ 添加请求头</el-button><p class="muted">已保存值不返回浏览器；同名请求头留空保留原值，删除行会移除配置。</p></div>
      <template v-if="value.accessType==='http' && value.httpConfig"><label><span>HTTP 请求方法</span><el-select v-model="value.httpConfig.method"><el-option v-for="method in ['GET','POST','PUT','DELETE']" :key="method" :label="method" :value="method" /></el-select></label><label class="full"><span>输入参数映射说明</span><el-input v-model="value.httpConfig.requestMapping" type="textarea" :rows="3" placeholder="说明工具输入如何映射到路径、查询参数或请求体" /></label><label class="full"><span>输出结果映射说明</span><el-input v-model="value.httpConfig.responseMapping" type="textarea" :rows="3" placeholder="说明HTTP响应字段如何映射到工具输出" /></label></template>

    </div>
  </template>
</template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {expertResourcesApi as api} from '@/api/aiDecision/expertResources'
import type {ExpertModel} from '@/types/expertResources'
import type {ExpertResource,ResourceContent,ResourceKind} from '@/types/expertResources'
const value=defineModel<ResourceContent>({required:true})
const props=defineProps<{kind:ResourceKind;resourceId?:string;showSkillBinding?:boolean;experts:ExpertResource[];skills:ExpertResource[];mcps:ExpertResource[]}>()
const models=ref<Array<ExpertModel&{label?:string}>>([])
watch(()=>value.value.executionMode,async mode=>{if(props.kind!=='experts'||mode!=='llm')return;try{models.value=(await api.models()).items}catch{models.value=[]}},{immediate:true})
const icons=['🎓','📊','📚','🧭','🧩','🔎','🛠️','🏫']
const boundChoices=computed(()=>props.skills.filter(item=>item.published&&item.enabled||value.value.skillIds?.includes(item.id)))
const derivedServers=computed(()=>{const servers=new Map<string,{id:string;name:string;tools:string[]}>();for(const skill of props.skills.filter(item=>value.value.skillIds?.includes(item.id)))for(const binding of (skill.published?.content||skill.draft.content).toolBindings||[]){const server=servers.get(binding.serverId)||{id:binding.serverId,name:props.mcps.find(item=>item.id===binding.serverId)?.name||binding.serverId,tools:[]};if(!server.tools.includes(binding.toolName))server.tools.push(binding.toolName);servers.set(binding.serverId,server)}return [...servers.values()]})
function addHeader(){value.value.requestHeaders??=[];value.value.requestHeaders.push({name:'',value:''})}
function accessChanged(){if(value.value.accessType==='http')value.value.httpConfig??={method:'GET',requestMapping:'',responseMapping:''};value.value.transport=value.value.accessType==='internal'?'internal':value.value.accessType==='http'?'http':'sse';if(value.value.accessType!=='internal')value.value.serviceUrl=''}
</script>
<style scoped>.config-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;padding:15px 0}.config-grid > label{display:flex;flex-direction:column;gap:9px;font-size:14px}.config-grid .full{grid-column:1/-1}.config-grid small,.muted,.derived p{font-size:12px;line-height:1.8;color:#64748b}.derived{background:#f5f7fb;padding:15px;border-radius:7px}.derived div{margin-top:10px}.derived small{margin-left:12px}.header-row{display:flex;gap:10px;margin:12px 0}.warning{padding:14px;background:#fff8e9;color:#7c5c22;border-radius:6px;line-height:1.8}@media(max-width:700px){.config-grid{grid-template-columns:1fr}.header-row{flex-wrap:wrap}}</style>
