<template>
  <div>
    <h2 class="sa-page-title">学业进度监控</h2>
    <p class="sa-page-sub">对照培养方案，追踪每个学生的选课进度和学分缺口</p>

    <div v-if="!planName" class="sa-faint" style="text-align:center;padding:60px">
      请先选择有培养方案的专业（当前仅安全工程、海洋油气工程提供方案数据）
    </div>

    <template v-else>
      <div class="sa-summary" style="margin-bottom:16px">
        培养方案：{{ planName }} · 版本 {{ planVersion }} · 方案课程 {{ planCourses.length }} 门 · 适用学生 {{ progress.length }} 人
      </div>
      <el-alert title="判定口径" type="info" :closable="false" show-icon style="margin-bottom:12px">
        必修/选修及最低学分按培养方案模块规则判定，核心课按方案核心课标记识别；方案外课程单列，不计入方案完成学分。
      </el-alert>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-input v-model="keyword" placeholder="搜索学号或姓名" clearable style="width:200px" />
        <el-select v-model="statusFilter" placeholder="合规状态" clearable style="width:120px">
          <el-option label="合规" value="合规" /><el-option label="不合规" value="不合规" />
        </el-select>
        <el-select v-model="riskFilter" placeholder="风险等级" clearable style="width:120px">
          <el-option v-for="v in ['高','中','低']" :key="v" :label="v" :value="v" />
        </el-select>
        <el-button @click="exportCsv">导出当前结果</el-button>
        <span class="sa-faint" style="align-self:center">{{ filteredProgress.length }} 人</span>
      </div>

      <el-table :data="filteredProgress" stripe size="small" v-loading="loading">
        <el-table-column prop="studentId" label="学号" width="130" />
        <el-table-column prop="name" label="姓名" width="80" />
        <el-table-column prop="grade" label="年级" width="72" />
        <el-table-column label="已修/应修" width="120">
          <template #default="{row}">
            <span class="tnum">{{ row.earnedCredits }}</span>
            <span class="sa-faint">/{{ row.requiredCredits }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方案外学分" width="90" align="right">
          <template #default="{row}"><span class="tnum">{{ row.outsidePlanCredits }}</span></template>
        </el-table-column>
        <el-table-column label="完成率" width="100">
          <template #default="{row}">
            <el-progress :percentage="row.completionRate" :stroke-width="8"
              :color="row.completionRate >= 80 ? '#16A34A' : row.completionRate >= 60 ? '#EA580C' : '#DC2626'" />
          </template>
        </el-table-column>
        <el-table-column label="学分缺口" width="80" align="right">
          <template #default="{row}"><span class="tnum" :style="{color: row.gapCredits > 10 ? '#DC2626' : '#6B7280'}">{{ row.gapCredits }}</span></template>
        </el-table-column>
        <el-table-column label="缺口构成" min-width="170">
          <template #default="{row}">
            <span class="sa-faint">必修</span> <span class="tnum">{{ row.requiredGapCredits }}</span>
            <span class="sa-faint"> · 核心</span> <span class="tnum">{{ row.coreGapCredits }}</span>
            <span class="sa-faint"> · 选修</span> <span class="tnum">{{ row.electiveGapCredits }}</span>
          </template>
        </el-table-column>
        <el-table-column label="合规" width="76">
          <template #default="{row}">
            <el-tag size="small" :type="row.complianceStatus === '合规' ? 'success' : 'danger'">{{ row.complianceStatus }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="60">
          <template #default="{row}">
            <el-tag size="small" :type="row.riskLevel === '高' ? 'danger' : row.riskLevel === '中' ? 'warning' : 'success'">{{ row.riskLevel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="缺修课程" min-width="200">
          <template #default="{row}">
            <span v-for="(g, i) in row.gapCourses.slice(0, 3)" :key="i">
              <el-tag size="small" :type="g.isCore ? 'danger' : 'info'" style="margin:2px">{{ g.courseName }}</el-tag>
            </span>
            <span v-if="row.gapCourses.length > 3" class="sa-faint">+{{ row.gapCourses.length - 3 }}门</span>
          </template>
        </el-table-column>
        <el-table-column type="expand" width="42">
          <template #default="{row}">
            <div style="padding:8px 20px;line-height:2">
              <div><b>选修学分：</b>{{ row.electiveEarnedCredits }} / {{ row.electiveRequiredCredits }}</div>
              <div><b>认定学分：</b>{{ row.recognizedCredits }}；<b>已应用例外：</b>{{ row.appliedExceptions.length }} 条</div>
              <div v-if="row.courseGroupChecks.length"><b>课程组：</b>
                <el-tag v-for="g in row.courseGroupChecks" :key="g.groupId" size="small"
                  :type="g.status === '满足' ? 'success' : 'warning'" style="margin:2px 4px">
                  {{ g.groupName }} {{ g.passedCourses }}/{{ g.minCourses }}门 · {{ g.earnedCredits }}/{{ g.minCredits }}学分
                </el-tag>
              </div>
              <div><b>合规说明：</b><span v-if="!row.complianceIssues.length">暂无问题</span>
                <el-tag v-for="issue in row.complianceIssues" :key="issue.type" size="small"
                  :type="issue.level === 'high' ? 'danger' : issue.level === 'medium' ? 'warning' : 'info'"
                  style="margin:2px 4px">{{ issue.message }}</el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { http } from '@/utils/http'

const props = defineProps<{ majorId: string }>()

const loading = ref(false)
const planName = ref('')
const planVersion = ref('')
const planCourses = ref<any[]>([])
const progress = ref<any[]>([])
const keyword = ref('')
const statusFilter = ref('')
const riskFilter = ref('')
const filteredProgress = computed(() => progress.value.filter(row =>
  (!keyword.value || row.studentId.toLowerCase().includes(keyword.value.toLowerCase()) || (row.name || '').includes(keyword.value)) &&
  (!statusFilter.value || row.complianceStatus === statusFilter.value) &&
  (!riskFilter.value || row.riskLevel === riskFilter.value)
))

function exportCsv() {
  const header = ['学号','姓名','年级','方案版本','方案内学分','方案外学分','认定学分','必修缺口','核心缺口','选修缺口','合规状态','风险等级','问题']
  const rows = filteredProgress.value.map(r => [r.studentId,r.name,r.grade,planVersion.value,r.planEarnedCredits,
    r.outsidePlanCredits,r.recognizedCredits,r.requiredGapCredits,r.coreGapCredits,r.electiveGapCredits,
    r.complianceStatus,r.riskLevel,r.complianceIssues.map((i:any) => i.message).join('；')])
  const csv = '\uFEFF' + [header, ...rows].map(row => row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = `培养方案合规_${planVersion.value}.csv`; a.click()
  URL.revokeObjectURL(url)
}

async function load(major: string) {
  loading.value = true
  try {
    const data = await http.get<any>(`/admin/curriculum/progress/${major}`)
    if (data.planCourses?.length) {
      planName.value = data.planName || major
      planVersion.value = data.planVersion || ''
      planCourses.value = data.planCourses
      progress.value = data.progress || []
    } else {
      planName.value = ''
      planVersion.value = ''
      planCourses.value = []
      progress.value = []
    }
  } catch { /* http 工具已 toast */ }
  finally { loading.value = false }
}

onMounted(() => load(props.majorId))
watch(() => props.majorId, (v) => load(v))
</script>
