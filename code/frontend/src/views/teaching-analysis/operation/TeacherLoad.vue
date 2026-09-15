<!-- 教学运行分析：TeacherLoad 页面或专用组件，保留原业务与权限行为。 -->
<template>
  <div v-loading="loading && !!kpis.length" element-loading-text="正在按新条件更新教师负荷，当前结果暂时保留…">
    <div class="sa-head-row">
      <div><h2 class="sa-page-title">教师教学负荷分析</h2></div>
      <div class="filters">
        <el-select v-model="fCollege" size="small" clearable placeholder="全部学院" style="width:160px" @change="load"><el-option v-for="c in colleges" :key="c.value" :label="c.label" :value="c.value" /></el-select>
        <el-select v-model="fTitle" size="small" clearable placeholder="全部职称" style="width:130px" @change="load"><el-option v-for="t in titles" :key="t" :label="t" :value="t" /></el-select>
      </div>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" show-icon title="教师负荷加载失败"
      :description="loadError" style="margin-bottom:12px"><template #default><el-button link type="primary" @click="load">重新加载</el-button></template></el-alert>
    <div v-else-if="loading && !kpis.length" class="sa-card" style="margin-bottom:12px"><el-skeleton :rows="8" animated /></div>
    <el-alert v-if="qualityIssueCount" type="warning" :closable="false" show-icon
      :title="`已排除 ${qualityIssueCount} 名教师异常记录`"
      style="margin-bottom:12px" />
    <el-collapse v-if="qualityIssueCount" v-model="qualityPanels" style="margin-bottom:12px">
      <el-collapse-item :title="`查看 ${qualityIssueCount} 条数据质量问题明细`" name="quality">
        <AppTable v-if="qualityIssues.length" :data="qualityIssues"  stripe max-height="300" :columns="[]" storage-key="teaching-analysis:operation:teacherload:1" :pagination="false">
        <template #columns>
          <el-table-column prop="semester_id" label="学期" min-width="120" align="center" header-align="center"/>
          <el-table-column label="教师" min-width="180" align="center" header-align="center"><template #default="{row}">{{ row.entity_name || row.entity_id }}（{{ row.entity_id }}）</template></el-table-column>
          <el-table-column prop="detail" label="问题说明" min-width="240" align="center" header-align="center"/>
          <el-table-column prop="recommendation" label="处置建议" min-width="280" align="center" header-align="center"/>
                </template>
      </AppTable>
        <el-empty v-else description="数据质量问题明细暂未返回，请刷新页面重试" :image-size="64" />
      </el-collapse-item>
    </el-collapse>

    <div class="sa-kpi-row"><KpiCard v-for="k in kpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="tone(k.label)" /></div>
    <div class="ai-toolbar"><el-button size="small" type="primary" plain @click="openLoadAi()">生成当前负荷重点</el-button></div>

    <el-row :gutter="16" align="top" class="load-table-row">
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">职称维度教学任务 <KpiLabel label="" formula="仅统计当前学期有有效教学任务的教师；不计算在岗教师上课率" /></div>
        <AppTable :columns="titleCols" :data="data.titleLoad" storage-key="operation:teacher-load-title"  max-height="310" :max-business-columns="5" :show-density="true" :show-column-settings="true" :pagination="false"/>
      </div></el-col>
      <el-col :span="12"><div class="sa-card">
        <div class="sa-card-title">负荷核查队列 <KpiLabel label="" :formula="data.topTeacherPolicy.ranking" /></div>
        <AppTable :columns="teacherCols" :data="data.topTeachers" storage-key="operation:teacher-load-review"  max-height="250" :max-business-columns="3" :show-density="true" :show-column-settings="true" :pagination="false">
          <template #col-name="{row}"><span class="link" @click="openReview(row)">{{ row.name }}</span><div class="sa-faint meta">{{ row.title }} · {{ row.dept }}</div></template>
          <template #col-attention="{row}"><el-tag size="small" :type="teacherNeedsAi(row)?'danger':'warning'">{{teacherNeedsAi(row)?'重点关注':'需关注'}}</el-tag></template>
          <template #col-actions="{row}"><el-button text type="primary" size="small" @click="openReview(row)">详情</el-button></template>
        </AppTable>
      </div></el-col>
    </el-row>

    <div class="sa-card">
      <div class="sa-card-title">各学院教学负荷对比 <KpiLabel label="" formula="按实际授课教师统计中位学时、P90学时和人均课程；相对负荷按学院P90归一化，仅用于安排核查顺序" /></div>
      <AppTable :columns="deptCols" :data="data.deptLoad" storage-key="operation:teacher-load-college"
        :max-business-columns="5" :show-density="true" :show-column-settings="true" :pagination="false">
        <template #col-dept="{row}"><span>{{ row.dept }}</span></template>
        <template #col-attention="{row,$index}"><el-tag size="small" :type="$index<3?'danger':row.loadLevel>60?'warning':'info'">{{$index<3?'优先关注':row.loadLevel>60?'需关注':'常规'}}</el-tag></template>
        <template #col-loadLevel="{row}"><el-progress :percentage="row.loadLevel" :stroke-width="10" :color="row.loadLevel>80?'#E11D48':row.loadLevel>60?'#D97706':'#0D9488'" /></template>
      </AppTable>
    </div>

    <el-drawer v-model="drawer" :title="`${selected.name || ''}｜教学负荷信息`" size="720px">
      <el-descriptions :column="3" border size="small" style="margin:14px 0">
        <el-descriptions-item label="总学时">{{ selected.hours || 0 }}</el-descriptions-item><el-descriptions-item label="课程数">{{ selected.courses || 0 }}</el-descriptions-item><el-descriptions-item label="教学班数">{{ selected.lessons || 0 }}</el-descriptions-item>
        <el-descriptions-item label="学生覆盖人次">{{ selected.studentVisits || 0 }}</el-descriptions-item><el-descriptions-item label="平均班额">{{ selected.avgClassSize || 0 }}</el-descriptions-item><el-descriptions-item label="当前排名">第 {{ selected.rank || '-' }} 位</el-descriptions-item>
      </el-descriptions>
      <div class="sa-card-title">课程构成证据</div>
      <AppTable :data="selected.courseBreakdown || []" :columns="[]" storage-key="teaching-analysis:operation:teacherload:5" :pagination="false">
        <template #columns>
        <el-table-column prop="courseName" label="课程" min-width="190" show-overflow-tooltip align="center" header-align="center"/><el-table-column prop="hours" label="学时" min-width="70" align="center" header-align="center"/><el-table-column prop="lessons" label="教学班" min-width="75" align="center" header-align="center"/><el-table-column prop="studentVisits" label="学生人次" min-width="86" align="center" header-align="center"/><el-table-column prop="avgClassSize" label="平均班额" min-width="82" align="center" header-align="center"/>
              </template>
      </AppTable>
      <div v-if="teacherNeedsAi(selected)" class="actions"><el-button type="primary" plain @click="openTeacherAi(selected)">查看负荷研判</el-button></div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="教师负荷研判"
      hide-intervention-tag hide-decision-meta hide-baseline hide-consequence hide-expected-result
      hide-no-comparison-tag hide-trace hide-trace-shortcut hide-evidence-help hide-evidence-source show-all-evidence />
  </div>
</template>

<script setup lang="ts">
import * as operationApi from '@/api/teachingAnalysis/operation'

import { computed, inject, onMounted, reactive, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'

import KpiCard from '@/components/KpiCard.vue'
import KpiLabel from '@/components/KpiLabel.vue'
import { getFilterMeta } from '@/api/shared/filterMeta'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import AppTable from '@/components/AppTable.vue'
import type { AppTableColumn } from '@/types/table'
import { getTeacherLoadAIInsight, getTeacherLoadTeacherAIInsight } from '@/api/teachingAnalysis/insights'

const route=useRoute()
const titleCols:AppTableColumn[]=[
  {key:'title',label:'职称',minWidth:100,required:true,region:'identity',fixed:'left'},
  {key:'count',label:'授课教师',minWidth:82,align:'center',required:true},
  {key:'medianHours',label:'中位学时',minWidth:86,align:'center',required:true},
  {key:'p90Hours',label:'P90学时',minWidth:86,align:'center',required:true},
  {key:'avgCourses',label:'人均课程',minWidth:86,align:'center'},
  {key:'avgClasses',label:'人均教学班',minWidth:92,align:'center'},
  {key:'note',label:'口径说明',minWidth:135,tooltip:true},
]
const teacherCols:AppTableColumn[]=[
  {key:'rank',label:'#',minWidth:42,align:'center',required:true,region:'identity',fixed:'left'},
  {key:'name',label:'教师',minWidth:130,required:true,region:'identity',fixed:'left'},
  {key:'hours',label:'总学时',minWidth:68,align:'center',required:true},
  {key:'lessons',label:'教学班',minWidth:68,align:'center'},
  {key:'attention',label:'管理关注',minWidth:100,required:true},
  {key:'actions',label:'操作',width:78,required:true,region:'action',fixed:'right'},
]
const deptCols:AppTableColumn[]=[
  {key:'dept',label:'学院',minWidth:170,required:true,region:'identity',fixed:'left'},
  {key:'teacherCount',label:'授课教师',minWidth:90,align:'center',required:true},
  {key:'medianHours',label:'中位学时',minWidth:90,align:'center',required:true},
  {key:'p90Hours',label:'P90学时',minWidth:90,align:'center',required:true},
  {key:'avgCourses',label:'人均课程',minWidth:90,align:'center'},
  {key:'attention',label:'管理关注',minWidth:100},
  {key:'loadLevel',label:'相对负荷水平',minWidth:220,required:true},
]
const fSemester=inject<Ref<string>>('operationSemester',ref('')), fCollege=ref(''), fTitle=ref('')
const colleges=ref<{value:string;label:string}[]>([]), titles=ref<string[]>([])
const kpis=ref<any[]>([]), drawer=ref(false), selected=ref<any>({})
const loading=ref(false),loadError=ref('')
const aiDrawerVisible=ref(false), aiLoading=ref(false), aiInsight=ref<any>(null)
const qualityPanels=ref<string[]>([])
const qualityIssues=computed(()=>Array.isArray(data.qualityIssues)?data.qualityIssues:[])
const qualityIssueCount=computed(()=>qualityIssues.value.length)
const data=reactive<any>({titleLoad:[],topTeachers:[],deptLoad:[],qualityIssues:[],dataQuality:{excludedTeachers:0},topTeacherPolicy:{ranking:'按当前范围统计分布形成有限核查队列'}})
// 按当前页面上下文读取数据，沿用原加载状态和异常处理。
async function load(){loading.value=true;loadError.value='';try{const p=new URLSearchParams();if(fCollege.value)p.set('college',fCollege.value);if(fSemester.value)p.set('semester',fSemester.value);if(fTitle.value)p.set('title',fTitle.value);const d=await operationApi.getTeacherLoad(p);if(d){const issues=Array.isArray(d.qualityIssues)?d.qualityIssues:[];const nextKpis=Array.isArray(d.kpis)?d.kpis:[];const anomalyKpi=nextKpis.find((item:any)=>item.label==='已排除异常教师');if(anomalyKpi)anomalyKpi.value=`${issues.length}人`;kpis.value=nextKpis;Object.assign(data,d,{qualityIssues:issues,dataQuality:{...(d.dataQuality||{}),excludedTeachers:issues.length}});qualityPanels.value=[]}}catch(error:any){loadError.value=error?.message||'教师负荷数据加载失败，请稍后重试。'}finally{loading.value=false}}
function openReview(row:any){selected.value=row;drawer.value=true}
function teacherNeedsAi(row:any){return Number(row?.rank||999)<=3}
async function openLoadAi(){aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadAIInsight({semester:fSemester.value,college:fCollege.value||undefined,title:fTitle.value||undefined})}finally{aiLoading.value=false}}
async function openTeacherAi(row:any){const id=row?.id||row?.teacher_id||row?.teacherId;if(!id)return;aiDrawerVisible.value=true;aiLoading.value=true;aiInsight.value=null;try{aiInsight.value=await getTeacherLoadTeacherAIInsight(id,fSemester.value)}finally{aiLoading.value=false}}
function tone(label:string):'primary'|'teal'|'danger'|'amber'{return label.includes('排除异常')?'amber':label.includes('P90')?'amber':label.includes('有效授课')?'teal':'primary'}
// 按既有监听条件响应路由、筛选或身份变化，保留原重载与清理时机。
watch(fSemester,(value,oldValue)=>{if(oldValue&&value!==oldValue)load()})
// 进入页面时执行原初始化流程，恢复路由条件与可用选项。
onMounted(async()=>{const meta=await getFilterMeta();colleges.value=meta.colleges||[];titles.value=meta.titles||[];const routeCollege=String(route.query.college||'');if(colleges.value.some(item=>item.value===routeCollege))fCollege.value=routeCollege;if(!fSemester.value)fSemester.value=meta.current;await load()})
</script>

<style scoped lang="scss">
// 按页面区域、后代元素和状态组织，保留原选择器顺序与作用范围。
.sa-head-row,.filters,.actions {
  display: flex;
}

.sa-head-row {
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.filters {
  gap: 8px;
}

.ai-toolbar {
  display: flex;
  justify-content: flex-end;
  margin: -4px 0 12px;
}

.load-table-row {
  margin-bottom: 16px;

  // 两张卡片各随表格内容收缩，覆盖全局同排等高规则。
  > .el-col > .sa-card {
    height: auto;
  }
}

.link {
  color: var(--sa-primary);
  cursor: pointer;
  font-weight: 500;
  &:hover {
    text-decoration: underline;
  }
}

.meta {
  font-size: 11px;
  margin-top: 2px;
}

.actions {
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
