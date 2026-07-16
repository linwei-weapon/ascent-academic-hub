<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>AI管理要情</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="brief-head">
      <div>
        <h2 class="sa-page-title">AI管理要情</h2>
        <p class="sa-page-sub">只报告相对上次快照发生的管理变化；数据不变时不重复制造任务。</p>
      </div>
      <div class="head-actions">
        <el-radio-group v-model="period" size="small" @change="load">
          <el-radio-button label="morning">本次更新</el-radio-button>
          <el-radio-button label="term">学期态势</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="loading" @click="load">更新要情</el-button>
      </div>
    </div>

    <el-alert v-if="loading && !hasData" class="loading-alert" type="info" :closable="false" show-icon
      title="正在比对管理快照" description="正在汇总跨专题数据，并识别新增、升级、变化和退出重点的事项。" />
    <el-alert v-else-if="loading" class="loading-alert" type="info" :closable="false" show-icon
      title="正在更新要情，当前结果将保留到新快照完成" />

    <el-skeleton :loading="loading && !hasData" animated :rows="7">
      <section class="hero-card" :class="{quiet:data.noSignificantChange}">
        <div class="status-mark">{{ data.noSignificantChange ? '稳' : data.changeCount || 0 }}</div>
        <div class="hero-main">
          <div class="hero-topline">
            <el-tag :type="data.noSignificantChange ? 'success' : 'danger'" effect="dark">
              {{ data.noSignificantChange ? '无新增重大事项' : `${data.changeCount || 0} 项管理变化` }}
            </el-tag>
            <span>{{ data.audience || '当前授权管理角色' }}</span>
          </div>
          <h3>{{ data.headline }}</h3>
          <p>{{ data.summary }}</p>
          <div class="hero-meta">
            <span>{{ data.snapshot?.comparisonLabel || '首次建立基线' }}</span>
            <span>当前快照：{{ formatTime(data.snapshot?.currentAt || data.generatedAt) }}</span>
            <span>成绩：{{ data.semester?.grade || '—' }}</span>
            <span>教学任务：{{ data.semester?.teaching || '—' }}</span>
          </div>
        </div>
      </section>

      <el-alert v-if="data.noSignificantChange" class="no-change" type="success" :closable="false" show-icon
        title="本次无需新增管理任务"
        description="系统仍保留下方持续需处理事项，供管理者确认进展；只有数据发生变化时才重新进入变化Top3。" />

      <section v-else class="change-section">
        <div class="section-heading">
          <div><h3>本次管理变化 Top3</h3><p>按升级、新增、发生变化、退出重点排序，不是把所有专题重新罗列一遍。</p></div>
          <el-tag type="danger" effect="plain">先处理第1项</el-tag>
        </div>
        <div class="change-grid">
          <article v-for="(item,index) in data.changes || []" :key="item.theme" class="change-card" :class="{primary:index===0}">
            <div class="change-head">
              <span class="rank">{{ index + 1 }}</span>
              <el-tag size="small" :type="changeTagType(item.changeType)">{{ item.changeLabel }}</el-tag>
              <el-tag v-if="item.level==='high'" size="small" type="danger" effect="plain">高优先级</el-tag>
            </div>
            <h4>{{ item.theme }}</h4>
            <p class="change-summary">{{ item.changeSummary }}</p>
            <div class="impact"><span>影响范围</span><b>{{ item.impactScope }}</b></div>
            <div class="action-box">
              <div><span>建议责任</span><b>{{ item.owner }}</b></div>
              <div><span>建议时点</span><b>{{ item.timing }}</b></div>
              <p>{{ item.managementAction }}</p>
              <small>预期形成：{{ item.expectedResult }}</small>
            </div>
            <p class="consequence">暂不处理的影响：{{ item.consequence }}</p>
            <div class="card-action"><el-button type="primary" plain @click="go(item.route,item.routeQuery)">查看事实证据</el-button></div>
          </article>
        </div>
      </section>

      <section v-if="period==='term' && data.periodPanel" class="sa-card term-panel">
        <div class="sa-card-title">学期态势比较 <span class="extra">有明确比较基准才输出变化</span></div>
        <div class="term-grid">
          <article v-for="item in data.periodPanel.items || []" :key="item.label">
            <span>{{ item.label }}</span><b>{{ item.value }}</b><p>{{ item.managementValue }}</p>
          </article>
        </div>
      </section>

      <section class="sa-card ongoing-card">
        <div class="sa-card-title">持续需处理事项 <span class="extra">最多3项；数据未变化时保留，但不重复标为新增</span></div>
        <el-table :data="data.ongoingPriorities || []" stripe>
          <el-table-column prop="rank" label="顺序" width="64" />
          <el-table-column label="事项" min-width="150"><template #default="{row}"><b>{{ row.theme }}</b><div><el-tag size="small" :type="row.level==='high'?'danger':'warning'">{{row.level==='high'?'高优先级':'中优先级'}}</el-tag></div></template></el-table-column>
          <el-table-column prop="summary" label="当前影响" min-width="250" />
          <el-table-column label="当前应做" min-width="250"><template #default="{row}"><b>{{row.managementAction}}</b><p class="table-meta">{{row.owner}} · {{row.timing}}</p></template></el-table-column>
          <el-table-column label="操作" width="110" fixed="right"><template #default="{row}"><el-button link type="primary" @click="go(row.route,row.routeQuery)">进入专题</el-button></template></el-table-column>
        </el-table>
      </section>

      <section class="sa-card trace-card">
        <div class="sa-card-title">数据来源与快照追溯</div>
        <div class="trace-overview">
          <div><span>比较基准</span><b>{{ data.snapshot?.comparisonLabel || '首次建立基线' }}</b></div>
          <div><span>业务数据</span><b>{{ trace.businessDataSources || businessSource(listText(trace.dataSources)) }}</b></div>
          <div><span>规则与时点</span><b>{{ trace.ruleVersion || '—' }} · {{ formatTime(trace.asOfTime) }}</b></div>
        </div>
        <el-collapse>
          <el-collapse-item name="trace" title="查看完整计算口径、来源与使用边界">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="快照保存">{{ data.snapshot?.persistence || '—' }}</el-descriptions-item>
              <el-descriptions-item label="技术来源">{{ listText(trace.dataSources) }}</el-descriptions-item>
              <el-descriptions-item label="生成方式">{{ trace.generationMethod || data.sourceLabel || '规则研判' }}</el-descriptions-item>
              <el-descriptions-item label="计算逻辑">{{ trace.calculationLogic || '—' }}</el-descriptions-item>
              <el-descriptions-item label="命中规则">{{ listText(trace.rules) }}</el-descriptions-item>
              <el-descriptions-item label="阈值说明">{{ listText(trace.thresholds) }}</el-descriptions-item>
              <el-descriptions-item label="使用边界">{{ trace.boundary || '—' }}</el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>
      </section>
    </el-skeleton>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getManagementBriefing } from '@/utils/ai'

const router=useRouter(),loading=ref(false),period=ref<'morning'|'term'>('morning'),data=reactive<any>({})
const hasData=computed(()=>Boolean(data.targetName)),trace=computed(()=>data.traceability||{})
const sourceMap:Record<string,string>={fact_alert:'学业预警记录',fact_grade:'学生成绩明细',student_plan_course_status:'学生培养方案课程完成证据',teaching_lesson:'教学任务与教学班',fact_room_occupancy:'实际教室占用记录',agg_course_team:'课程团队结构汇总'}
function listText(v:any){return Array.isArray(v)?v.join('；'):v||'—'}
function businessSource(v:any){const raw=String(v||'');const labels=Object.entries(sourceMap).filter(([k])=>raw.includes(k)).map(([,x])=>x);return[...new Set(labels)].join('、')||raw||'当前页面业务数据'}
function formatTime(v?:string){return v?v.replace('T',' ').slice(0,19):'—'}
function changeTagType(t:string):'danger'|'warning'|'success'|'info'{return t==='upgraded'?'danger':t==='new'||t==='changed'?'warning':t==='resolved'?'success':'info'}
function go(path?:string,query?:Record<string,string>){if(path)router.push({path,query:query||{}})}
async function load(){loading.value=true;try{const result=await getManagementBriefing({period:period.value});Object.keys(data).forEach(k=>delete data[k]);Object.assign(data,result)}finally{loading.value=false}}
onMounted(load)
</script>

<style scoped>
.brief-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.head-actions{display:flex;gap:10px;align-items:center;padding-top:12px}.loading-alert,.no-change{margin:12px 0}.hero-card{display:flex;gap:18px;padding:22px;border-radius:16px;background:linear-gradient(135deg,#fff1f2,#f8fafc 52%,#eef2ff);border:1px solid #fecdd3;margin:12px 0 16px}.hero-card.quiet{background:linear-gradient(135deg,#ecfdf5,#f8fafc);border-color:#bbf7d0}.status-mark{width:52px;height:52px;flex:0 0 52px;border-radius:15px;background:#e11d48;color:#fff;display:grid;place-items:center;font-size:22px;font-weight:800}.quiet .status-mark{background:#16a34a}.hero-topline{display:flex;align-items:center;gap:10px;color:#64748b;font-size:12px}.hero-main h3{margin:8px 0;color:#0f172a;font-size:22px}.hero-main>p{margin:0;color:#475569;line-height:1.8;font-size:13px}.hero-meta{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;color:#64748b;font-size:12px}.section-heading{display:flex;justify-content:space-between;align-items:flex-start;margin:4px 0 12px}.section-heading h3{margin:0;color:#0f172a}.section-heading p{margin:5px 0 0;color:#64748b;font-size:12px}.change-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:16px}.change-card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px;box-shadow:0 4px 18px rgba(15,23,42,.04)}.change-card.primary{border:2px solid #e11d48;box-shadow:0 8px 24px rgba(225,29,72,.1)}.change-head{display:flex;gap:7px;align-items:center}.rank{display:grid;place-items:center;width:25px;height:25px;border-radius:8px;background:#0f172a;color:#fff;font-weight:700}.change-card h4{font-size:17px;margin:12px 0 7px;color:#1e293b}.change-summary{color:#64748b;font-size:12px;line-height:1.7;min-height:42px}.impact{padding:10px 12px;background:#f8fafc;border-radius:9px}.impact span,.action-box span{display:block;color:#94a3b8;font-size:11px}.impact b{display:block;margin-top:4px;color:#334155;font-size:12px;line-height:1.6}.action-box{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;padding:12px;border-radius:10px;background:#eef2ff}.action-box b{font-size:12px;color:#3730a3}.action-box p,.action-box small{grid-column:1/-1;margin:4px 0 0;color:#334155;font-size:12px;line-height:1.6}.action-box small{color:#64748b}.consequence{font-size:11px;color:#9f1239;line-height:1.6}.card-action{text-align:right}.term-panel,.ongoing-card,.trace-card{margin-bottom:14px}.term-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.term-grid article{padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc}.term-grid span{color:#64748b;font-size:11px}.term-grid b{display:block;margin:5px 0;color:#1e293b}.term-grid p,.table-meta{margin:4px 0;color:#64748b;font-size:11px;line-height:1.6}.trace-overview{display:grid;grid-template-columns:1fr 1.4fr 1fr;gap:10px;margin-bottom:10px}.trace-overview>div{padding:10px 12px;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc}.trace-overview span{display:block;color:#64748b;font-size:11px}.trace-overview b{display:block;margin-top:4px;color:#334155;font-size:12px;line-height:1.55}
@media(max-width:1100px){.brief-head,.head-actions{display:block}.change-grid,.term-grid,.trace-overview{grid-template-columns:1fr}.change-summary{min-height:0}}
</style>
