<template>
  <div>
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">管理决策专题</h2>
        <p class="sa-page-sub">
          围绕教务处和二级学院的管理问题组织结论、重点对象和证据下钻；AI能力用于把数据转成优先级、研判和行动建议。
        </p>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
      title="专题中心按管理场景组织"
      description="当前聚焦学生学业分析与预警、毕业准备、课程运行、师资保障和排课优化，不提供自定义报表和认证评估报表。"
    />

    <div class="topic-grid">
      <section v-for="topic in topics" :key="topic.key" class="topic-card" :class="topic.tone">
        <div class="topic-top">
          <div class="topic-index">{{ topic.index }}</div>
          <el-tag size="small" :type="statusType(topic.status)">{{ topic.status }}</el-tag>
        </div>
        <h3>{{ topic.title }}</h3>
        <p class="value">{{ topic.value }}</p>
        <div class="questions">
          <div v-for="q in topic.questions" :key="q">{{ q }}</div>
        </div>
        <div class="topic-actions">
          <el-button
            v-for="a in topic.actions"
            :key="a.label"
            size="small"
            :type="a.primary ? 'primary' : ''"
            @click="go(a.path)"
          >
            {{ a.label }}
          </el-button>
        </div>
        <div class="boundary">{{ topic.boundary }}</div>
      </section>
    </div>

    <div class="sa-card roadmap">
      <div class="sa-card-title">AI能力落地路径</div>
      <el-steps :active="2" align-center finish-status="success">
        <el-step title="AI研判抽屉" description="已在预警、学生档案、毕业准备、教学运行和师资保障中接入" />
        <el-step title="AI管理简报" description="把跨专题数据组织成管理优先级和行动清单" />
        <el-step title="AI决策模拟" description="下一步用于重修资源、排课优化和帮扶优先级的方案比较" />
        <el-step title="真实大模型接入" description="生产系统按学校授权接入云端或私有化大模型" />
      </el-steps>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

const topics = [
  {
    key: 'ai-briefing',
    index: 'AI',
    title: 'AI管理要情',
    status: 'AI增强',
    tone: 'ai',
    value: '对比管理快照，只报告新增、升级、变化或退出重点的事项，并给出管理层本轮最该先处理的Top3。',
    questions: [
      '今天教务处最应该先看哪三件事？',
      '哪些问题需要学院、课程团队、辅导员共同处理？',
      '数据背后的管理动作是什么，而不只是排名是什么？',
    ],
    actions: [{ label: '查看管理要情', path: '/admin/reports/management-briefing', primary: true }],
    boundary: '当前为原型阶段 AI 增强样本，保证演示稳定；生产系统可按学校授权接入真实大模型。',
  },
  {
    key: 'ai-simulation',
    index: 'AI+',
    title: 'AI决策模拟',
    status: 'AI增强',
    tone: 'simulation',
    value: '围绕毕业准备课程保障，比较重修班、课程替代认定核查、学习支持和课程团队保障等不同管理动作的覆盖规模、成本和落地难度。',
    questions: [
      '如果资源有限，哪些课程应该优先开重修或补修？',
      '哪些问题先做认定核查就可能减少误判？',
      '不同方案的覆盖学生规模、成本和实施难度如何比较？',
    ],
    actions: [{ label: '进入模拟', path: '/admin/reports/decision-simulation', primary: true }],
    boundary: '模拟结果是管理测算，不是毕业结论、开课承诺或学生最终通过预测。',
  },
  {
    key: 'risk',
    index: '01',
    title: '学业风险与低年级受挫',
    status: '可用',
    tone: 'risk',
    value: '把关注时点从严重预警前移到首次受挫和持续困难，识别需要更早支持的学生群体。',
    questions: [
      '哪些学生在大一首次挂科后没有恢复？',
      '困难集中在哪些课程、年级和专业？',
      '哪些学生已经改善，应避免持续贴标签？',
    ],
    actions: [
      { label: '进入专题', path: '/admin/reports/early-setback', primary: true },
      { label: '查看困难学生', path: '/admin/alert' },
    ],
    boundary: '不自动建立帮扶任务；学生个人原因必须由授权人员核实。',
  },
  {
    key: 'plan',
    index: '02',
    title: '毕业准备核查与课程保障',
    status: '可用',
    tone: 'plan',
    value: '把学生毕业前课程缺口与学校课程供给能力放在同一专题核查，支持学院干预和教务处统筹开课、重修及替代资源。',
    questions: [
      '哪些高年级学生存在明确未通过或到期缺证据的必修课程？',
      '哪些课程同时影响多个专业和大量学生？',
      '哪些瓶颈课程缺少开课、教师、重修班或替代关系证据？',
    ],
    actions: [
      { label: '进入专题', path: '/admin/reports/graduation-readiness', primary: true },
      { label: '查看培养质量', path: '/admin/curriculum' },
    ],
    boundary: '当前不输出能否毕业结论；缺完整选课过程时不称“漏选”。',
  },
  {
    key: 'course',
    index: '03',
    title: '课程质量与教学运行',
    status: '可用',
    tone: 'course',
    value: '识别影响面大且持续异常的课程，结合通过率、班额、年级和排课时段组织课程层面核查。',
    questions: [
      '哪些课程连续高挂科，而非单学期波动？',
      '首次与最终通过率差异是否反映重修压力？',
      '体育、思政、数学、英语等重点课程时段是否均衡？',
    ],
    actions: [
      { label: '进入专题', path: '/admin/reports/course-quality', primary: true },
      { label: '查看排课分析', path: '/admin/operation/schedule-analysis' },
    ],
    boundary: '课程差异不直接归因于教师；长期趋势需要多学期真实数据。',
  },
  {
    key: 'faculty',
    index: '04',
    title: '资源与师资风险',
    status: '可用',
    tone: 'faculty',
    value: '识别核心课程单点承担、职称梯队、课程团队稳定性及特殊空间约束，服务课程保障和师资建设。',
    questions: [
      '哪些核心课程长期依赖单一教师？',
      '课程团队年龄或职称结构是否存在接续风险？',
      '特殊教室和高峰时段是否限制课程供给？',
    ],
    actions: [
      { label: '进入专题', path: '/admin/reports/faculty-resource-risk', primary: true },
      { label: '查看课程团队', path: '/admin/faculty/team' },
    ],
    boundary: '年龄风险必须等待真实人事年龄段；不使用模拟画像评价教师。',
  },
  {
    key: 'schedule',
    index: '05',
    title: '排课策略与方案优化',
    status: '规划中',
    tone: 'schedule',
    value: '沉淀历史排课规律，预测新学年压力，支持冲突诊断和候选方案 A/B 比较。',
    questions: [
      '哪些历史分布是稳定倾向，哪些由资源约束造成？',
      '新学年哪些教师、学生群体和教室成为瓶颈？',
      '调整时段后解决什么冲突，又增加什么代价？',
    ],
    actions: [
      { label: '进入专题', path: '/admin/reports/schedule-strategy', primary: true },
      { label: '查看教室资源', path: '/admin/operation/classroom' },
    ],
    boundary: '不自动生成或发布最终课表；当前一个真实学期只能展示实际分布。',
  },
]

function statusType(status: string) {
  if (status === '可用') return 'success'
  if (status === 'AI增强') return 'primary'
  if (status === '规划中') return 'info'
  return 'warning'
}

function go(path: string) {
  router.push(path)
}
</script>

<style scoped>
.sa-head-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.topic-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.topic-card {
  border: 1px solid #e2e8f0;
  border-top: 4px solid #4f46e5;
  border-radius: 12px;
  background: #fff;
  padding: 18px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, .04);
}

.topic-card.ai { border-top-color: #4f46e5; background: linear-gradient(180deg, #ffffff 0%, #f8f7ff 100%); }
.topic-card.risk { border-top-color: #e11d48; }
.topic-card.plan { border-top-color: #0d9488; }
.topic-card.course { border-top-color: #4f46e5; }
.topic-card.faculty { border-top-color: #d97706; }
.topic-card.schedule { border-top-color: #7c3aed; }

.topic-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.topic-index {
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: .12em;
}

.topic-card h3 {
  margin: 10px 0 8px;
  font-size: 18px;
  color: #1e293b;
}

.value {
  min-height: 48px;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.questions {
  margin: 12px 0;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  color: #475569;
  font-size: 12px;
  line-height: 1.8;
}

.questions div::before {
  content: '·';
  margin-right: 7px;
  color: #4f46e5;
  font-weight: 700;
}

.topic-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.boundary {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.6;
}

.roadmap {
  margin-top: 16px;
}

.roadmap :deep(.el-step__description) {
  font-size: 11px;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .topic-grid {
    grid-template-columns: 1fr;
  }
}
</style>
