<template>
  <div>
    <el-breadcrumb separator="/" class="crumb"><el-breadcrumb-item to="/admin/faculty">本科教学师资保障分析</el-breadcrumb-item><el-breadcrumb-item>课程团队核查</el-breadcrumb-item></el-breadcrumb>
    <div class="head"><div><h2 class="sa-page-title">课程团队保障核查</h2><p class="sa-page-sub">核查课程的实际授课成员、教学规模、职称证据和接续保障，不评价教师个人能力。</p></div></div>
    <div class="search sa-card"><el-input v-model="query" clearable placeholder="输入课程名称或代码" @keyup.enter="search"/><el-button type="primary" :loading="searching" @click="search">查询课程</el-button></div>
    <div v-if="results.length" class="results"><el-tag v-for="c in results" :key="c.id" effect="plain" @click="select(c)">{{c.name}}（{{c.code}}）</el-tag></div>

    <template v-if="course">
      <div class="scope"><span>当前课程：<b>{{course.name}}</b>（{{course.code}}）</span><el-button link type="primary" @click="clear">重新选择</el-button></div>
      <el-alert type="warning" :closable="false" show-icon title="证据边界" :description="boundary"/>
      <div class="kpis"><div v-for="x in kpis" :key="x.label" class="kpi"><span>{{x.label}}</span><b>{{x.value}}</b><small>{{x.note}}</small></div></div>

      <div class="grid"><section class="sa-card"><div class="sa-card-title">实际授课团队成员 <span class="extra">来源：教学任务教师关联</span></div><el-table :data="team.members||[]" stripe size="small"><el-table-column prop="display_name" label="教师" min-width="110"/><el-table-column prop="staff_id" label="教师代码" width="120"/><el-table-column prop="title" label="职称" width="120"><template #default="{row}">{{row.title||'待补充'}}</template></el-table-column><el-table-column prop="organization_id" label="组织代码" width="120"/><el-table-column label="证据状态" width="105"><template #default="{row}"><el-tag :type="row.title?'success':'warning'">{{row.title?'职称已知':'职称缺失'}}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="teacher(row)">教学档案</el-button></template></el-table-column></el-table></section>
      <section class="sa-card"><div class="sa-card-title">历史开课供给证据</div><el-table :data="supply.offerings||[]" size="small"><el-table-column prop="semesterId" label="学期" width="115"/><el-table-column prop="lessonCount" label="教学班" width="75"/><el-table-column prop="teacherCount" label="教师" width="70"/><el-table-column prop="capacity" label="容量" width="75"/><el-table-column prop="enrolled" label="选课人次" width="85"/><el-table-column prop="avgClassSize" label="平均班额" width="85"/></el-table></section></div>

      <section class="sa-card"><div class="sa-card-title">管理核查结论</div><el-table :data="checks" stripe><el-table-column prop="level" label="级别" width="85"><template #default="{row}"><el-tag :type="row.level==='优先'?'danger':row.level==='核验'?'warning':'info'">{{row.level}}</el-tag></template></el-table-column><el-table-column prop="topic" label="核查事项" width="160"/><el-table-column prop="basis" label="事实依据" min-width="250"/><el-table-column prop="action" label="建议管理动作" min-width="300"/></el-table></section>

      <section class="sa-card explain"><div class="sa-card-title">如何理解本页</div><p><b>团队人数：</b>当前真实教学任务中与该课程关联的去重教师，不等于学校所有具备授课资格的教师。</p><p><b>单点承担：</b>当前仅发现1名实际授课教师，应核查下一轮开课的备课和接续安排，但不等于已发生人才断层。</p><p><b>职称结构：</b>只对职称已知成员进行描述；存在缺失时不得形成完整梯队结论。</p><p><b>历史开课：</b>证明已接入学期曾经开设，不承诺未来继续开设。</p></section>
    </template>
    <el-empty v-else description="请选择一门课程开始团队核查"/>
  </div>
</template>

<script setup lang="ts">
import{computed,onMounted,reactive,ref}from'vue';import{useRoute,useRouter}from'vue-router';import{http}from'@/utils/http';import{getV2TeachingSemester}from'@/utils/v2meta'
const route=useRoute(),router=useRouter(),query=ref(''),searching=ref(false),results=ref<any[]>([]),course=ref<any>(),semester=ref(''),team=reactive<any>({summary:null,members:[]}),supply=reactive<any>({offerings:[],availability:{}})
const boundary=computed(()=>`${team.summary?.semester_id||semester.value}学期的成员来自实际教学任务。当前缺少完整年龄、学历、课程资格和未来开课计划，因此不判断年龄断层、个人能力或未来必然缺师。${supply.boundary||''}`)
const kpis=computed(()=>{const s=team.summary||{};return[{label:'实际授课教师',value:(s.teacher_count||0)+' 人',note:'当前教学任务去重教师'},{label:'职称已知',value:Math.max(0,(s.teacher_count||0)-(s.unknown_title_count||0))+' 人',note:`缺失 ${s.unknown_title_count||0} 人`},{label:'教授/副教授',value:`${s.professor_count||0} / ${s.associate_professor_count||0} 人`,note:'仅统计职称已知成员'},{label:'历史开课学期',value:(supply.offerings?.length||0)+' 个',note:'当前已接入证据'},{label:'替代关系',value:(supply.substitutions?.length||0)+' 条',note:'不等于师资替代'}]})
const checks=computed(()=>{const s=team.summary||{},rows:any[]=[];if((s.teacher_count||0)===1)rows.push({level:'优先',topic:'课程单点承担',basis:'当前教学任务仅关联1名实际授课教师',action:'核查下一轮开课规模、协同备课教师和临时替课安排。'});else if((s.teacher_count||0)===2)rows.push({level:'核验',topic:'团队覆盖偏窄',basis:'当前教学任务关联2名教师',action:'结合教学班数量和未来开课计划核查团队冗余度。'});else rows.push({level:'观察',topic:'团队覆盖',basis:`当前关联${s.teacher_count||0}名实际授课教师`,action:'保持常规观察，结合后续学期确认团队稳定性。'});if(s.unknown_title_count)rows.push({level:'核验',topic:'职称证据缺失',basis:`${s.unknown_title_count}名成员缺少职称`,action:'先补齐教师主数据，再判断职称梯队结构。'});if(!supply.availability?.hasFuturePlanEvidence)rows.push({level:'核验',topic:'未来开课保障',basis:'当前未接入未来开课计划',action:'由排课人员结合下一学年教学任务确认课程是否开设及师资容量。'});return rows})
async function search(){if(!query.value.trim())return;searching.value=true;try{results.value=await http.get<any>('/admin/faculty/team/search?q='+encodeURIComponent(query.value))}finally{searching.value=false}}
async function select(c:any){course.value={name:c.name,code:c.code||c.id,id:c.id};results.value=[];query.value='';await load(c.id)}
async function load(id:string){const r=await http.get<any>(`/admin/faculty/management-course/${encodeURIComponent(id)}?semester=${encodeURIComponent(semester.value)}`);Object.assign(team,{summary:r.summary,members:r.members});Object.assign(supply,{offerings:r.offerings,substitutions:[],availability:{hasFuturePlanEvidence:false},boundary:r.boundary})}
function clear(){course.value=undefined;Object.assign(team,{summary:null,members:[]});Object.assign(supply,{offerings:[],availability:{}})}function teacher(row:any){router.push('/admin/faculty/'+row.staff_id)}
onMounted(async()=>{semester.value=await getV2TeachingSemester()||'2023-2024-1';const id=String(route.query.courseId||'');if(id)await select({id,code:id,name:String(route.query.courseName||id)})})
</script>

<style scoped>.crumb{margin-bottom:10px}.head{display:flex;justify-content:space-between}.search{display:flex;gap:10px;margin-bottom:10px}.search .el-input{max-width:420px}.results{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}.results .el-tag{cursor:pointer}.scope{display:flex;justify-content:space-between;padding:11px 14px;margin-bottom:12px;background:#eef2ff;border:1px solid #c7d2fe;border-radius:9px}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0}.kpi{padding:14px;background:#fff;border:1px solid var(--sa-border);border-radius:9px}.kpi span,.kpi small{display:block;color:#64748b}.kpi b{display:block;margin:6px 0;font-size:22px}.grid{display:grid;grid-template-columns:1.2fr 1fr;gap:14px}.sa-card{margin-bottom:14px}.explain p{font-size:13px;line-height:1.8;color:#475569}</style>
