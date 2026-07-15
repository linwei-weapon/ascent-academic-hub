<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
      <div>
        <h2 class="sa-page-title">学业预警监控</h2>
        <p class="sa-page-sub">数据来源：学校学籍、成绩数据与当前已激活规则计算结果 · 点击等级卡片筛选核查对象</p>
      </div>
      <div class="alert-actions">
        <el-button type="primary" plain @click="openGroupInsight">AI研判当前切片</el-button>
      </div>
    </div>

    <div v-if="hasFilters" class="filter-feedback">
      <div><b>当前查看：</b>{{ activeFilterText }}<span>，匹配 {{ filteredList.length }} 条预警</span></div>
      <el-button link type="primary" @click="clearFilters">清除全部筛选</el-button>
    </div>

    <!-- KPI 行（点击联动筛选） -->
    <div class="alert-kpi-row">
      <div v-for="a in levels" :key="a.key" class="alert-kpi" :class="{ active: activeFilter === a.key }"
        role="button" tabindex="0" :aria-pressed="activeFilter === a.key"
        @click="toggleFilter(a)" @keydown.enter.prevent="toggleFilter(a)" @keydown.space.prevent="toggleFilter(a)">
        <div class="ak-val tnum" :style="{ color: a.color }">{{ data.summary[a.key] }}</div>
        <div class="ak-label"><KpiLabel :label="a.label" :formula="a.formula" /></div>
        <div class="ak-hint">{{ activeFilter === a.key ? '▼ 已筛选' : '点击筛选' }}</div>
      </div>
      <div class="alert-kpi" :class="{ active: activeFilter === 'inbox' }" role="button" tabindex="0"
        :aria-pressed="activeFilter === 'inbox'" @click="toggleInbox" @keydown.enter.prevent="toggleInbox" @keydown.space.prevent="toggleInbox">
        <div class="ak-val tnum" style="color:#4F46E5">{{ data.summary.inbox }}</div>
        <div class="ak-label"><KpiLabel label="我的待办" formula="分派给当前用户且尚未解决/关闭的预警事件" /></div>
        <div class="ak-hint">{{ activeFilter === 'inbox' ? '▼ 已筛选' : '点击筛选' }}</div>
      </div>
      <div class="alert-kpi" @click="clearFilters">
        <div class="ak-val tnum" style="color:#0D9488">{{ data.summary.resolvedRate }}</div>
        <div class="ak-label"><KpiLabel label="解决率" formula="已解决预警数÷预警总数×100%" /></div>
        <div class="ak-hint">显示全部</div>
      </div>
    </div>

    <!-- 重点关注 -->
    <div class="sa-card" style="margin-bottom:16px" v-if="focusStudents.length">
      <div class="sa-card-title">重点关注 <span class="extra">严重 + 未处理 · 共 {{ focusStudents.length }} 人需立即关注</span></div>
      <div class="focus-grid">
        <div v-for="f in focusStudents.slice(0,4)" :key="f.sid" class="focus-card" @click="showStudent(f)">
          <div class="focus-name">{{ f.name }} <span class="sa-faint" style="font-weight:400">{{ f.class }}</span></div>
          <div class="focus-type">{{ f.type }} · {{ f.detail }}</div>
          <div class="sa-faint" style="font-size:11px;margin-top:2px">{{ f.college }} · 触发：{{ f.time }}</div>
        </div>
      </div>
    </div>

    <!-- 趋势 + 分布 -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">月度预警趋势 <span class="extra">各月新增预警数</span></div>
          <EChart v-if="data.monthlyTrend.length" :option="trendOption" :height="220" />
          <div v-else class="sa-faint" style="font-size:12px">暂无趋势数据</div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="sa-card">
          <div class="sa-card-title">按学院预警分布 <span class="extra">严重 / 警告 / 提醒 分层</span></div>
          <EChart v-if="data.collegeDist.length" :option="distOption" :height="Math.max(200, data.collegeDist.length*28)" />
          <div v-else class="sa-faint" style="font-size:12px">暂无分布数据</div>
        </div>
      </el-col>
    </el-row>

    <!-- 主内容区 -->
    <el-row :gutter="16">
      <el-col :span="5">
        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">筛选条件</div>
          <el-select v-model="fCollege" placeholder="学院" size="small" style="width:100%;margin-bottom:8px" clearable>
            <el-option label="全部学院" value="" /><el-option v-for="c in filterColleges" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="fType" placeholder="预警类型" size="small" style="width:100%;margin-bottom:8px" clearable>
            <el-option label="全部类型" value="" /><el-option v-for="t in filterTypes" :key="t" :label="t" :value="t" />
          </el-select>
          <el-select v-model="fLevel" placeholder="预警等级" size="small" style="width:100%;margin-bottom:8px" clearable>
            <el-option label="全部等级" value="" /><el-option label="严重" value="严重" /><el-option label="警告" value="警告" /><el-option label="提醒" value="提醒" />
          </el-select>
          <el-select v-model="fStatus" placeholder="处理状态" size="small" style="width:100%" clearable>
            <el-option label="全部状态" value="" />
            <el-option v-for="s in workflowStatuses" :key="s.value" :label="s.label" :value="s.label" />
          </el-select>
        </div>
      </el-col>

      <el-col :span="19">
        <div class="sa-card">
          <div class="sa-card-title">
            <span>预警列表<span class="sa-faint" style="font-weight:400;font-size:12px;margin-left:8px">共 {{ filteredList.length }} 条</span></span>
            <el-button size="small" @click="exportList">导出 CSV</el-button>
          </div>
          <el-table :data="pagedList" size="small" @row-click="showStudent" row-class-name="row-clickable" :class="{'is-filtered':hasFilters}">
            <el-table-column prop="name" label="姓名" width="70"><template #default="{row}"><span class="link">{{ row.name }}</span></template></el-table-column>
            <el-table-column prop="sid" label="学号" width="105" />
            <el-table-column prop="college" label="学院" width="130" />
            <el-table-column prop="class" label="班级" width="130" />
            <el-table-column prop="level" label="等级" width="64"><template #default="{row}"><el-tag :type="tagType(row.level)" size="small">{{ row.level }}</el-tag></template></el-table-column>
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column prop="detail" label="触发数据链" min-width="180"><template #default="{row}"><span style="font-size:12px">{{ row.detail }}</span></template></el-table-column>
            <el-table-column prop="status" label="状态" width="76"><template #default="{row}"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column prop="failSummary" label="挂科溯源摘要" width="160"><template #default="{row}"><el-tooltip :content="row.failSummary || ''" placement="top" :disabled="!row.failSummary" :show-after="300"><span class="fail-summary-cell">{{ row.failSummary || '-' }}</span></el-tooltip></template></el-table-column>
            <el-table-column label="AI研判" width="88" fixed="right"><template #default="{row}"><el-button link type="primary" @click.stop="openStudentInsight(row)">AI研判</el-button></template></el-table-column>
            <el-table-column prop="time" label="时间" width="92" />
          </el-table>
          <el-pagination v-model:current-page="page" :page-size="15" :total="filteredList.length" layout="prev,next,total" size="small" style="margin-top:12px;justify-content:flex-end" />
        </div>
      </el-col>
    </el-row>

    <!-- 抽屉：学生数据查看（对齐真实 student 接口） -->
    <el-drawer v-model="drawerVisible" title="预警学生数据查看" size="520px">
      <div v-if="student.name">
        <div class="drawer-info">
          {{ student.code }} · {{ student.collegeName }} · {{ student.majorName }} · {{ student.className }}
          <el-button size="small" type="primary" text style="margin-left:8px" @click="router.push('/admin/student/' + student.code)">查看完整档案 →</el-button>
          <el-button size="small" type="primary" text @click="openStudentInsight({ sid: student.code })">AI研判</el-button>
        </div>

        <el-row :gutter="8" style="margin-bottom:12px">
          <el-col :span="6" v-for="k in (student.kpis || [])" :key="k.label">
            <div class="drawer-kpi">
              <div class="dk-val tnum" :style="{ color: k.color || '#1E293B' }">{{ k.value }}</div>
              <div class="dk-label">{{ k.label }}</div>
            </div>
          </el-col>
        </el-row>

        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">GPA 趋势</div>
          <EChart v-if="student.gpaHistory && student.gpaHistory.length" :option="gpaTrendOption" :height="150" />
          <div v-else class="sa-faint" style="font-size:12px">暂无 GPA 数据</div>
        </div>

        <!-- V1.1 学业统计摘要 -->
        <div class="sa-card" style="margin-bottom:12px" v-if="student.studySummary">
          <div class="sa-card-title">学业统计摘要</div>
          <el-row :gutter="12">
            <el-col :span="12">
              <div class="study-stat study-stat--pass">
                <div class="study-stat__label">已通过</div>
                <div class="study-stat__items">
                  <span class="study-stat__item">已修 <b>{{ student.studySummary.passed?.courses ?? '-' }}</b> 门</span>
                  <span class="study-stat__item"><b>{{ student.studySummary.passed?.hours ?? '-' }}</b> 学时</span>
                  <span class="study-stat__item"><b>{{ student.studySummary.passed?.credits ?? '-' }}</b> 学分</span>
                </div>
                <div class="study-stat__rate" style="color:#0D9488">完成率 {{ student.studySummary.passed?.completionRate ?? '-' }}%</div>
              </div>
            </el-col>
            <el-col :span="12">
              <div class="study-stat study-stat--fail">
                <div class="study-stat__label">挂科</div>
                <div class="study-stat__items">
                  <span class="study-stat__item">挂科 <b>{{ student.studySummary.failed?.courses ?? '-' }}</b> 门</span>
                  <span class="study-stat__item"><b>{{ student.studySummary.failed?.hours ?? '-' }}</b> 学时</span>
                  <span class="study-stat__item"><b>{{ student.studySummary.failed?.credits ?? '-' }}</b> 学分</span>
                </div>
                <div class="study-stat__rate" style="color:#E11D48">当前挂科 <b>{{ student.studySummary.failed?.currentCourses ?? '-' }}</b> 门</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- V1.1 挂科溯源 -->
        <div class="sa-card" style="margin-bottom:12px" v-if="student.failTrace && student.failTrace.length">
          <div class="sa-card-title">挂科溯源</div>
          <el-table :data="student.failTrace" size="small" style="width:100%">
            <el-table-column prop="courseName" label="课程名称" min-width="140"><template #default="{row}"><span style="color:#E11D48">{{ row.courseName }}</span></template></el-table-column>
            <el-table-column prop="teacherName" label="授课教师" width="80" />
            <el-table-column prop="college" label="开课学院" width="110" />
            <el-table-column prop="failCount" label="挂科次数" width="76"><template #default="{row}"><span style="font-weight:600;color:#E11D48">{{ row.failCount }}</span></template></el-table-column>
            <el-table-column prop="semesters" label="挂科学期" min-width="130"><template #default="{row}"><span style="font-size:11px">{{ row.semesters }}</span></template></el-table-column>
          </el-table>
        </div>

        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">预警历史与变化</div>
          <div v-if="student.alertComparison" class="comparison-grid">
            <div><b>{{ student.alertComparison.totalCycles || 0 }}</b><span>历史预警</span></div>
            <div><b>{{ student.alertComparison.activeAlerts || 0 }}</b><span>当前有效</span></div>
            <div><b>{{ student.alertComparison.interventionCount || 0 }}</b><span>干预记录</span></div>
            <div><b>{{ student.alertComparison.latestChange || '—' }}</b><span>最近变化</span></div>
          </div>
          <div v-if="student.alertHistory && student.alertHistory.length">
            <div v-for="a in student.alertHistory" :key="a.time + a.type" class="rule-row">
              <div class="history-head"><div><el-tag :type="tagType(a.level)" size="small">{{ a.level }}</el-tag><span>{{ a.type }}</span></div><el-tag size="small" effect="plain">{{ a.changeType }}</el-tag></div>
              <div class="sa-faint" style="font-size:11px;margin-top:3px">{{ a.detail }} · {{ a.time }}<span v-if="a.workflowStatusLabel"> · {{ a.workflowStatusLabel }}</span></div>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">无历史记录</div>
        </div>

        <div class="sa-card" style="margin-bottom:12px" v-if="student.interventionHistory?.length">
          <div class="sa-card-title">已记录干预过程 <span class="extra">同步呈现在学生完整档案</span></div>
          <div v-for="item in student.interventionHistory" :key="item.event_id + '-' + item.created_at" class="intervention-item">
            <div><b>{{ item.action_type }}</b><span>{{ item.operator }} · {{ item.created_at }}</span></div>
            <p>{{ item.content }}</p>
            <small v-if="item.next_action_at">下次跟进：{{ item.next_action_at }}</small>
          </div>
        </div>

        <div class="sa-card" style="margin-bottom:12px" v-if="workflow.eventId">
          <div class="sa-card-title">
            <span>预警跟进闭环</span>
            <el-tag :type="statusType(workflow.workflowStatusLabel)" size="small">{{ workflow.workflowStatusLabel }}</el-tag>
          </div>
          <div class="workflow-meta">
            主责任人：{{ workflow.assignees?.[0]?.username || '未分派' }}
            <span v-if="workflow.assignees?.[0]?.assignment_reason"> · {{ workflow.assignees[0].assignment_reason }}</span>
          </div>
          <div class="workflow-meta">
            风险周期：第 {{ workflow.cycleNo || 1 }} 周期
            <span v-if="workflow.recurrenceOfEventId"> · 前序事件 #{{ workflow.recurrenceOfEventId }}</span>
            <span v-if="workflow.cycleReason"> · {{ workflow.cycleReason }}</span>
          </div>
          <div class="workflow-actions">
            <el-select v-model="nextStatus" size="small" style="width:120px" placeholder="更新状态">
              <el-option v-for="s in workflowStatuses" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-button size="small" type="primary" :loading="savingWorkflow" @click="saveStatus">更新状态</el-button>
          </div>
          <el-input v-model="followupContent" type="textarea" :rows="2" maxlength="1000" show-word-limit placeholder="填写联系、约谈或帮扶记录" />
          <div style="display:flex;justify-content:flex-end;margin-top:8px">
            <el-button size="small" type="primary" :loading="savingWorkflow" @click="addFollowup">添加跟进记录</el-button>
          </div>
          <div v-if="workflow.followups?.length" class="followup-list">
            <div v-for="f in workflow.followups" :key="f.followup_id" class="followup-item">
              <div><b>{{ f.operator }}</b> · {{ f.action_type }} <span class="sa-faint">{{ f.created_at }}</span></div>
              <div class="followup-content">{{ f.content }}</div>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px;margin-top:10px">暂无人工跟进记录</div>
        </div>

        <div class="sa-card" style="margin-bottom:12px">
          <div class="sa-card-title">挂科课程明细</div>
          <div v-if="failScores.length">
            <div v-for="s in failScores" :key="s.courseName + s.semester" class="score-row">
              <span style="color:#E11D48">{{ s.courseName }}<span class="sa-faint" style="margin-left:6px">{{ s.semester }}</span></span>
              <span style="color:#E11D48;font-weight:600" class="tnum">{{ s.score }} 分</span>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">无挂科记录</div>
        </div>

        <div class="sa-card">
          <div class="sa-card-title">近期全部成绩</div>
          <div v-if="student.scores && student.scores.length">
            <div v-for="s in student.scores" :key="s.courseName + s.semester" class="score-row">
              <span>{{ s.courseName }}</span>
              <span :style="{ color: s.passed ? '#0D9488' : '#E11D48', fontWeight: 600 }" class="tnum">{{ s.score }}</span>
            </div>
          </div>
          <div v-else class="sa-faint" style="font-size:12px">暂无成绩数据</div>
        </div>

        <div class="sa-faint" style="font-size:11px;text-align:center;margin-top:12px">
          学业数据来源：教务系统 · 跟进记录保存在本平台 · 不回写教务源库
        </div>
      </div>
      <div v-else class="sa-faint" style="font-size:12px;text-align:center;padding-top:40px">加载中…</div>
    </el-drawer>
    <AIInsightDrawer v-model="aiDrawerVisible" :insight="aiInsight" :loading="aiLoading" title="AI研判" />
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, ref, computed, watch } from 'vue'
import { http } from '@/utils/http';
import { getAlertSummaryAIInsight, getStudentAIInsight } from '@/utils/ai';
import KpiLabel from '@/components/KpiLabel.vue';
import EChart from '@/components/EChart.vue';
import AIInsightDrawer from '@/components/AIInsightDrawer.vue';
import { exportCsv } from '@/utils/export';
import { authStore } from '@/store/auth';

const drawerVisible = ref(false); const student = ref({} as any);
const workflow = ref({} as any); const followupContent = ref(''); const nextStatus = ref('');
const savingWorkflow = ref(false); const currentEventId = ref<number | null>(null);
const page = ref(1); const fCollege = ref(''); const fType = ref(''); const fLevel = ref(''); const fStatus = ref('');
const activeFilter = ref('');
const aiDrawerVisible = ref(false); const aiLoading = ref(false); const aiInsight = ref<any>(null);

const levels = [
  { key: 'critical', label: '严重', color: '#E11D48', formula: '触发条件满足且等级=严重' },
  { key: 'warning', label: '警告', color: '#F97316', formula: '触发条件满足且等级=警告' },
  { key: 'info', label: '提醒', color: '#D97706', formula: '触发条件满足且等级=提醒' },
  { key: 'resolved', label: '已解决', color: '#0D9488', formula: '干预状态=已解决的预警数' },
];
const workflowStatuses = [
  { value: 'new', label: '待处理' }, { value: 'assigned', label: '已分派' },
  { value: 'notified', label: '已通知' }, { value: 'contacted', label: '已联系' },
  { value: 'supporting', label: '帮扶中' }, { value: 'review_pending', label: '待复核' },
  { value: 'resolved', label: '已解决' }, { value: 'closed', label: '已关闭' },
];

const data = reactive({
  summary: { critical: 0, warning: 0, info: 0, resolved: 0, resolvedRate: '0%', inbox: 0, workflow: {} } as Record<string, any>,
  rules: [] as any[], list: [] as any[],
  monthlyTrend: [] as any[], collegeDist: [] as any[],
});

// 筛选项由真实列表派生，避免与数据不一致
const filterColleges = computed(() => [...new Set(data.list.map((x: any) => x.college).filter(Boolean))]);
const filterTypes = computed(() => [...new Set(data.list.map((x: any) => x.type).filter(Boolean))]);

const focusStudents = computed(() =>
  data.list.filter((x: any) => x.level === '严重' && (x.status === '未处理' || !x.status))
);

const failScores = computed(() => (student.value.scores || []).filter((s: any) => !s.passed));

const filteredList = computed(() => {
  let arr = data.list;
  if (fCollege.value) arr = arr.filter((x: any) => x.college === fCollege.value);
  if (fType.value) arr = arr.filter((x: any) => x.type === fType.value);
  if (fLevel.value) arr = arr.filter((x: any) => x.level === fLevel.value);
  if (fStatus.value) arr = arr.filter((x: any) => x.status === fStatus.value);
  if (activeFilter.value === 'inbox') {
    const username = authStore.user?.username;
    arr = arr.filter((x: any) => x.assignee === username && !['已解决', '已关闭'].includes(x.status));
  }
  return arr;
});
const hasFilters = computed(() => Boolean(activeFilter.value || fCollege.value || fType.value || fLevel.value || fStatus.value));
const activeFilterText = computed(() => {
  const parts:string[] = [];
  if (fLevel.value) parts.push(`等级=${fLevel.value}`);
  if (fStatus.value) parts.push(`状态=${fStatus.value}`);
  if (fCollege.value) parts.push(`学院=${fCollege.value}`);
  if (fType.value) parts.push(`类型=${fType.value}`);
  if (activeFilter.value === 'inbox') parts.unshift('范围=我的待办');
  return parts.join('、') || '全部预警';
});
const pagedList = computed(() => filteredList.value.slice((page.value - 1) * 15, page.value * 15));

function fmtMonth(m: string) { const p = String(m).split('-'); return p.length > 1 ? `${+p[1]}月` : m; }
function tagType(level: string) { return level === '严重' ? 'danger' : level === '警告' ? 'warning' : 'info'; }
function statusType(s: string) { return s === '已解决' ? 'success' : s === '未处理' ? 'danger' : s === '已约谈' ? 'warning' : 'info'; }

const trendOption = computed(() => {
  const mt = data.monthlyTrend || [];
  return {
    grid: { left: 6, right: 12, top: 24, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'category', data: mt.map((m: any) => fmtMonth(m.month)), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'bar', barWidth: '46%', itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: mt.map((m: any) => ({ value: m.count, itemStyle: { color: m.count > 60 ? '#E11D48' : m.count > 40 ? '#F97316' : '#D97706' } })),
      label: { show: true, position: 'top', formatter: '{c}', color: '#64748B', fontSize: 11 },
    }],
  };
});

const distOption = computed(() => {
  const cd = [...(data.collegeDist || [])].reverse();
  return {
    grid: { left: 6, right: 24, top: 6, bottom: 28, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['严重', '警告', '提醒'], bottom: 0, textStyle: { color: '#64748B', fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    yAxis: { type: 'category', data: cd.map((c: any) => c.name), axisLabel: { color: '#475569', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    series: [
      { name: '严重', type: 'bar', stack: 't', data: cd.map((c: any) => c.critical), itemStyle: { color: '#E11D48' }, barWidth: '56%' },
      { name: '警告', type: 'bar', stack: 't', data: cd.map((c: any) => c.warning), itemStyle: { color: '#F97316' } },
      { name: '提醒', type: 'bar', stack: 't', data: cd.map((c: any) => c.info), itemStyle: { color: '#D97706' } },
    ],
  };
});

const gpaTrendOption = computed(() => {
  const g = student.value.gpaHistory || [];
  return {
    grid: { left: 4, right: 10, top: 16, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: g.map((_: any, i: number) => `S${i + 1}`), axisLabel: { color: '#94A3B8', fontSize: 11 }, axisLine: { lineStyle: { color: '#E2E8F0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 5, axisLabel: { color: '#94A3B8' }, splitLine: { lineStyle: { color: '#EEF1F5' } } },
    series: [{
      type: 'line', smooth: true, data: g, symbolSize: 7, lineStyle: { width: 3, color: '#4F46E5' }, itemStyle: { color: '#4F46E5' },
      areaStyle: { color: 'rgba(79,70,229,0.08)' },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 2 }], lineStyle: { color: '#E11D48', type: 'dashed' }, label: { formatter: '预警线 2.0', color: '#E11D48', fontSize: 10 } },
    }],
  };
});

function toggleFilter(a: any) {
  if (activeFilter.value === a.key) {
    activeFilter.value = ''; fLevel.value = ''; fStatus.value = '';
  } else {
    activeFilter.value = a.key;
    if (a.key === 'resolved') { fStatus.value = '已解决'; fLevel.value = ''; }
    else { fLevel.value = a.label; fStatus.value = ''; }
  }
  page.value = 1;
}
function toggleInbox() {
  const selected = activeFilter.value === 'inbox';
  activeFilter.value = selected ? '' : 'inbox';
  fLevel.value = '';
  fStatus.value = '';
  page.value = 1;
}
function clearFilters() {
  activeFilter.value = ''; fLevel.value = ''; fStatus.value = ''; fCollege.value = ''; fType.value = '';
  page.value = 1;
}

watch([fCollege, fType, fLevel, fStatus], () => {
  // 下拉条件与顶层卡片可组合；手工改掉卡片对应条件时同步取消高亮。
  const selected = levels.find((item) => item.key === activeFilter.value);
  if (selected && selected.key === 'resolved' && fStatus.value !== '已解决') activeFilter.value = '';
  if (selected && selected.key !== 'resolved' && fLevel.value !== selected.label) activeFilter.value = '';
  page.value = 1;
});

onMounted(async () => {
  const d = await http.get('/admin/alerts');
  if (d) Object.assign(data, d);
});

async function showStudent(row: any) {
  drawerVisible.value = true;
  student.value = {};
  workflow.value = {}; currentEventId.value = row.eventId || null;
  followupContent.value = ''; nextStatus.value = '';
  try {
    const d = await http.get('/admin/student/' + row.sid);
    student.value = d || {};
    if (row.eventId) await loadWorkflow(row.eventId);
  } catch {
    // 不伪造数据：仅回填列表中已有的真实字段，其余留空
    student.value = { name: row.name, code: row.sid, collegeName: row.college, className: row.class, majorName: '', kpis: [], gpaHistory: row.gpaHistory || [], alertHistory: [], scores: [] };
  }
}

async function openStudentInsight(row: any) {
  const sid = row.sid || row.code || row.student_id;
  if (!sid) return;
  aiDrawerVisible.value = true;
  aiLoading.value = true;
  aiInsight.value = null;
  try {
    aiInsight.value = await getStudentAIInsight(sid, 'alert');
  } finally {
    aiLoading.value = false;
  }
}

async function openGroupInsight() {
  aiDrawerVisible.value = true;
  aiLoading.value = true;
  aiInsight.value = null;
  try {
    aiInsight.value = await getAlertSummaryAIInsight({
      level: fLevel.value,
      type: fType.value,
      status: fStatus.value,
      college: fCollege.value,
    });
  } finally {
    aiLoading.value = false;
  }
}

async function loadWorkflow(eventId: number) {
  const d = await http.get('/admin/alert-events/' + eventId);
  workflow.value = d || {};
  nextStatus.value = workflow.value.workflowStatus || '';
}

async function addFollowup() {
  if (!currentEventId.value || !followupContent.value.trim()) {
    ElMessage.warning('请先填写跟进内容'); return;
  }
  savingWorkflow.value = true;
  try {
    await http.post('/admin/alert-events/' + currentEventId.value + '/followups', {
      action_type: '人工跟进', content: followupContent.value.trim(),
    });
    followupContent.value = '';
    await loadWorkflow(currentEventId.value);
    ElMessage.success('跟进记录已保存');
  } finally { savingWorkflow.value = false; }
}

async function saveStatus() {
  if (!currentEventId.value || !nextStatus.value) return;
  savingWorkflow.value = true;
  try {
    await http.put('/admin/alert-events/' + currentEventId.value + '/status', {
      status: nextStatus.value, reason: '在预警详情中更新',
    });
    await loadWorkflow(currentEventId.value);
    const row = data.list.find((x: any) => x.eventId === currentEventId.value);
    if (row) row.status = workflow.value.workflowStatusLabel;
    ElMessage.success('预警状态已更新');
  } finally { savingWorkflow.value = false; }
}

function exportList() {
  if (!filteredList.value.length) { window.alert('当前无数据可导出'); return }
  exportCsv('学业预警列表', [
    { prop: 'name', label: '姓名' }, { prop: 'sid', label: '学号' },
    { prop: 'college', label: '学院' }, { prop: 'class', label: '班级' },
    { prop: 'level', label: '等级' }, { prop: 'type', label: '类型' },
    { prop: 'detail', label: '触发数据链' }, { prop: 'status', label: '状态' },
    { prop: 'failSummary', label: '挂科溯源摘要' }, { prop: 'time', label: '时间' },
  ], filteredList.value)
}
</script>

<style scoped>
.alert-kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px; }
.alert-actions { padding-top: 4px; white-space: nowrap; }
.alert-kpi {
  background: #fff; border: 1.5px solid var(--sa-border); border-radius: 14px;
  padding: 14px 12px; text-align: center; cursor: pointer; transition: all .18s;
}
.alert-kpi:hover { border-color: #c7d2fe; transform: translateY(-2px); }
.alert-kpi:focus-visible { outline: 3px solid #c7d2fe; outline-offset: 2px; }
.alert-kpi.active { border-color: var(--sa-primary); box-shadow: 0 0 0 3px #eef2ff; }
.ak-val { font-family: var(--sa-font-head); font-size: 24px; font-weight: 700; line-height: 1; }
.ak-label { font-size: 12px; color: var(--sa-muted); margin-top: 6px; }
.ak-hint { font-size: 10px; color: var(--sa-faint); margin-top: 3px; }
.filter-feedback { margin:-4px 0 14px; padding:9px 12px; display:flex; justify-content:space-between; align-items:center; background:#eef2ff; border:1px solid #c7d2fe; border-radius:9px; color:#3730a3; font-size:12px; }
.filter-feedback span { color:#64748b; margin-left:3px; }
.is-filtered { animation:filter-in .18s ease-out; }
@keyframes filter-in { from { opacity:.55; transform:translateY(3px) } to { opacity:1; transform:none } }

.focus-grid { display: flex; gap: 12px; flex-wrap: wrap; }
.focus-card {
  flex: 1; min-width: 200px; padding: 10px 12px; cursor: pointer;
  background: #fff5f7; border: 1px solid #fecdd3; border-left: 3px solid #E11D48; border-radius: 10px; transition: all .18s;
}
.focus-card:hover { box-shadow: 0 4px 12px rgba(225,29,72,.12); }
.focus-name { font-size: 13px; font-weight: 600; color: var(--sa-text); }
.focus-type { font-size: 12px; color: #E11D48; margin-top: 4px; }

.rule-row { padding: 6px 0; border-bottom: 1px solid var(--sa-border); }
.rule-row:last-child { border-bottom: none; }
.history-head { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:12px; }
.history-head span { margin-left:6px; }
.comparison-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin:8px 0 10px; }
.comparison-grid div { padding:7px 4px; text-align:center; background:#f8fafc; border-radius:7px; }
.comparison-grid b { display:block; color:#1e293b; font-size:14px; }
.comparison-grid span { display:block; color:#94a3b8; font-size:10px; margin-top:2px; }
.intervention-item { padding:9px 0; border-bottom:1px solid var(--sa-border); font-size:12px; }
.intervention-item:last-child { border-bottom:0; }
.intervention-item div { display:flex; justify-content:space-between; gap:8px; }
.intervention-item div span,.intervention-item small { color:#94a3b8; }
.intervention-item p { margin:5px 0 2px; color:#475569; line-height:1.6; }
.rule-name { font-size: 12px; font-weight: 600; color: var(--sa-text); }
.score-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f1f5f9; font-size: 12px; }
.score-row:last-child { border-bottom: none; }

.drawer-info { font-size: 12px; color: var(--sa-muted); margin-bottom: 12px; }
.drawer-kpi { background: #f8fafc; border: 1px solid var(--sa-border); border-radius: 8px; padding: 8px 4px; text-align: center; }
.dk-val { font-family: var(--sa-font-head); font-size: 16px; font-weight: 700; }
.dk-label { font-size: 10px; color: var(--sa-muted); margin-top: 2px; }

.fail-summary-cell { font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:block; max-width:148px; }

.study-stat { border-radius:10px; padding:12px; height:100%; }
.study-stat--pass { background:#f0fdf6; border:1px solid #bbf7d0; }
.study-stat--fail { background:#fff5f7; border:1px solid #fecdd3; }
.study-stat__label { font-size:13px; font-weight:600; margin-bottom:6px; }
.study-stat--pass .study-stat__label { color:#0D9488; }
.study-stat--fail .study-stat__label { color:#E11D48; }
.study-stat__items { display:flex; flex-wrap:wrap; gap:4px 10px; font-size:11px; color:var(--sa-muted); margin-bottom:6px; }
.study-stat__item b { color:var(--sa-text); }
.study-stat__rate { font-size:12px; font-weight:600; }

.workflow-meta { font-size:12px; color:var(--sa-muted); margin-bottom:10px; }
.workflow-actions { display:flex; gap:8px; margin-bottom:10px; }
.followup-list { margin-top:10px; border-top:1px solid var(--sa-border); }
.followup-item { padding:8px 0; border-bottom:1px solid #f1f5f9; font-size:12px; }
.followup-content { margin-top:3px; color:var(--sa-text); white-space:pre-wrap; }

.link { color: var(--sa-primary); cursor: pointer; font-weight: 500; }
.link:hover { text-decoration: underline; }
:deep(.row-clickable) { cursor: pointer; }
:deep(.row-clickable:hover) { background: #eef2ff !important; }
</style>
