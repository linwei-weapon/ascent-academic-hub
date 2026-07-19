<template>
  <div v-loading="loading" element-loading-text="正在加载培养方案与学生执行证据，请稍候…" element-loading-background="rgba(248,250,252,.82)">
    <div class="sa-head-row">
      <div>
        <h2 class="sa-page-title">{{ pageTitle }}</h2>
        <p class="sa-page-sub">基于真实培养方案与学生课程记录，核查方案结构、学分要求和学生执行情况</p>
      </div>
      <div v-if="activeTab !== 'overview'" class="plan-filter-area">
        <div class="filter-scope-label">方案查看条件 <span>仅作用于“培养方案详情”和“学业进度监控”</span></div>
        <div class="plan-filters">
        <el-select v-model="college" placeholder="学院" clearable filterable @change="resetCollege">
          <el-option v-for="x in colleges" :key="x" :label="x" :value="x" />
        </el-select>
        <el-select v-model="grade" placeholder="年级" clearable @change="resetGrade">
          <el-option v-for="x in grades" :key="x" :label="`${x}级`" :value="x" />
        </el-select>
        <el-select v-model="major" placeholder="专业" clearable filterable @change="resetMajor">
          <el-option v-for="x in majorNames" :key="x" :label="x" :value="x" />
        </el-select>
        <el-select v-model="selectedMajor" placeholder="培养方案" filterable style="width:260px" @change="loadPlan">
          <el-option v-for="x in availablePlans" :key="x.planId" :label="`${x.planName} · ${x.coverageLabel}`" :value="x.planId" />
        </el-select>
        </div>
      </div>
    </div>
    <BusinessPageContext
      source="培养方案、学籍、成绩、教学任务与课程替代数据"
      :loading="loading"
      :period="activeTab === 'overview' ? '当前授权范围总览' : selectedPlanPeriod"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane label="培养质量管理总览" name="overview">
        <el-alert type="success" :closable="false" show-icon title="当前是全校管理总览" description="以下卡片和表格按当前账号的全部授权学生计算，不受培养方案查看条件影响。" style="margin-bottom:10px" />
        <el-alert type="info" :closable="false" show-icon :title="overview.definition.boundary" style="margin-bottom:14px" />
        <div class="sa-kpi-row">
          <KpiCard label="有效培养方案" :value="`${overview.summary.activePlans || 0}个`" hint="当前V2已接入并可查询的培养方案数" tone="primary" />
          <KpiCard label="结构完整方案" :value="`${overview.summary.completeStructurePlans || 0}个`" :hint="overview.definition.completeStructurePlans" tone="teal" />
          <KpiCard label="未绑定已接入方案" :value="`${overview.summary.studentsWithoutPlan || 0}人`" hint="当前学籍未匹配到本次已接入方案的去重学生数，包含方案源数据尚未覆盖的年级，不直接视为异常" tone="amber" />
          <KpiCard label="明确需处理学生" :value="`${overview.summary.actionRequiredStudents || 0}人`" :hint="overview.definition.actionRequiredStudents" tone="danger" />
          <KpiCard label="到期待核验学生" :value="`${overview.summary.verificationStudents || 0}人`" :hint="overview.definition.verificationStudents" tone="amber" />
          <KpiCard label="无开课证据课程" :value="`${overview.summary.coursesWithoutOfferingEvidence || 0}门`" :hint="overview.definition.coursesWithoutOfferingEvidence" tone="amber" />
          <KpiCard label="单一教师覆盖课程" :value="`${overview.summary.singleTeacherCourses || 0}门`" :hint="overview.definition.singleTeacherCourses" tone="amber" />
        </div>
        <div class="sa-card" style="margin-top:16px">
          <div class="sa-card-title">学院方案执行关注 <span class="extra">按明确需处理、到期待核验、无方案学生依次排序</span></div>
          <el-table :data="overview.colleges" size="small" stripe>
            <el-table-column prop="collegeName" label="学院" min-width="180" />
            <el-table-column prop="students" label="覆盖学生" width="100" align="right" />
            <el-table-column label="明确需处理" width="110" align="right"><template #default="{row}"><el-button link type="danger" :disabled="!row.actionRequired" @click="openStudents({college_name:row.collegeName,status:'明确需处理'},`${row.collegeName}｜明确需处理`)">{{row.actionRequired}}</el-button></template></el-table-column>
            <el-table-column label="到期待核验" width="110" align="right"><template #default="{row}"><el-button link type="warning" :disabled="!row.verification" @click="openStudents({college_name:row.collegeName,status:'到期待核验'},`${row.collegeName}｜到期待核验`)">{{row.verification}}</el-button></template></el-table-column>
            <el-table-column label="未绑定已接入方案" width="150" align="right"><template #default="{row}"><el-button link type="warning" :disabled="!row.withoutPlan" @click="openStudents({college_name:row.collegeName,status:'未绑定已接入方案'},`${row.collegeName}｜未绑定方案`)">{{row.withoutPlan}}</el-button></template></el-table-column>
            <el-table-column label="操作" width="85"><template #default="{row}"><el-button link type="primary" @click="openStudents({college_name:row.collegeName},`${row.collegeName}｜全部`)">全部学生</el-button></template></el-table-column>
          </el-table>
        </div>
        <el-row :gutter="16" style="margin-top:16px">
          <el-col :span="13"><div class="sa-card">
            <div class="sa-card-title">专业执行关注 <span class="extra">用于定位学院内部重点专业</span></div>
            <el-table :data="overview.majors" size="small" stripe max-height="420">
              <el-table-column prop="collegeName" label="学院" min-width="150" />
              <el-table-column prop="majorName" label="专业" min-width="150" />
              <el-table-column prop="students" label="学生" width="70" align="right" />
              <el-table-column prop="actionRequired" label="明确需处理" width="100" align="right" />
              <el-table-column prop="verification" label="待核验" width="80" align="right" />
              <el-table-column label="操作" width="115"><template #default="{row}"><el-button link type="primary" @click="openMajor(row)">画像</el-button><el-button link @click="openStudents({major_code:row.majorCode},row.majorName)">学生</el-button></template></el-table-column>
            </el-table>
          </div></el-col>
          <el-col :span="11"><div class="sa-card">
            <div class="sa-card-title">必修课程瓶颈 <span class="extra">按影响学生数排序</span></div>
            <el-table :data="overview.bottleneckCourses" size="small" stripe max-height="420">
              <el-table-column prop="courseName" label="课程" min-width="170" />
              <el-table-column prop="actionRequiredStudents" label="明确未通过学生" width="110" align="right" />
              <el-table-column prop="verificationStudents" label="待核验学生" width="95" align="right" />
              <el-table-column prop="affectedMajors" label="涉及专业" width="80" align="right" />
              <el-table-column label="操作" width="70"><template #default="{row}"><el-button link type="primary" @click="openStudents({course_id:row.courseId},row.courseName)">学生</el-button></template></el-table-column>
            </el-table>
          </div></el-col>
        </el-row>
      </el-tab-pane>
      <!-- Tab 1: 培养方案详情 -->
      <el-tab-pane label="培养方案详情" name="plan">
        <template v-if="hasPlan">
          <el-alert type="info" :closable="false" style="margin-bottom:14px"
            :title="`${plan.dataSource || '培养方案'}：${plan.coverageNote || '按专业与年级匹配适用方案'}`" />
          <div class="sa-kpi-row">
            <KpiCard v-for="k in planKpis" :key="k.label" :label="k.label" :value="k.value" :hint="k.formula" :tone="k.tone" />
          </div>

          <el-row :gutter="16" style="margin-bottom:16px">
            <el-col :span="10">
              <div class="sa-card">
                <div class="sa-card-title">学分结构 <KpiLabel label="" formula="各课程模块学分占总学分比例" /></div>
                <EChart v-if="creditDist.length" :option="creditOption" :height="240" />
                <div v-else class="sa-faint" style="font-size:12px">暂无数据</div>
              </div>
            </el-col>
            <el-col :span="14">
              <div class="sa-card">
                <div class="sa-card-title">各模块学分与课程数 <span class="extra">★ 为核心课程</span></div>
                <el-table :data="moduleSummary" size="small">
                  <el-table-column prop="name" label="模块" min-width="160" />
                  <el-table-column v-if="false" label="性质" width="80"><template #default="{row}">
                    <el-tag :type="row.required?'danger':'warning'" size="small">{{ row.required?'必修':'选修' }}</el-tag>
                  </template></el-table-column>
                  <el-table-column prop="credits" label="记录学分" width="90" align="right"><template #default="{row}"><b class="tnum">{{ row.credits }}</b></template></el-table-column>
                  <el-table-column prop="courseCount" label="课程数" width="70" align="right"><template #default="{row}"><span class="tnum">{{ row.courseCount }}</span></template></el-table-column>
                  <el-table-column prop="coreCount" label="核心" width="60" align="right"><template #default="{row}"><span class="tnum" :style="{color:row.coreCount?'#0D9488':'#94A3B8'}">{{ row.coreCount || '—' }}</span></template></el-table-column>
                </el-table>
              </div>
            </el-col>
          </el-row>

          <div class="sa-card" style="margin-bottom:16px">
            <div class="sa-card-title">模块最低学分要求 <span class="extra">来源：Word计划课程表中的“要求学分”汇总行</span></div>
            <el-alert v-if="!plan.moduleRequirements.length" type="warning" :closable="false" show-icon
              title="当前方案没有可展示的Word模块学分规则" description="该方案可能只有结构化课程表、未匹配到Word方案原文，或原表的要求学分为空。" />
            <el-table v-else :data="plan.moduleRequirements" size="small" max-height="360">
              <el-table-column prop="parentModule" label="一级模块" min-width="170" />
              <el-table-column prop="moduleName" label="子模块/课程组" min-width="170" />
              <el-table-column prop="requirementType" label="性质" width="80"><template #default="{row}">{{ row.requirementType || '—' }}</template></el-table-column>
              <el-table-column prop="minimumCredits" label="要求学分" width="90" align="right"><template #default="{row}"><b class="tnum">{{ row.minimumCredits }}</b></template></el-table-column>
              <el-table-column prop="rawHierarchy" label="原表层级证据" min-width="220" />
            </el-table>
          </div>

          <div class="sa-card module-course-card" style="margin-bottom:16px" v-if="plan.modules.length">
            <div class="sa-card-title">课程模块与课程明细 <span class="extra">默认显示汇总，点击模块后展开课程</span></div>
            <el-collapse class="module-collapse">
              <el-collapse-item v-for="(mod, mi) in plan.modules" :key="mi" :name="String(mi)">
                <template #title>
                  <div class="module-collapse-title">
                    <b>{{ mod.name }}</b>
                    <span>{{ moduleCourseCount(mod) }}门 · 记录学分 {{ mod.credits }}</span>
                  </div>
                </template>
                <div v-for="sm in mod.subModules" :key="sm.name" class="module-course-table">
                  <div v-if="mod.subModules.length > 1" class="submodule-name">{{ sm.name }}</div>
                  <el-table :data="sm.courses" size="small" max-height="420">
                    <el-table-column prop="code" label="课程代码" width="130" />
                    <el-table-column prop="name" label="课程名称" min-width="200">
                      <template #default="{row}"><span :style="{fontWeight:row.name.includes('★')?'700':'400'}">{{ row.name }}</span></template>
                    </el-table-column>
                    <el-table-column prop="credits" label="学分" width="64" align="right"><template #default="{row}"><span class="tnum">{{ row.credits }}</span></template></el-table-column>
                    <el-table-column prop="hours" label="学时" width="64" align="right"><template #default="{row}"><span class="tnum">{{ row.hours }}</span></template></el-table-column>
                    <el-table-column prop="term" label="学期" width="64" align="center"><template #default="{row}"><el-tag size="small" :type="row.term<=4?'success':row.term<=6?'warning':'info'">{{ row.term||'-' }}</el-tag></template></el-table-column>
                    <el-table-column prop="dept" label="开课院系" width="150" />
                  </el-table>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <div class="sa-card plan-text-card" style="margin-bottom:16px" v-if="plan.graduationRequirements.length">
            <div class="sa-card-title">毕业要求说明 <span class="extra">方案文本，不作为学生达成度结论</span></div>
            <el-alert type="info" :closable="false" show-icon title="当前仅展示培养方案原文"
              description="待学校提供‘毕业要求指标点—支撑课程—评价环节—实际结果’结构化数据后，才能计算达成度。当前不用课程平均分或通过率替代。" />
            <el-collapse class="requirement-collapse">
              <el-collapse-item :title="`查看方案原文（${plan.graduationRequirements.length}条）`" name="requirements">
                <div v-for="(r,i) in plan.graduationRequirements" :key="i" class="grad-row">
                  <el-tag size="small" type="info">{{ i+1 }}</el-tag><span>{{ r }}</span>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div class="sa-card" v-if="plan.degreeRequirement">
            <div class="sa-card-title">学位授予条件</div>
            <p style="font-size:13px;color:#475569;line-height:1.7">{{ plan.degreeRequirement }}</p>
          </div>
        </template>
        <el-empty v-else description="" :image-size="100">
          <template #description>
            <div style="font-size:13px;color:#64748B">暂无该专业培养方案数据</div>
            <div style="font-size:11px;color:#94A3B8;margin-top:4px">可切换方案查看其课程表与原文覆盖状态</div>
          </template>
        </el-empty>
      </el-tab-pane>

      <!-- Tab 4: 学业进度监控 -->
      <el-tab-pane label="学业进度监控" name="progress">
        <ProgressView v-if="activeTab === 'progress'" :major-id="selectedMajor" />
      </el-tab-pane>
      <el-tab-pane label="毕业准备核查" name="graduation-readiness">
        <div v-if="activeTab === 'graduation-readiness'" class="embedded-topic"><GraduationReadiness /></div>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="studentDialog.visible" :title="`${studentDialog.title}｜方案执行学生名单`" width="980px">
      <el-alert type="info" :closable="false" :title="studentDialog.definition" style="margin-bottom:12px" />
      <el-table :data="studentDialog.items" size="small" stripe max-height="520" v-loading="studentDialog.loading">
        <el-table-column prop="studentId" label="学号" width="130" /><el-table-column prop="name" label="姓名" width="90" />
        <el-table-column prop="grade" label="年级" width="70" /><el-table-column prop="collegeName" label="学院" min-width="150" />
        <el-table-column prop="majorName" label="专业" min-width="140" />
        <el-table-column prop="failedRequired" label="明确未通过必修" width="120" align="right" />
        <el-table-column prop="verificationRequired" label="到期待核验" width="100" align="right" />
        <el-table-column label="状态" width="110"><template #default="{row}"><el-tag size="small" :type="row.evidenceStatus==='明确需处理'?'danger':row.evidenceStatus==='到期待核验'?'warning':'success'">{{row.evidenceStatus}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="studentProfile(row)">执行详情</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-drawer v-model="studentEvidence.visible" :title="`${studentEvidence.data.student?.display_name || ''}｜培养方案执行详情`" size="760px" append-to-body>
      <div v-loading="studentEvidence.loading">
        <el-alert type="warning" :closable="false" show-icon title="这是方案执行核查，不是学生综合档案" :description="studentEvidence.data.boundary" />
        <el-descriptions class="student-evidence-summary" :column="2" border>
          <el-descriptions-item label="学号">{{ studentEvidence.data.student?.student_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="年级">{{ studentEvidence.data.student?.entry_grade || '—' }}</el-descriptions-item>
          <el-descriptions-item label="专业">{{ studentEvidence.data.student?.major_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="培养方案">{{ studentEvidence.data.student?.plan_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="明确未通过">{{ studentEvidence.data.summary?.failed_courses || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="到期缺结果候选">{{ studentEvidence.data.summary?.candidate_courses || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="无历史开课证据">{{ studentEvidence.data.summary?.courses_without_offering || 0 }} 门</el-descriptions-item>
          <el-descriptions-item label="有课程替代证据">{{ studentEvidence.data.summary?.courses_with_substitution || 0 }} 门</el-descriptions-item>
        </el-descriptions>
        <h4 class="evidence-title">明确未通过必修课程 <small>可直接进入重修与课程保障核查</small></h4>
        <el-table :data="studentEvidence.data.failed_courses || []" size="small" empty-text="当前没有明确未通过必修课程">
          <el-table-column prop="course_name" label="课程" min-width="150" /><el-table-column prop="effective_score" label="成绩" width="65" />
          <el-table-column prop="lesson_count" label="历史教学班" width="95" /><el-table-column prop="substitution_count" label="替代证据" width="85" />
          <el-table-column prop="reason" label="核查原因与动作" min-width="260" />
        </el-table>
        <h4 class="evidence-title">到期缺结果记录候选 <small>必须先核验选课、免修与认定数据</small></h4>
        <el-table :data="studentEvidence.data.candidate_courses || []" size="small" max-height="280" empty-text="当前没有到期缺结果候选">
          <el-table-column prop="course_name" label="课程" min-width="150" /><el-table-column prop="suggested_term" label="建议学期" width="80" />
          <el-table-column prop="lesson_count" label="历史教学班" width="95" /><el-table-column prop="reason" label="核查原因与动作" min-width="280" />
        </el-table>
      </div>
    </el-drawer>
    <el-dialog v-model="majorDialog.visible" :title="`${majorDialog.data.majorName || ''}｜专业方案执行画像`" width="1080px">
      <el-alert type="info" :closable="false" :title="majorDialog.data.boundary" style="margin-bottom:12px" />
      <div class="sa-kpi-row">
        <KpiCard label="覆盖学生" :value="`${majorDialog.data.summary?.students || 0}人`" hint="当前专业纳入V2范围的去重学生" tone="primary" />
        <KpiCard label="适用方案版本" :value="`${majorDialog.data.summary?.plans || 0}个`" hint="当前学生实际绑定的培养方案版本数" tone="primary" />
        <KpiCard label="明确需处理" :value="`${majorDialog.data.summary?.actionRequiredStudents || 0}人`" hint="存在明确未通过必修课的学生" tone="danger" />
        <KpiCard label="课程瓶颈" :value="`${majorDialog.data.summary?.bottleneckCourses || 0}门`" hint="影响学生方案推进、需要进一步核查的课程" tone="amber" />
        <KpiCard label="无开课证据" :value="`${majorDialog.data.summary?.coursesWithoutOffering || 0}门`" hint="瓶颈课程中当前教学任务未发现开课记录的课程" tone="amber" />
        <KpiCard label="单一教师覆盖" :value="`${majorDialog.data.summary?.singleTeacherCourses || 0}门`" hint="瓶颈课程中当前仅关联一名教师的课程" tone="amber" />
      </div>
      <el-row :gutter="16" style="margin-top:14px"><el-col :span="10"><div class="sa-card"><div class="sa-card-title">适用方案版本</div>
        <el-table :data="majorDialog.data.plans" size="small"><el-table-column prop="planName" label="方案" min-width="180"/><el-table-column prop="courseCount" label="课程" width="65"/><el-table-column prop="moduleRuleCount" label="规则" width="65"/></el-table>
      </div></el-col><el-col :span="14"><div class="sa-card"><div class="sa-card-title">重点课程</div>
        <el-table :data="majorDialog.data.courses" size="small" max-height="360"><el-table-column prop="courseName" label="课程" min-width="150"/><el-table-column prop="actionRequiredStudents" label="未通过学生" width="90"/><el-table-column prop="lessonCount" label="教学班" width="70"/><el-table-column prop="teacherCount" label="教师" width="60"/><el-table-column label="操作" width="75"><template #default="{row}"><el-button link type="primary" @click="openSupply(row)">供给证据</el-button></template></el-table-column></el-table>
      </div></el-col></el-row>
    </el-dialog>
    <el-dialog v-model="supplyDialog.visible" :title="`${supplyDialog.data.course?.courseName || ''}｜课程供给保障证据`" width="900px">
      <el-alert type="warning" :closable="false" :title="supplyDialog.data.boundary" style="margin-bottom:12px" />
      <div class="sa-kpi-row"><KpiCard label="明确未通过学生" :value="`${supplyDialog.data.affected?.actionRequiredStudents || 0}人`" hint="该必修课程存在明确未通过记录的学生" tone="danger"/><KpiCard label="涉及专业" :value="`${supplyDialog.data.affected?.affectedMajors || 0}个`" hint="方案课程状态涉及的去重专业数" tone="primary"/><KpiCard label="已接入开课学期" :value="`${supplyDialog.data.offerings?.length || 0}个`" hint="当前真实教学任务中发现开课记录的学期数" tone="teal"/></div>
      <div class="sa-card" style="margin-top:12px"><div class="sa-card-title">已接入开课记录</div><el-empty v-if="!supplyDialog.data.offerings?.length" description="当前教学任务未发现开课证据" :image-size="70"/><el-table v-else :data="supplyDialog.data.offerings" size="small"><el-table-column prop="semesterId" label="学期"/><el-table-column prop="lessonCount" label="教学班"/><el-table-column prop="teacherCount" label="教师"/><el-table-column prop="enrolled" label="选课人次"/><el-table-column prop="avgClassSize" label="平均班额"/></el-table></div>
      <div class="sa-card" style="margin-top:12px"><div class="sa-card-title">课程替代证据</div><el-empty v-if="!supplyDialog.data.substitutions?.length" description="当前未发现课程替代记录" :image-size="70"/><el-table v-else :data="supplyDialog.data.substitutions" size="small"><el-table-column prop="originalCourseName" label="原课程"/><el-table-column prop="substituteCourseName" label="替代课程"/><el-table-column prop="studentCount" label="涉及学生"/></el-table></div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { http } from '@/utils/http'
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import KpiLabel from '@/components/KpiLabel.vue'
import KpiCard from '@/components/KpiCard.vue'
import EChart from '@/components/EChart.vue'
import BusinessPageContext from '@/components/BusinessPageContext.vue'
import ProgressView from './Progress.vue'
import GraduationReadiness from '../reports/GraduationReadiness.vue'
import { useBusinessPageTitle } from '@/utils/businessPage'

const route = useRoute()
const router = useRouter()
const pageTitle = useBusinessPageTitle('/admin/curriculum', '培养质量分析')
const allPlans = ref<any[]>([])
const college = ref('')
const grade = ref<number | ''>('')
const major = ref('')
const selectedMajor = ref('')
const curriculumTabs = new Set(['overview','plan','progress','graduation-readiness'])
const activeTab = ref(curriculumTabs.has(String(route.query.tab)) ? String(route.query.tab) : 'overview')
const selectedPlanPeriod = computed(() => {
  const plan = allPlans.value.find((item:any) => item.planId === selectedMajor.value)
  return plan ? `当前方案：${plan.planName}` : '尚未选择培养方案'
})
watch(activeTab, tab => {
  const query = { ...route.query }
  if (tab === 'overview') delete query.tab
  else query.tab = tab
  router.replace({ path:'/admin/curriculum', query })
})
const loading = ref(false)
const overview = reactive<any>({ summary:{}, colleges:[], majors:[], bottleneckCourses:[], definition:{ boundary:'' } })
const studentDialog = reactive<any>({visible:false,loading:false,title:'',items:[],definition:''})
const studentEvidence = reactive<any>({visible:false,loading:false,data:{student:{},summary:{},failed_courses:[],candidate_courses:[],boundary:''}})
const majorDialog = reactive<any>({visible:false,loading:false,data:{summary:{},plans:[],courses:[]}})
const supplyDialog = reactive<any>({visible:false,loading:false,data:{course:{},affected:{},offerings:[],substitutions:[],boundary:''}})
async function openMajor(row:any) {
  majorDialog.visible=true; majorDialog.loading=true
  try { majorDialog.data=await http.get('/v2/curriculum/management-major/'+row.majorCode) }
  finally { majorDialog.loading=false }
}
async function openSupply(row:any) {
  supplyDialog.visible=true; supplyDialog.loading=true
  try { supplyDialog.data=await http.get('/v2/curriculum/course-supply/'+row.courseId) }
  finally { supplyDialog.loading=false }
}

async function openStudents(params:Record<string,string>, title:string) {
  studentDialog.visible=true; studentDialog.loading=true; studentDialog.title=title
  try {
    const query=new URLSearchParams(params)
    const data=await http.get('/v2/curriculum/management-students?'+query.toString())
    Object.assign(studentDialog,{items:data.items||[],definition:data.definition||''})
  } finally { studentDialog.loading=false }
}
async function studentProfile(row:any) {
  studentEvidence.visible=true; studentEvidence.loading=true
  studentEvidence.data={student:{display_name:row.name,student_id:row.studentId},summary:{},failed_courses:[],candidate_courses:[],boundary:''}
  try { studentEvidence.data=await http.get('/v2/topics/graduation-readiness/student/'+encodeURIComponent(row.studentId)) }
  finally { studentEvidence.loading=false }
}

const colleges = computed(() => [...new Set(allPlans.value.map(x => x.collegeName))].sort())
const collegePlans = computed(() => allPlans.value.filter(x => !college.value || x.collegeName === college.value))
const grades = computed(() => [...new Set<number>(collegePlans.value.map(x => x.grade))].sort((a,b) => b-a))
const gradePlans = computed(() => collegePlans.value.filter(x => grade.value === '' || x.grade === grade.value))
const majorNames = computed(() => [...new Set<string>(gradePlans.value.map(x => x.majorName))].sort())
const availablePlans = computed(() => gradePlans.value.filter(x => !major.value || x.majorName === major.value))

function pickFirst() { selectedMajor.value = availablePlans.value[0]?.planId || ''; loadPlan() }
function resetCollege() { grade.value=''; major.value=''; pickFirst() }
function resetGrade() { major.value=''; pickFirst() }
function resetMajor() { pickFirst() }

const plan = reactive<any>({
  name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
  electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
  planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
  courseCount: 0, moduleCount: 0, graduationMinimumCredits: null, creditNote: '',
  requiredMinimumCredits:null, electiveMinimumCredits:null, practiceMinimumCredits:null,
  moduleRequirements: [],
})
const hasPlan = ref(true)

function resetPlan() {
  Object.assign(plan, {
    name: '', grade: '', college: '', totalCredits: 0, requiredCredits: 0,
    electiveMinCredits: 0, practiceCredits: 0, modules: [], graduationRequirements: [], degreeRequirement: '',
    planVersion: '', applicableGrade: '', dataSource: '', coverageNote: '',
    courseCount: 0, moduleCount: 0, graduationMinimumCredits: null, creditNote: '',
    requiredMinimumCredits:null, electiveMinimumCredits:null, practiceMinimumCredits:null,
    moduleRequirements: [],
  })
}

const planKpis = computed(() => [
  { label: '方案课程记录', value: `${plan.courseCount}门`, formula: '结构化方案课程表中的课程行数', tone: 'primary' as const },
  { label: '课程记录学分合计', value: plan.totalCredits, formula: plan.creditNote, tone: 'teal' as const },
  { label: '课程模块', value: `${plan.moduleCount}个`, formula: '按方案课程表中的课程模块字段去重', tone: 'primary' as const },
  { label: '毕业最低学分', value: plan.graduationMinimumCredits ?? '待核验', formula: '只采用方案原文明示的毕业最低要求；未结构化时不推算', tone: 'amber' as const },
  { label: '必修课学分', value: plan.requiredMinimumCredits ?? '待核验', formula: '培养方案修读要求原文明示的必修课学分', tone: 'teal' as const },
  { label: '选修课学分', value: plan.electiveMinimumCredits ?? '待核验', formula: '培养方案修读要求原文明示的选修课最低学分', tone: 'amber' as const },
  { label: '集中实践环节', value: plan.practiceMinimumCredits ?? '待核验', formula: '培养方案修读要求原文明示的集中实践教学环节学分；未可靠识别时不倒推', tone: 'primary' as const },
  { label: '模块学分规则', value: `${plan.moduleRequirements.length}条`, formula: 'Word计划课程表中带明确数字的“要求学分”汇总行', tone: 'teal' as const },
])

const moduleSummary = computed(() => (plan.modules || []).map((m: any) => {
  const courses = (m.subModules || []).flatMap((sm: any) => sm.courses || [])
  return {
    name: m.name, required: m.required, credits: m.credits,
    courseCount: courses.length,
    coreCount: courses.filter((c: any) => String(c.name).includes('★')).length,
  }
}))
function moduleCourseCount(mod:any) { return (mod.subModules || []).reduce((sum:number, sm:any) => sum + (sm.courses || []).length, 0) }

const MOD_COLORS = ['#4F46E5', '#0D9488', '#D97706', '#6366F1', '#0EA5E9', '#94A3B8', '#A855F7', '#E11D48']
const creditDist = computed(() => (plan.modules || []).filter((m: any) => (m.credits || 0) > 0))
const creditOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c} 学分（{d}%）' },
  legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#64748B', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['46%', '72%'], center: ['32%', '50%'], avoidLabelOverlap: true,
    itemStyle: { borderColor: '#fff', borderWidth: 2 }, label: { show: false },
    data: creditDist.value.map((m: any, i: number) => ({ name: m.name, value: m.credits, itemStyle: { color: MOD_COLORS[i % MOD_COLORS.length] } })),
  }],
}))

async function loadPlan() {
  if (!selectedMajor.value) { hasPlan.value = false; resetPlan(); return }
  loading.value = true
  try {
    const d = await http.get('/v2/curriculum/plans/' + selectedMajor.value)
    if (d?.plan) {
      Object.assign(plan, {
        name: d.plan.planName, grade: `${d.plan.grade}级`, college: college.value,
        totalCredits: d.creditEvidence?.recordedCourseCredits ?? 0, requiredCredits: '待核验',
        electiveMinCredits: '待核验', practiceCredits: '待核验',
        courseCount: d.courses?.length || 0, moduleCount: d.modules?.length || 0,
        graduationMinimumCredits: d.creditEvidence?.graduationMinimumCredits,
        requiredMinimumCredits: d.creditEvidence?.requiredMinimumCredits,
        electiveMinimumCredits: d.creditEvidence?.electiveMinimumCredits,
        practiceMinimumCredits: d.creditEvidence?.practiceMinimumCredits,
        moduleRequirements: d.moduleRequirements || [],
        creditNote: d.creditEvidence?.note || '',
        modules: (d.modules || []).map((m:any) => ({ name:m.name, credits:m.recordedCredits,
          required:false, subModules:[{name:m.name,courses:(m.courses || []).map((c:any) => ({
            code:c.courseId,name:c.courseName,credits:c.credits,hours:'—',term:c.suggestedTerm,dept:'—'
          }))}] })),
        graduationRequirements: d.requirements.map((x:any) => x.text),
        degreeRequirement: d.creditEvidence?.degreeRequirement || '',
        planVersion: d.plan.version || d.plan.planId,
        dataSource: d.creditEvidence?.sourceFile ? `真实培养方案原文（${d.creditEvidence.sourceFile}）` : '结构化方案课程表',
        coverageNote: `${d.coverage?.label || '覆盖状态待确认'}；${d.evidence.boundaryNote}`,
      })
      hasPlan.value = true
    }
    else { hasPlan.value = false; resetPlan() }
  } catch {
    hasPlan.value = false; resetPlan()
  } finally { loading.value = false }
}

onMounted(async () => {
  loading.value = true
  try {
    const d = await http.get('/v2/curriculum/options')
    allPlans.value = d.plans || []
    Object.assign(overview, await http.get('/v2/curriculum/management-overview'))
    const first = allPlans.value.find(x => x.requirementCount > 0) || allPlans.value[0]
    if (first) {
      college.value=first.collegeName; grade.value=first.grade; major.value=first.majorName
      selectedMajor.value=first.planId; await loadPlan()
    }
  } catch { hasPlan.value=false; resetPlan() }
  finally { loading.value=false }
})
</script>

<style scoped>
.sa-head-row { display:block; margin-bottom:14px; }
.plan-filter-area { width:100%; margin-top:12px; padding:10px 12px; border:1px solid #dbeafe; border-radius:9px; background:#f8fbff; }
.filter-scope-label { margin-bottom:8px; color:#334155; font-size:12px; font-weight:600; }
.filter-scope-label span { margin-left:8px; color:#64748b; font-weight:400; }
.plan-filters { display:flex; gap:8px; flex-wrap:nowrap; align-items:center; width:100%; }
.plan-filters .el-select { width:180px; flex:0 0 180px; }
.plan-filters .el-select:last-child { width:300px !important; flex:1 1 300px; }
@media (max-width:900px) { .plan-filters { overflow-x:auto; padding-bottom:4px; } }
.grad-row { padding: 8px 0; border-bottom: 1px solid var(--sa-border); font-size: 13px; display: flex; gap: 8px; align-items: flex-start; color: #334155; }
.grad-row:last-child { border-bottom: none; }
.plan-text-card :deep(.el-alert) { margin-bottom: 8px; }
.requirement-collapse { border-top:0; }
.requirement-collapse :deep(.el-collapse-item__header) { color:#475569; font-size:13px; }
.student-evidence-summary { margin:14px 0 18px; }
.embedded-topic :deep(.crumb),
.embedded-topic :deep(.sa-page-title),
.embedded-topic :deep(.sa-page-sub),
.embedded-topic :deep(.el-breadcrumb) { display:none; }
.evidence-title { margin:20px 0 10px; color:#1e293b; }
.evidence-title small { margin-left:8px; color:#64748b; font-weight:400; }
.module-collapse { border-top:0; }
.module-collapse-title { display:flex; justify-content:space-between; align-items:center; width:100%; padding-right:14px; }
.module-collapse-title b { color:#334155; font-size:13px; }
.module-collapse-title span { color:#64748b; font-size:12px; font-variant-numeric:tabular-nums; }
.module-course-table + .module-course-table { margin-top:12px; }
.submodule-name { margin:0 0 6px; color:#475569; font-size:12px; font-weight:600; }
</style>
