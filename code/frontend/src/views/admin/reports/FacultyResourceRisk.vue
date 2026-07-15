<template>
  <div>
    <el-breadcrumb separator="/">
      <el-breadcrumb-item to="/admin/reports">管理决策专题</el-breadcrumb-item>
      <el-breadcrumb-item>资源与师资风险</el-breadcrumb-item>
    </el-breadcrumb>

    <h2 class="sa-page-title">资源与师资风险</h2>
    <p class="sa-page-sub">
      从真实教学任务识别课程团队单点承担、职称信息缺口和已知职称梯队线索，帮助教务处与学院提前发现课程保障风险。
    </p>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="年龄风险暂不可判断"
      :description="definition.boundary"
    />

    <el-skeleton :loading="loading" animated :rows="5">
      <div class="kpis">
        <div v-for="x in kpis" :key="x.label" class="kpi">
          <span>
            {{ x.label }}
            <el-tooltip :content="x.help">
              <i>?</i>
            </el-tooltip>
          </span>
          <b>{{ x.value }}</b>
          <small>{{ x.note }}</small>
        </div>
      </div>

      <div class="ai-toolbar">
        <el-button type="primary" plain @click="openTopicAi">
          AI研判本专题
        </el-button>
      </div>

      <section class="sa-card">
        <div class="sa-card-title">
          需要进一步核查的课程团队
          <span class="extra">关注原因可以同时满足多项，AI研判会结合覆盖学生数与团队结构给出核查优先级</span>
        </div>

        <el-table :data="data.courses" stripe>
          <el-table-column prop="course_name" label="课程" min-width="190" />
          <el-table-column prop="teacher_count" label="实际授课教师" width="120" />
          <el-table-column prop="lesson_count" label="教学班" width="90" />
          <el-table-column prop="enrolled" label="选课人数" width="100" />
          <el-table-column label="职称已知/团队人数" width="140">
            <template #default="{ row }">{{ row.known_title_count }} / {{ row.teacher_count }}</template>
          </el-table-column>
          <el-table-column label="教授/副教授" width="120">
            <template #default="{ row }">{{ row.professor_count }} / {{ row.associate_professor_count }}</template>
          </el-table-column>
          <el-table-column label="关注原因" min-width="250">
            <template #default="{ row }">
              <el-tag
                v-for="r in row.attention_reasons"
                :key="r"
                :type="r === 'single_teacher' ? 'danger' : 'warning'"
                size="small"
                class="tag"
              >
                {{ reason[r] || r }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openCourseAi(row)">AI研判</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="sa-card explain">
        <div class="sa-card-title">管理员可以如何使用</div>
        <p>
          单点承担用于安排备用教师和课程团队建设核查；职称缺失应先补齐人事主数据；已知成员无教授或副教授只提示结构核查，不代表课程质量存在问题。
          对覆盖学生数较高、且同时命中多个原因的课程，建议优先由学院确认课程团队稳定性，再由教务处统筹跨学院资源。
        </p>
      </section>
    </el-skeleton>

    <AIInsightDrawer
      v-model="aiDrawerVisible"
      :insight="aiInsight"
      :loading="aiLoading"
      title="师资保障AI研判"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AIInsightDrawer from '@/components/AIInsightDrawer.vue'
import {
  getFacultyCourseAIInsight,
  getFacultyResourceAIInsight,
} from '@/utils/ai'
import { http } from '@/utils/http'

const loading = ref(true)
const aiDrawerVisible = ref(false)
const aiLoading = ref(false)
const aiInsight = ref<any>(null)

const data = reactive<any>({
  semester: '',
  summary: {},
  courses: [],
})
const definition = reactive<any>({})

const reason: Record<string, string> = {
  single_teacher: '当期单一教师承担',
  title_incomplete: '职称信息不完整',
  no_senior_title: '已知成员无教授/副教授',
}

const currentSemester = computed(() => data.semester || '2023-2024-1')

const kpis = computed(() => [
  {
    label: '真实团队课程',
    value: `${data.summary.courses || 0} 门`,
    note: '当前接入学期',
    help: '具有真实教学任务教师关联的去重课程数。',
  },
  {
    label: '实际授课教师',
    value: `${data.summary.teachers || 0} 人`,
    note: '按教师代码去重',
    help: '当前接入学期承担教学任务的去重教师人数。',
  },
  {
    label: '单一教师承担课程',
    value: `${data.summary.single_teacher_courses || 0} 门`,
    note: '优先核查备份能力',
    help: definition.single_teacher || '',
  },
  {
    label: '职称信息不完整课程',
    value: `${data.summary.title_incomplete_courses || 0} 门`,
    note: '先补主数据',
    help: definition.title_incomplete || '',
  },
  {
    label: '已知成员无高职称',
    value: `${data.summary.no_senior_title_courses || 0} 门`,
    note: '仅作结构核查',
    help: definition.no_senior_title || '',
  },
])

async function loadData() {
  loading.value = true
  try {
    const result = await http.get<any>('/v2/topics/faculty-resource-risk')
    Object.assign(data, result)
    Object.assign(definition, result.definition || {})
  } finally {
    loading.value = false
  }
}

async function openTopicAi() {
  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getFacultyResourceAIInsight(currentSemester.value)
  } finally {
    aiLoading.value = false
  }
}

async function openCourseAi(row: any) {
  const courseId = row.course_id || row.courseId
  if (!courseId) return

  aiDrawerVisible.value = true
  aiLoading.value = true
  aiInsight.value = null
  try {
    aiInsight.value = await getFacultyCourseAIInsight(courseId, currentSemester.value)
  } finally {
    aiLoading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.sa-page-title {
  margin-top: 12px;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin: 14px 0;
}

.kpi {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 15px;
}

.kpi span,
.kpi small {
  display: block;
  color: #64748b;
}

.kpi b {
  display: block;
  font-size: 24px;
  margin: 6px 0;
}

.kpi i {
  margin-left: 5px;
  font-style: normal;
}

.ai-toolbar {
  display: flex;
  justify-content: flex-end;
  margin: -2px 0 12px;
}

.sa-card {
  margin-bottom: 14px;
}

.tag {
  margin: 2px;
}

.explain p {
  font-size: 13px;
  color: #475569;
  line-height: 1.8;
}

@media (max-width: 1100px) {
  .kpis {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
