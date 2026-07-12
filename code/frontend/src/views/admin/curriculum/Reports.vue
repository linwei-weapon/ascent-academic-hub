<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">管理决策专题</h2>
        <p class="sa-page-sub">围绕管理问题组织结论、重点对象和证据下钻，不再提供任意字段拼表</p>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon style="margin-bottom:16px"
      title="专题中心正在分阶段建设"
      description="当前先复用已验证的真实数据页面作为专题入口；考风考纪、出勤、校外考试、自定义报表和认证评估暂缓。" />

    <div class="topic-grid">
      <section v-for="topic in topics" :key="topic.key" class="topic-card" :class="topic.tone">
        <div class="topic-top">
          <div class="topic-index">{{ topic.index }}</div>
          <el-tag size="small" :type="topic.status==='可用'?'success':topic.status==='部分可用'?'warning':'info'">{{ topic.status }}</el-tag>
        </div>
        <h3>{{ topic.title }}</h3>
        <p class="value">{{ topic.value }}</p>
        <div class="questions">
          <div v-for="q in topic.questions" :key="q">{{ q }}</div>
        </div>
        <div class="topic-actions">
          <el-button v-for="a in topic.actions" :key="a.label" size="small" :type="a.primary?'primary':''" @click="go(a.path)">{{ a.label }}</el-button>
        </div>
        <div class="boundary">{{ topic.boundary }}</div>
      </section>
    </div>

    <div class="sa-card roadmap">
      <div class="sa-card-title">建设顺序与当前边界</div>
      <el-steps :active="1" align-center finish-status="success">
        <el-step title="学生建议与低年级受挫" description="确定性建议原型已开始接入" />
        <el-step title="培养方案与毕业准备度" description="复用V2课程状态，继续深化" />
        <el-step title="课程质量与教学运行" description="需要更多真实课程日历" />
        <el-step title="资源师资与排课优化" description="需年龄段、多学期课表和新学年任务" />
      </el-steps>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
const topics = [
  { key:'risk', index:'01', title:'学业风险与低年级受挫', status:'部分可用', tone:'risk',
    value:'把关注时点从严重预警前移到首次受挫和持续困难，识别需要更早支持的学生群体。',
    questions:['哪些学生在大一首次挂科后没有恢复？','困难集中在哪些课程、年级和专业？','哪些学生已有改善，应避免持续贴标签？'],
    actions:[{label:'进入专题',path:'/admin/reports/early-setback',primary:true},{label:'查看困难学生',path:'/admin/alert'}],
    boundary:'不自动建立帮扶任务；学生个人原因必须由授权人员核实。' },
  { key:'plan', index:'02', title:'培养方案完成与毕业准备度', status:'部分可用', tone:'plan',
    value:'从“修了多少学分”转向“是否完成正确的课程结构”，提前发现必修、模块和先修链缺口。',
    questions:['哪些学生存在明确未通过的必修课程？','哪些课程只是尚无完成证据，需要选课或认定核验？','哪些课程缺口需要新增重修资源？'],
    actions:[{label:'查看培养方案进度',path:'/admin/curriculum/progress',primary:true},{label:'查看培养质量',path:'/admin/curriculum'}],
    boundary:'当前不输出能否毕业结论；缺完整选课过程时不称“漏选”。' },
  { key:'course', index:'03', title:'课程质量与教学运行', status:'部分可用', tone:'course',
    value:'识别影响面大且持续异常的课程，结合通过率、班额、年级和排课时段组织课程层面核查。',
    questions:['哪些课程连续高挂科而非单学期波动？','首次与最终通过率差异是否反映重修压力？','体育、思政等重点课程时段是否均衡？'],
    actions:[{label:'查看开课分析',path:'/admin/operation/courses',primary:true},{label:'查看排课分析',path:'/admin/operation/schedule-analysis'}],
    boundary:'课程差异不直接归因于教师；长期趋势需要多学期真实数据。' },
  { key:'faculty', index:'04', title:'资源与师资风险', status:'部分可用', tone:'faculty',
    value:'识别核心课程单点承担、年龄和职称梯队、接续活跃度及特殊空间约束。',
    questions:['哪些核心课程长期依赖单一教师？','课程团队年龄或职称结构是否存在接续风险？','特殊教室和高峰时段是否限制课程供给？'],
    actions:[{label:'查看课程团队',path:'/admin/faculty/team',primary:true},{label:'查看师资结构',path:'/admin/faculty'}],
    boundary:'年龄风险必须等待真实人事年龄段；不使用模拟画像评价教师。' },
  { key:'schedule', index:'05', title:'排课策略与方案优化', status:'规划中', tone:'schedule',
    value:'沉淀历史排课规律，预测新学年压力，支持冲突诊断和候选方案 A/B 比较。',
    questions:['哪些历史分布是稳定倾向，哪些由资源约束造成？','新学年哪些教师、学生群体和教室成为瓶颈？','调整时段后解决什么冲突，又增加什么代价？'],
    actions:[{label:'查看历史排课分布',path:'/admin/operation/schedule-analysis',primary:true},{label:'查看教室资源',path:'/admin/operation/classroom'}],
    boundary:'不自动生成或发布最终课表；当前一个真实学期只能展示实际分布。' },
]
function go(path:string) { router.push(path) }
</script>

<style scoped>
.sa-head-row { display:flex; justify-content:space-between; margin-bottom:10px; }
.topic-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.topic-card { border:1px solid #E2E8F0; border-top:4px solid #4F46E5; border-radius:12px; background:#fff; padding:18px; box-shadow:0 4px 16px rgba(15,23,42,.04); }
.topic-card.risk { border-top-color:#E11D48; }.topic-card.plan { border-top-color:#0D9488; }.topic-card.course { border-top-color:#4F46E5; }.topic-card.faculty { border-top-color:#D97706; }.topic-card.schedule { border-top-color:#7C3AED; }
.topic-top { display:flex; justify-content:space-between; align-items:center; }.topic-index { font-size:12px; font-weight:700; color:#94A3B8; letter-spacing:.12em; }
.topic-card h3 { margin:10px 0 8px; font-size:18px; color:#1E293B; }.value { min-height:48px; color:#475569; font-size:13px; line-height:1.7; }
.questions { margin:12px 0; padding:10px 12px; background:#F8FAFC; border-radius:8px; color:#475569; font-size:12px; line-height:1.8; }.questions div:before { content:'·'; margin-right:7px; color:#4F46E5; font-weight:700; }
.topic-actions { display:flex; gap:8px; flex-wrap:wrap; }.boundary { margin-top:12px; padding-top:10px; border-top:1px dashed #E2E8F0; color:#94A3B8; font-size:11px; line-height:1.6; }
.roadmap { margin-top:16px; }.roadmap :deep(.el-step__description) { font-size:11px; line-height:1.5; }
@media (max-width:1100px) { .topic-grid { grid-template-columns:1fr; } }
</style>
