import { defineConfig, loadEnv, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'
import viteCompression from 'vite-plugin-compression'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import ElementPlus from 'unplugin-element-plus/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import tailwindcss from '@tailwindcss/vite'

/** 内置Mock数据 — 参见详细需求设计文档的字段定义 */
function mockPlugin(): Plugin {
  const MOCKS: Record<string, any> = {
    '/api/admin/dashboard': { data: {
      kpi: [
        { label:'在籍学生数', value:'18,532', formula:'在籍本科生总数', trend:'同比+1.2%', up:true },
        { label:'本学期开课门数', value:'2,847', formula:'当前学期开设课程总数(去重)', trend:'同比+3.2%', up:true },
        { label:'专任教师数', value:'1,203', formula:'在职专任教师总数', trend:'同比+2.1%', up:true },
        { label:'应届毕业率', value:'96.8%', formula:'应届毕业÷应届总人数', trend:'+0.3%', up:true },
        { label:'学位授予率', value:'94.2%', formula:'获学位÷应届总人数', trend:'+0.5%', up:true },
        { label:'当前预警', value:'487人', formula:'处于预警状态的学生总数', trend:'同比-12%', up:false },
      ],
      colleges: [
        { id:'PE', name:'石油工程学院', students:2156, avgScore:78.2, failRate:'5.8%', alertRate:'2.1%', creditDone:82 },
        { id:'GE', name:'地球科学学院', students:1890, avgScore:75.1, failRate:'7.2%', alertRate:'2.8%', creditDone:79 },
        { id:'CE', name:'化学工程学院', students:1650, avgScore:73.5, failRate:'8.5%', alertRate:'3.2%', creditDone:76 },
        { id:'ME', name:'机械与储运工程学院', students:1820, avgScore:71.8, failRate:'9.8%', alertRate:'3.6%', creditDone:73 },
        { id:'GP', name:'地球物理与信息工程学院', students:2030, avgScore:74.3, failRate:'7.8%', alertRate:'2.9%', creditDone:78 },
        { id:'SC', name:'理学院', students:980, avgScore:72.1, failRate:'10.2%', alertRate:'4.1%', creditDone:71 },
        { id:'BA', name:'工商管理学院', students:2100, avgScore:76.8, failRate:'6.5%', alertRate:'2.3%', creditDone:81 },
        { id:'FL', name:'外国语学院', students:680, avgScore:79.5, failRate:'5.2%', alertRate:'1.8%', creditDone:84 },
        { id:'HS', name:'人文社会科学学院', students:750, avgScore:77.2, failRate:'6.1%', alertRate:'2.0%', creditDone:83 },
      ],
      gpaDist: [
        { range:'0-2.0', label:'0-2.0', percent:8, count:1482 },
        { range:'2.0-2.5', label:'2.0-2.5', percent:15, count:2780 },
        { range:'2.5-3.0', label:'2.5-3.0', percent:32, count:5930 },
        { range:'3.0-3.5', label:'3.0-3.5', percent:28, count:5189 },
        { range:'3.5-4.0', label:'3.5-4.0', percent:17, count:3151 },
      ],
      failCourses: [
        { id:'EE301',name:'通信原理',college:'信息学院',failCount:37,totalCount:328,failRate:'11.3',avgScore:73.2,excellentRate:'12.8'},
        { id:'MA202',name:'高等数学II',college:'理学院',failCount:164,totalCount:1520,failRate:'10.8',avgScore:71.5,excellentRate:'9.5'},
        { id:'PH202',name:'电磁场理论',college:'信息学院',failCount:32,totalCount:310,failRate:'10.2',avgScore:68.9,excellentRate:'8.1'},
        { id:'CH301',name:'有机化学',college:'化工学院',failCount:28,totalCount:285,failRate:'9.8',avgScore:70.2,excellentRate:'10.2'},
        { id:'CS201',name:'数据结构',college:'信息学院',failCount:41,totalCount:480,failRate:'8.5',avgScore:74.1,excellentRate:'14.5'},
        { id:'ME301',name:'机械原理',college:'机械学院',failCount:25,totalCount:302,failRate:'8.3',avgScore:72.8,excellentRate:'11.3'},
        { id:'EE304',name:'数字信号处理',college:'信息学院',failCount:30,totalCount:380,failRate:'7.9',avgScore:69.5,excellentRate:'7.8'},
        { id:'MA203',name:'线性代数',college:'理学院',failCount:96,totalCount:1350,failRate:'7.1',avgScore:75.8,excellentRate:'16.2'},
      ],
    }},
    '/api/admin/alerts': { data: {
      summary: { critical:128, warning:215, info:312, resolved:168, resolvedRate:'34.5%' },
      rules: [
        { id:1,name:'GPA持续下降',level:'严重',triggerType:'ai',params:'连续2学期GPA下降>0.3'},
        { id:2,name:'挂科累积',level:'严重',triggerType:'threshold',params:'挂科≥3门'},
        { id:3,name:'学分缺口',level:'警告',triggerType:'threshold',params:'缺口>10学分'},
        { id:4,name:'单科挂科',level:'提醒',triggerType:'threshold',params:'核心课挂科1门'},
      ],
      list: [
        { name:'张XX',sid:'2021012345',college:'地球科学学院',class:'通信211',level:'严重',type:'挂科累积',detail:'挂科5门·GPA2.05·学分缺口66',status:'未处理',time:'2025-06-03',gpaHistory:[3.1,2.8,2.5,2.4,2.3],alerts:[{level:'严重',type:'挂科累积',status:'已通知',detail:'挂科3门',time:'2023-09'},{level:'严重',type:'GPA异常',status:'已约谈',detail:'GPA<2.0',time:'2024-03'}],scores:[{courseName:'通信原理',semester:'2025-2026-2',score:48,passed:false},{courseName:'数字信号处理',semester:'2025-2026-2',score:55,passed:false},{courseName:'电磁场理论',semester:'2025-2026-2',score:68,passed:true}]},
        { name:'李XX',sid:'2021012346',college:'地球科学学院',class:'通信212',level:'警告',type:'GPA下降',detail:'连续2学期GPA下降0.5',status:'已通知',time:'2025-06-01',gpaHistory:[3.5,3.2,2.9,2.7,2.5],alerts:[{level:'警告',type:'GPA下降',status:'已通知',detail:'连续2学期GPA下降0.5',time:'2025-06-01'}],scores:[{courseName:'通信原理',semester:'2025-2026-2',score:72,passed:true},{courseName:'高等数学II',semester:'2025-2026-2',score:68,passed:true}]},
        { name:'王XX',sid:'2021012347',college:'地球科学学院',class:'通信211',level:'提醒',type:'单科挂科',detail:'通信原理48分·先修未通过',status:'已约谈',time:'2025-05-28',gpaHistory:[3.2,3.0,2.8],alerts:[],scores:[{courseName:'通信原理',semester:'2025-2026-2',score:48,passed:false}]},
        { name:'赵XX',sid:'2022013001',college:'石油工程学院',class:'石工221',level:'严重',type:'挂科累积',detail:'挂科4门·GPA1.85',status:'未处理',time:'2025-06-02',gpaHistory:[2.5,2.1,1.8],alerts:[],scores:[{courseName:'油藏工程',semester:'2025-2026-2',score:45,passed:false},{courseName:'钻井工程',semester:'2025-2026-2',score:52,passed:false}]},
        { name:'钱XX',sid:'2023014001',college:'化学工程学院',class:'化工231',level:'警告',type:'学分缺口',detail:'学分缺口15·先修未通过2门',status:'未处理',time:'2025-06-01',gpaHistory:[2.8,2.6],alerts:[],scores:[{courseName:'有机化学',semester:'2025-2026-2',score:58,passed:false}]},
        { name:'孙XX',sid:'2021013002',college:'机械学院',class:'机械211',level:'严重',type:'挂科累积',detail:'挂科3门·GPA1.92·学分缺口32',status:'未处理',time:'2025-06-04',gpaHistory:[2.2,1.9,1.8,1.7],alerts:[],scores:[{courseName:'工程力学',semester:'2025-2026-2',score:42,passed:false},{courseName:'机械原理',semester:'2025-2026-2',score:55,passed:false}]},
        { name:'周XX',sid:'2022015001',college:'信息工程学院',class:'信息221',level:'警告',type:'GPA下降',detail:'连续3学期GPA从3.5降至2.8',status:'已通知',time:'2025-05-30',gpaHistory:[3.5,3.2,3.0,2.8],alerts:[],scores:[]},
        { name:'吴XX',sid:'2023016001',college:'工商管理学院',class:'工商231',level:'提醒',type:'单科挂科',detail:'高等数学II 55分',status:'已约谈',time:'2025-05-25',gpaHistory:[3.1,2.9],alerts:[],scores:[{courseName:'高等数学II',semester:'2025-2026-2',score:55,passed:false}]},
        { name:'郑XX',sid:'2022017001',college:'理学院',class:'理学221',level:'严重',type:'挂科累积',detail:'挂科6门·GPA1.65·学分缺口48',status:'未处理',time:'2025-06-05',gpaHistory:[2.5,2.0,1.7,1.6],alerts:[],scores:[{courseName:'高等数学A(二)',semester:'2025-2026-2',score:38,passed:false},{courseName:'大学物理A',semester:'2025-2026-2',score:42,passed:false}]},
        { name:'冯XX',sid:'2023018001',college:'外国语学院',class:'英语231',level:'提醒',type:'出勤异常',detail:'英语精读缺勤>3次·出勤率<85%',status:'已通知',time:'2025-05-20',gpaHistory:[3.8,3.6],alerts:[],scores:[{courseName:'英语精读',semester:'2025-2026-2',score:78,passed:true}]},
      ],
    }},
    '/api/admin/student/2021012345': { data: {
      code:'2021012345',name:'张XX',collegeId:'GE',collegeName:'地球科学学院',majorName:'通信工程',className:'通信211',
      enrollOn:'2021-09-01',graduateOn:'2025-06-30',
      kpis:[
        {label:'当前GPA',value:'2.35',formula:'累计平均绩点',color:'#DC2626',sub:'持续下降'},
        {label:'学分完成',value:'98/164',formula:'已修÷要求',color:'#EA580C',sub:'缺口66学分'},
        {label:'预警状态',value:'⚠ 严重',formula:'当前预警等级',color:'#DC2626',sub:'挂科5门'},
        {label:'毕业预判',value:'可能延毕',formula:'基于当前进度推算',color:'#EA580C',sub:'建议补修3门'},
      ],
      gpaHistory:[3.1,2.8,2.5,2.4,2.3],
      alertHistory:[
        {level:'严重',type:'挂科累积',detail:'挂科5门·GPA2.05·学分缺口66',time:'2025-06-03'},
        {level:'严重',type:'GPA异常',detail:'GPA<2.0·连续下降',time:'2024-03-15'},
        {level:'警告',type:'挂科累积',detail:'挂科3门·学分缺口42',time:'2023-09-20'},
      ],
      scores:[
        {semester:'2025-2026-2',courseCode:'EE301',courseName:'通信原理',score:48,gp:0,passed:false,takeType:'正常',examStatus:'正常'},
        {semester:'2025-2026-2',courseCode:'EE302',courseName:'数字信号处理',score:55,gp:0,passed:false,takeType:'重修',examStatus:'正常'},
        {semester:'2025-2026-2',courseCode:'EE303',courseName:'电磁场理论',score:68,gp:1.7,passed:true,takeType:'正常',examStatus:'正常'},
        {semester:'2024-2025-1',courseCode:'EE301',courseName:'通信原理',score:52,gp:0,passed:false,takeType:'正常',examStatus:'正常'},
        {semester:'2024-2025-1',courseCode:'MA201',courseName:'高等数学II',score:45,gp:0,passed:false,takeType:'补考',examStatus:'正常'},
        {semester:'2024-2025-1',courseCode:'PH201',courseName:'大学物理II',score:78,gp:2.7,passed:true,takeType:'正常',examStatus:'正常'},
      ],
    }},
    '/api/admin/schools': { data: [
      { name:'东北大学秦皇岛分校',status:'生效中',signed:'2024-03-15',expire:'2029-03-14',syncStatus:'正常',deployFee:'¥12万' },
      { name:'华东师范大学',status:'生效中',signed:'2023-09-01',expire:'2028-08-31',syncStatus:'正常',deployFee:'¥15万' },
      { name:'四川师范大学',status:'已签约',signed:'2025-01-10',expire:'2030-01-09',syncStatus:'待部署',deployFee:'¥10万' },
      { name:'北京信息科技大学',status:'已签约',signed:'2025-06-01',expire:'2030-05-31',syncStatus:'待部署',deployFee:'¥10万' },
      { name:'东北石油大学',status:'协商中',signed:'—',expire:'—',syncStatus:'—',deployFee:'待定' },
    ]},
    '/api/admin/sync': { data: {
      schools: [
        { name:'东北大学秦皇岛分校', types:[
          { type:'学生信息',status:'正常',lastSync:'2025-06-17 08:30',rows:18532,duration:'12s',failCount:0 },
          { type:'课程成绩',status:'正常',lastSync:'2025-06-17 02:30',rows:284700,duration:'45s',failCount:3 },
          { type:'培养方案',status:'正常',lastSync:'2025-06-16 08:30',rows:320,duration:'3s',failCount:0 },
          { type:'开课计划',status:'正常',lastSync:'2025-06-17 06:00',rows:4521,duration:'8s',failCount:0 },
        ]},
        { name:'华东师范大学', types:[
          { type:'学生信息',status:'正常',lastSync:'2025-06-17 08:00',rows:22100,duration:'15s',failCount:0 },
          { type:'课程成绩',status:'正常',lastSync:'2025-06-17 02:00',rows:312500,duration:'52s',failCount:5 },
          { type:'培养方案',status:'正常',lastSync:'2025-06-16 08:00',rows:280,duration:'2s',failCount:0 },
          { type:'开课计划',status:'正常',lastSync:'2025-06-17 06:00',rows:5100,duration:'10s',failCount:0 },
        ]},
        { name:'四川师范大学', types:[
          { type:'学生信息',status:'待部署',lastSync:'—',rows:0,duration:'—',failCount:0 },
          { type:'课程成绩',status:'待部署',lastSync:'—',rows:0,duration:'—',failCount:0 },
          { type:'培养方案',status:'待部署',lastSync:'—',rows:0,duration:'—',failCount:0 },
          { type:'开课计划',status:'待部署',lastSync:'—',rows:0,duration:'—',failCount:0 },
        ]},
      ],
      logs: [
        { time:'2025-06-17 08:30:12',school:'东北大学秦皇岛分校',type:'学生信息',status:'成功',rows:18532,duration:'12s',error:'' },
        { time:'2025-06-17 06:00:05',school:'东北大学秦皇岛分校',type:'开课计划',status:'成功',rows:4521,duration:'8s',error:'' },
        { time:'2025-06-17 02:30:45',school:'东北大学秦皇岛分校',type:'课程成绩',status:'部分成功',rows:284700,duration:'45s',error:'3条校验失败: 成绩格式异常' },
        { time:'2025-06-17 08:00:00',school:'华东师范大学',type:'学生信息',status:'成功',rows:22100,duration:'15s',error:'' },
        { time:'2025-06-17 02:00:00',school:'华东师范大学',type:'课程成绩',status:'部分成功',rows:312500,duration:'52s',error:'5条校验失败: 课程代码不存在' },
        { time:'2025-06-16 08:30:00',school:'东北大学秦皇岛分校',type:'培养方案',status:'成功',rows:320,duration:'3s',error:'' },
        { time:'2025-06-16 08:00:00',school:'华东师范大学',type:'培养方案',status:'成功',rows:280,duration:'2s',error:'' },
        { time:'2025-06-15 12:00:00',school:'东北大学秦皇岛分校',type:'学生信息',status:'失败',rows:0,duration:'120s',error:'连接超时，重试3次后放弃' },
      ],
    }},

    '/api/admin/meta/filters': { data: {
      current: '2025-2026-2',
      semesters: [
        { value:'2022-2023-1',label:'2022-2023-1',current:false },
        { value:'2022-2023-2',label:'2022-2023-2',current:false },
        { value:'2023-2024-1',label:'2023-2024-1',current:false },
        { value:'2023-2024-2',label:'2023-2024-2',current:false },
        { value:'2024-2025-1',label:'2024-2025-1',current:false },
        { value:'2024-2025-2',label:'2024-2025-2',current:false },
        { value:'2025-2026-1',label:'2025-2026-1',current:false },
        { value:'2025-2026-2',label:'2025-2026-2(当前)',current:true },
      ],
      grades: ['2021','2022','2023','2024'],
      campuses: ['校本部','克拉玛依校区'],
      colleges: [
        { value:'PE',label:'石油工程学院' },{ value:'GE',label:'地球科学学院' },
        { value:'CE',label:'化学工程学院' },{ value:'ME',label:'机械与储运工程学院' },
        { value:'GP',label:'地球物理与信息工程学院' },{ value:'SC',label:'理学院' },
        { value:'BA',label:'工商管理学院' },{ value:'FL',label:'外国语学院' },
        { value:'HS',label:'人文社会科学学院' },
      ],
      courseNature: ['必修','选修','公选'],
      titles: ['教授','副教授','讲师','助教','研究员','高级工程师'],
      majors: [
        { value:'PE1',label:'石油工程',college:'PE' },{ value:'PE2',label:'油气储运',college:'PE' },
        { value:'PE3',label:'海洋油气',college:'PE' },{ value:'GE1',label:'通信工程',college:'GE' },
        { value:'GE2',label:'地球物理学',college:'GE' },{ value:'CE1',label:'化学工程',college:'CE' },
        { value:'CE2',label:'应用化学',college:'CE' },{ value:'ME1',label:'机械工程',college:'ME' },
        { value:'GP1',label:'计算机科学',college:'GP' },{ value:'GP2',label:'软件工程',college:'GP' },
        { value:'GP3',label:'电子信息工程',college:'GP' },{ value:'SC1',label:'数学与应用数学',college:'SC' },
        { value:'BA1',label:'工商管理',college:'BA' },{ value:'BA2',label:'会计学',college:'BA' },
        { value:'FL1',label:'英语',college:'FL' },
      ],
      classes: [
        { value:'C1',label:'通信211',major:'GE1',grade:'2021' },
        { value:'C2',label:'通信212',major:'GE1',grade:'2021' },
        { value:'C3',label:'石工221',major:'PE1',grade:'2022' },
        { value:'C4',label:'化工231',major:'CE1',grade:'2023' },
        { value:'C5',label:'计科241',major:'GP1',grade:'2024' },
        { value:'C6',label:'机械211',major:'ME1',grade:'2021' },
        { value:'C7',label:'英语231',major:'FL1',grade:'2023' },
        { value:'C8',label:'软件221',major:'GP2',grade:'2022' },
      ],
      categories: ['数学与自然科学','学科基础','专业必修','专业选修','通识选修','实践环节'],
      roomTypes: ['普通教室','多媒体教室','阶梯教室','实验室','机房','体育场地'],
      buildings: ['第一教学楼','第二教学楼','第三教学楼','实验楼A','实验楼B','体育馆','主楼'],
      years: ['2022','2023','2024','2025'],
      attritionKinds: ['休学','复学','退学','转专业'],
      sizeBuckets: ['小班(<30)','中班(30-60)','大班(60-120)','超大班(>120)'],
      alert: { level: ['严重','警告','提醒'], type: ['GPA下降','挂科累积','学分缺口','核心课挂科','出勤异常','退学风险'], status: ['未处理','已通知','已约谈','已解决'] },
      retake: ['重修','非重修'],
    }},

    // ── 教学运行分析 ──
    '/api/admin/operation/courses': { data: {
      kpis: [
        { label:'本学期开课门数', value:'2,847', formula:'去重课程计数', tone:'primary' },
        { label:'教学班数', value:'4,521', formula:'排课教学班总数', tone:'primary' },
        { label:'平均班额', value:'38.2', formula:'总修读人次÷教学班数', tone:'teal' },
        { label:'合班率', value:'62.5%', formula:'合班教学班÷总教学班', tone:'amber' },
      ],
      deptCourses: [
        { id:'GP',name:'地球物理与信息工程学院',courseCount:482,lessonCount:812,pct:16.9,level:'高'},
        { id:'PE',name:'石油工程学院',courseCount:395,lessonCount:658,pct:13.9,level:'高'},
        { id:'ME',name:'机械与储运工程学院',courseCount:368,lessonCount:602,pct:12.9,level:'高'},
        { id:'CE',name:'化学工程学院',courseCount:341,lessonCount:568,pct:12.0,level:'中'},
        { id:'GE',name:'地球科学学院',courseCount:325,lessonCount:542,pct:11.4,level:'中'},
        { id:'BA',name:'工商管理学院',courseCount:298,lessonCount:488,pct:10.5,level:'中'},
        { id:'SC',name:'理学院',courseCount:285,lessonCount:465,pct:10.0,level:'中'},
        { id:'FL',name:'外国语学院',courseCount:208,lessonCount:256,pct:7.3,level:'低'},
        { id:'HS',name:'人文社会科学学院',courseCount:145,lessonCount:130,pct:5.1,level:'低'},
      ],
      typeDist: [
        { name:'专业必修',count:985 },{ name:'专业选修',count:620 },{ name:'学科基础',count:485 },
        { name:'数学与自然科学',count:312 },{ name:'通识选修',count:258 },{ name:'实践环节',count:187 },
      ],
      sizeDist: [
        { label:'小班(<30)',count:1280,pct:28.3,color:'#0D9488' },
        { label:'中班(30-60)',count:1850,pct:40.9,color:'#4F46E5' },
        { label:'大班(60-120)',count:1080,pct:23.9,color:'#D97706' },
        { label:'超大班(>120)',count:311,pct:6.9,color:'#E11D48' },
      ],
      trend: [
        { semester:'2023-2024-1',courseCount:2680,lessonCount:4320,avgSize:36.8 },
        { semester:'2023-2024-2',courseCount:2710,lessonCount:4380,avgSize:37.1 },
        { semester:'2024-2025-1',courseCount:2785,lessonCount:4460,avgSize:37.5 },
        { semester:'2024-2025-2',courseCount:2810,lessonCount:4495,avgSize:37.9 },
        { semester:'2025-2026-1',courseCount:2835,lessonCount:4510,avgSize:38.0 },
        { semester:'2025-2026-2',courseCount:2847,lessonCount:4521,avgSize:38.2 },
      ],
      totalCourses: 2847,
    }},

    '/api/admin/operation/classroom': { data: {
      kpis: [
        { label:'教室总数', value:'342', formula:'在用教室总数', tone:'primary' },
        { label:'平均周利用率', value:'68.5%', formula:'各教室已排课时÷可用时段均值', tone:'primary' },
        { label:'高峰时段利用率', value:'92.1%', formula:'最满时段(2-4节)覆盖比', tone:'danger' },
        { label:'低利用率教室', value:'48', formula:'周利用率<30% 的教室', tone:'amber' },
        { label:'教学楼房数', value:'7', formula:'含教室的楼栋数', tone:'teal' },
      ],
      heatmap: {
        '周一':{1:72,2:92,3:85,4:65},
        '周二':{1:78,2:90,3:82,4:60},
        '周三':{1:68,2:88,3:80,4:58},
        '周四':{1:74,2:91,3:83,4:62},
        '周五':{1:65,2:82,3:75,4:52},
      },
      buildings: [
        { name:'第一教学楼',pct:82 },{ name:'第二教学楼',pct:75 },{ name:'第三教学楼',pct:68 },
        { name:'实验楼A',pct:58 },{ name:'实验楼B',pct:52 },{ name:'主楼',pct:45 },{ name:'体育馆',pct:38 },
      ],
      types: [
        { name:'多媒体教室',pct:85 },{ name:'阶梯教室',pct:72 },{ name:'普通教室',pct:68 },
        { name:'实验室',pct:58 },{ name:'机房',pct:52 },{ name:'体育场地',pct:35 },
      ],
    }},

    '/api/admin/operation/schedule-changes': { data: {
      kpis: [
        { label:'本学期调课次数', value:'187', formula:'已审批通过的调课申请数', tone:'primary' },
        { label:'停课次数', value:'24', formula:'已审批通过的停课申请数', tone:'danger' },
        { label:'受影响学生人次', value:'12,850', formula:'∑(调停课教学班修读人数)', tone:'danger' },
        { label:'自动审核通过率', value:'78.5%', formula:'系统自动审核通过÷总通过', tone:'teal' },
      ],
      deptRanks: [
        { id:'GP',name:'地球物理与信息工程学院',totalLessons:812,changeCount:28,pct:3.45 },
        { id:'ME',name:'机械与储运工程学院',totalLessons:602,changeCount:20,pct:3.32 },
        { id:'SC',name:'理学院',totalLessons:465,changeCount:14,pct:3.01 },
        { id:'CE',name:'化学工程学院',totalLessons:568,changeCount:16,pct:2.82 },
        { id:'FL',name:'外国语学院',totalLessons:256,changeCount:7,pct:2.73 },
        { id:'GE',name:'地球科学学院',totalLessons:542,changeCount:13,pct:2.40 },
        { id:'PE',name:'石油工程学院',totalLessons:658,changeCount:15,pct:2.28 },
        { id:'BA',name:'工商管理学院',totalLessons:488,changeCount:10,pct:2.05 },
        { id:'HS',name:'人文社会科学学院',totalLessons:130,changeCount:2,pct:1.54 },
      ],
      reasonDist: [
        { name:'教师因病/因事',count:82,color:'#4F46E5' },
        { name:'学术会议/出差',count:48,color:'#0D9488' },
        { name:'教学设备故障',count:24,color:'#D97706' },
        { name:'教学场地调整',count:18,color:'#6366F1' },
        { name:'其他原因',count:15,color:'#94A3B8' },
      ],
      frequentTeachers: [
        { id:'T018',name:'陈XX',dept:'地球物理与信息工程学院',count:5,reason:'学术会议/出差' },
        { id:'T056',name:'刘XX',dept:'石油工程学院',count:4,reason:'因病/因事' },
        { id:'T102',name:'吴XX',dept:'理学院',count:3,reason:'因病/因事' },
      ],
      monthlyTrend: [
        { month:'2025-09',count:18 },{ month:'2025-10',count:22 },{ month:'2025-11',count:25 },
        { month:'2025-12',count:20 },{ month:'2026-01',count:15 },{ month:'2026-02',count:8 },
        { month:'2026-03',count:28 },{ month:'2026-04',count:31 },{ month:'2026-05',count:20 },
      ],
    }},

    '/api/admin/operation/teacher-load': { data: {
      kpis: [
        { label:'专任教师数', value:'1,203', formula:'在职专任教师', tone:'primary' },
        { label:'人均学时', value:'185', formula:'总学时÷教师数', tone:'primary' },
        { label:'教授上课率', value:'91.2%', formula:'为本科生上课教授÷教授总数', tone:'teal' },
        { label:'过载教师', value:'48', formula:'学时>280 或 课程>5门', tone:'danger' },
      ],
      titleLoad: [
        { title:'教授',count:285,avgHours:168,avgCourses:2.1,teachingRate:91.2,status:'ok',note:'达标'},
        { title:'副教授',count:420,avgHours:192,avgCourses:2.8,teachingRate:94.5,status:'ok',note:'达标'},
        { title:'讲师',count:368,avgHours:208,avgCourses:3.5,teachingRate:98.2,status:'ok',note:'活跃'},
        { title:'助教',count:130,avgHours:142,avgCourses:2.2,teachingRate:82.5,status:'warn',note:'接近预警'},
      ],
      loadDist: [
        { label:'低(<80)',count:285,pct:23.7,color:'#0D9488' },
        { label:'正常(80-180)',count:520,pct:43.2,color:'#4F46E5' },
        { label:'高(180-280)',count:350,pct:29.1,color:'#D97706' },
        { label:'过载(>280)',count:48,pct:4.0,color:'#E11D48' },
      ],
      overloaded: [
        { id:'T008',name:'张XX',title:'副教授',dept:'地球物理与信息工程学院',hours:320,courses:6 },
        { id:'T025',name:'李XX',title:'教授',dept:'石油工程学院',hours:296,courses:5 },
        { id:'T042',name:'王XX',title:'讲师',dept:'理学院',hours:305,courses:7 },
      ],
      deptLoad: [
        { id:'GP',dept:'地球物理与信息工程学院',teacherCount:210,avgHours:210,avgCourses:3.8,loadLevel:85 },
        { id:'PE',dept:'石油工程学院',teacherCount:185,avgHours:195,avgCourses:3.2,loadLevel:78 },
        { id:'SC',dept:'理学院',teacherCount:95,avgHours:225,avgCourses:4.5,loadLevel:92 },
        { id:'CE',dept:'化学工程学院',teacherCount:142,avgHours:188,avgCourses:3.0,loadLevel:72 },
        { id:'ME',dept:'机械与储运工程学院',teacherCount:168,avgHours:178,avgCourses:2.8,loadLevel:68 },
        { id:'GE',dept:'地球科学学院',teacherCount:155,avgHours:182,avgCourses:2.9,loadLevel:70 },
        { id:'BA',dept:'工商管理学院',teacherCount:128,avgHours:165,avgCourses:2.5,loadLevel:58 },
        { id:'FL',dept:'外国语学院',teacherCount:75,avgHours:145,avgCourses:2.2,loadLevel:48 },
        { id:'HS',dept:'人文社会科学学院',teacherCount:45,avgHours:120,avgCourses:1.8,loadLevel:35 },
      ],
    }},

    // ── 师资结构分析 ──
    '/api/admin/faculty/structure': { data: {
      facultyKpis: [
        { label:'专任教师数', value:'1,203', formula:'在职专任教师', tone:'primary' },
        { label:'教授占比', value:'23.7%', formula:'教授÷总教师数', tone:'teal' },
        { label:'博士学位占比', value:'62.5%', formula:'博士÷总教师数', tone:'teal' },
        { label:'教授上课率', value:'91.2%', formula:'为本科生上课教授÷教授总数', tone:'teal' },
        { label:'生师比', value:'15.4:1', formula:'在籍学生÷专任教师', tone:'primary' },
      ],
      structure: [
        { title:'职称结构', items:[
          { label:'教授',value:285,color:'#4F46E5' },{ label:'副教授',value:420,color:'#6366F1' },
          { label:'讲师',value:368,color:'#A5B4FC' },{ label:'助教及其他',value:130,color:'#C7D2FE' },
        ]},
        { title:'学历结构', items:[
          { label:'博士',value:752,color:'#0D9488' },{ label:'硕士',value:358,color:'#2DD4BF' },
          { label:'学士及其他',value:93,color:'#99F6E4' },
        ]},
        { title:'年龄结构', items:[
          { label:'35岁以下',value:312,color:'#D97706' },{ label:'36-45岁',value:482,color:'#F59E0B' },
          { label:'46-55岁',value:285,color:'#FCD34D' },{ label:'56岁以上',value:124,color:'#FEF08A' },
        ]},
        { title:'学缘结构', items:[
          { label:'本校',value:358,color:'#6366F1' },{ label:'国内其他',value:528,color:'#0EA5E9' },
          { label:'海外',value:218,color:'#94A3B8' },{ label:'企业/其他',value:99,color:'#CBD5E1' },
        ]},
      ],
      teachingRates: [
        { id:'GP',name:'地球物理与信息工程学院',profTotal:48,profRate:93.8,assocRate:96.2 },
        { id:'PE',name:'石油工程学院',profTotal:42,profRate:95.2,assocRate:94.5 },
        { id:'CE',name:'化学工程学院',profTotal:35,profRate:91.4,assocRate:92.8 },
        { id:'ME',name:'机械与储运工程学院',profTotal:38,profRate:89.5,assocRate:93.1 },
        { id:'GE',name:'地球科学学院',profTotal:36,profRate:90.2,assocRate:91.8 },
        { id:'BA',name:'工商管理学院',profTotal:28,profRate:88.5,assocRate:92.0 },
        { id:'SC',name:'理学院',profTotal:22,profRate:86.4,assocRate:88.5 },
        { id:'FL',name:'外国语学院',profTotal:15,profRate:84.2,assocRate:90.0 },
        { id:'HS',name:'人文社会科学学院',profTotal:10,profRate:78.5,assocRate:85.2 },
      ],
      teacherTrends: [
        { id:'T018',name:'陈XX',title:'教授',dept:'地球物理与信息工程学院',avgScore:88.5,trend:'up',students:42 },
        { id:'T056',name:'刘XX',title:'副教授',dept:'石油工程学院',avgScore:85.2,trend:'up',students:38 },
        { id:'T102',name:'吴XX',title:'讲师',dept:'理学院',avgScore:84.8,trend:'up',students:68 },
      ],
      notTeaching: [
        { name:'周XX',title:'教授',dept:'人文社会科学学院',reason:'学术休假',semesters:'2学期' },
        { name:'赵XX',title:'教授',dept:'外国语学院',reason:'外派交流访问',semesters:'3学期' },
      ],
    }},

    // ── 学生学业分析 ──
    '/api/admin/students/analysis': { data: {
      studentKpis: [
        { label:'统计学生数', value:'18,532', formula:'有有效成绩的在籍学生', tone:'primary' },
        { label:'平均GPA', value:'2.82', formula:'加权平均绩点', tone:'primary' },
        { label:'挂科率', value:'18.5%', formula:'有挂科学生÷统计学生', tone:'danger' },
        { label:'优秀率', value:'12.8%', formula:'GPA≥3.5学生占比', tone:'teal' },
        { label:'高危学生', value:'1,482', formula:'GPA<2.0学生', tone:'danger' },
        { label:'预警学生', value:'487', formula:'当前预警状态学生', tone:'danger' },
      ],
      clusters: [
        { label:'优秀(GPA≥3.5)',count:2372,pct:12.8,color:'#0D9488' },
        { label:'良好(3.0-3.5)',count:5189,pct:28.0,color:'#4F46E5' },
        { label:'一般(2.5-3.0)',count:5930,pct:32.0,color:'#6366F1' },
        { label:'困难(2.0-2.5)',count:3559,pct:19.2,color:'#D97706' },
        { label:'高危(<2.0)',count:1482,pct:8.0,color:'#E11D48' },
      ],
      gradeGpa: [
        { grade:'2024',gpa:2.98,students:4820,failRate:'12.5%',alertRate:'' },
        { grade:'2023',gpa:2.85,students:4650,failRate:'15.8%',alertRate:'2.1%' },
        { grade:'2022',gpa:2.72,students:4580,failRate:'19.2%',alertRate:'2.8%' },
        { grade:'2021',gpa:2.68,students:4482,failRate:'22.5%',alertRate:'3.5%' },
      ],
      creditDist: [
        { label:'已修≥90%',count:8520,pct:46.0,color:'#0D9488' },
        { label:'已修70-90%',count:5420,pct:29.2,color:'#4F46E5' },
        { label:'已修50-70%',count:3210,pct:17.3,color:'#D97706' },
        { label:'已修<50%',count:1382,pct:7.5,color:'#E11D48' },
      ],
      failCourses: [
        { id:'EE301',name:'通信原理',dept:'信息学院',failRate:11.3,failCount:37,totalCount:328,avgScore:73.2 },
        { id:'MA202',name:'高等数学II',dept:'理学院',failRate:10.8,failCount:164,totalCount:1520,avgScore:71.5 },
        { id:'PH202',name:'电磁场理论',dept:'信息学院',failRate:10.2,failCount:32,totalCount:310,avgScore:68.9 },
        { id:'CH301',name:'有机化学',dept:'化工学院',failRate:9.8,failCount:28,totalCount:285,avgScore:70.2 },
        { id:'CS201',name:'数据结构',dept:'信息学院',failRate:8.5,failCount:41,totalCount:480,avgScore:74.1 },
        { id:'ME301',name:'机械原理',dept:'机械学院',failRate:8.3,failCount:25,totalCount:302,avgScore:72.8 },
        { id:'EE304',name:'数字信号处理',dept:'信息学院',failRate:7.9,failCount:30,totalCount:380,avgScore:69.5 },
        { id:'MA203',name:'线性代数',dept:'理学院',failRate:7.1,failCount:96,totalCount:1350,avgScore:75.8 },
        { id:'PE201',name:'油藏工程',dept:'石油工程学院',failRate:6.8,failCount:18,totalCount:265,avgScore:77.2 },
        { id:'EN101',name:'大学英语IV',dept:'外国语学院',failRate:1.8,failCount:28,totalCount:1556,avgScore:82.5 },
      ],
    }},
  }

  // sync-detail 数据
  function getSyncDetailData(type: string): any[] {
    const all: Record<string, any[]> = {
      student: [
        { sid:'2021012345',name:'张XX',grade:'2021',college:'地球科学学院',major:'通信工程',class:'通信211',status:'在籍' },
        { sid:'2021012346',name:'李XX',grade:'2021',college:'地球科学学院',major:'通信工程',class:'通信212',status:'在籍' },
        { sid:'2022013001',name:'赵XX',grade:'2022',college:'石油工程学院',major:'石油工程',class:'石工221',status:'在籍' },
        { sid:'2023014001',name:'钱XX',grade:'2023',college:'化学工程学院',major:'化学工程',class:'化工231',status:'休学' },
        { sid:'2024012001',name:'孙XX',grade:'2024',college:'信息学院',major:'计算机科学',class:'计科241',status:'在籍' },
      ],
      course: [
        { semester:'2025-2026-2',sid:'2021012345',name:'张XX',course:'通信原理',credit:4,required:'必修',teacher:'王教授',retake:'否',score:48,grade:'不及格',gpa:0,passed:'未通过',finalScore:'48',makeupScore:'—',makeupFlag:'—' },
        { semester:'2025-2026-2',sid:'2021012346',name:'李XX',course:'通信原理',credit:4,required:'必修',teacher:'王教授',retake:'否',score:72,grade:'中等',gpa:2.3,passed:'通过',finalScore:'72',makeupScore:'—',makeupFlag:'—' },
        { semester:'2025-2026-2',sid:'2022013001',name:'赵XX',course:'油藏工程',credit:3,required:'必修',teacher:'刘教授',retake:'否',score:85,grade:'良好',gpa:3.3,passed:'通过',finalScore:'85',makeupScore:'—',makeupFlag:'—' },
        { semester:'2025-2026-2',sid:'2023014001',name:'钱XX',course:'有机化学',credit:3,required:'必修',teacher:'陈教授',retake:'否',score:65,grade:'及格',gpa:1.7,passed:'通过',finalScore:'65',makeupScore:'—',makeupFlag:'—' },
      ],
      plan: [
        { major:'通信工程',grade:'2021',courseCode:'EE301',courseName:'通信原理',credit:4,semester:'5',type:'专业必修',examType:'考试',module:'专业核心' },
        { major:'通信工程',grade:'2021',courseCode:'EE302',courseName:'数字信号处理',credit:3,semester:'5',type:'专业必修',examType:'考试',module:'专业核心' },
        { major:'石油工程',grade:'2021',courseCode:'PE201',courseName:'油藏工程',credit:3,semester:'5',type:'专业必修',examType:'考试',module:'专业核心' },
        { major:'计算机科学',grade:'2021',courseCode:'CS301',courseName:'数据结构',credit:4,semester:'4',type:'学科基础',examType:'考试',module:'学科基础' },
      ],
      offering: [
        { semester:'2025-2026-2',courseCode:'EE301',courseName:'通信原理',teacher:'王教授',college:'信息学院',classGroup:'通信211+通信212(合班)',weeklyHours:4,capacity:80,enrolled:76 },
        { semester:'2025-2026-2',courseCode:'PE201',courseName:'油藏工程',teacher:'刘教授',college:'石油工程学院',classGroup:'石工221(单班)',weeklyHours:3,capacity:45,enrolled:42 },
        { semester:'2025-2026-2',courseCode:'CS301',courseName:'数据结构',teacher:'赵副教授',college:'信息学院',classGroup:'计科231+计科232(合班)',weeklyHours:4,capacity:90,enrolled:88 },
      ],
    }
    return all[type] || []
  }
  // 去除查询参数
  function stripQuery(u: string) { const i = u.indexOf('?'); return i > -1 ? u.substring(0, i) : u }
  // 解析查询参数
  function parseParams(u: string): Record<string,string> {
    const p: Record<string,string> = {}
    const i = u.indexOf('?')
    if (i < 0) return p
    u.substring(i+1).split('&').forEach(kv => { const [k,v] = kv.split('='); if(k) p[decodeURIComponent(k)] = decodeURIComponent(v||'') })
    return p
  }
  // 简单 hash 取数字 (0–1)，让同参数产生稳定"变化"
  function hash01(s: string): number {
    let h = 0
    for (let i = 0; i < s.length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0 }
    return Math.abs(h % 1000) / 1000
  }
  // 深拷贝
  function clone<T>(o: T): T { return JSON.parse(JSON.stringify(o)) }
  // 根据 hash 微调数值
  function varyNum(v: number, hash: number, pct: number = 0.1): number {
    return Math.round((v * (1 + (hash - 0.5) * pct * 2)) * 10) / 10
  }

  function getDynamicMock(url: string) {
    const base = stripQuery(url)
    const q = parseParams(url)
    const qHash = hash01(JSON.stringify(q))
    // 学期偏移：不同学期给不同基准
    const semIdx = ['2022-2023-1','2022-2023-2','2023-2024-1','2023-2024-2','2024-2025-1','2024-2025-2','2025-2026-1','2025-2026-2'].indexOf(q.semester || '')
    const semBias = semIdx >= 0 ? (semIdx - 5) * 0.02 : 0  // 以 2024-2025-2 为基准

    // ── 教学运行分析（带查询参数）──
    if (base.startsWith('/api/admin/operation/courses')) {
      const d = clone(MOCKS['/api/admin/operation/courses'].data)
      const bias = qHash + semBias
      // 变更 KPI 数值
      d.kpis[0].value = (2847 + Math.round(bias * 200)).toLocaleString()
      d.kpis[1].value = (4521 + Math.round(bias * 300)).toLocaleString()
      d.kpis[2].value = String((38.2 + bias * 5).toFixed(1))
      d.kpis[3].value = (62.5 + bias * 5).toFixed(1) + '%'
      d.totalCourses = 2847 + Math.round(bias * 200)
      // 按学院筛选
      if (q.college) {
        const cm = MOCKS['/api/admin/meta/filters'].data.colleges
        const cn = cm.find((c:any) => c.value === q.college)
        d.deptCourses = d.deptCourses.filter((r:any) => r.id === q.college).map((r:any) => {
          r.courseCount += Math.round(bias * 20); r.lessonCount += Math.round(bias * 30)
          r.pct = Math.round(1000 / d.totalCourses * r.courseCount) / 10
          return r
        })
        if (cn) d.deptCourses[0].name = cn.label
        d.kpis.unshift({ label:'当前筛选', value: cn ? cn.label : q.college, formula:'已应用学院筛选', tone:'teal' })
      } else {
        d.deptCourses.forEach((r:any) => { r.courseCount += Math.round(bias * 30); r.lessonCount += Math.round(bias * 40) })
      }
      // 按班额筛选
      if (q.size) { d.sizeDist = d.sizeDist.filter((r:any) => r.label === q.size); if(d.sizeDist.length===0) d.sizeDist = clone(MOCKS['/api/admin/operation/courses'].data.sizeDist).slice(0,1) }
      // 趋势微调
      d.trend.forEach((t:any) => { t.courseCount += Math.round(bias * 50); t.avgSize += bias * 2 })
      return { data: d }
    }
    if (base.startsWith('/api/admin/operation/classroom')) {
      const d = clone(MOCKS['/api/admin/operation/classroom'].data)
      const bias = qHash + semBias
      d.kpis[0].value = String(342)  // 教室总数不变
      d.kpis[1].value = (68.5 + bias * 10).toFixed(1) + '%'
      d.kpis[2].value = (92.1 + bias * 5).toFixed(1) + '%'
      d.kpis[3].value = String(Math.max(20, 48 + Math.round(bias * 30)))
      // 按楼栋筛选
      if (q.building) { d.buildings = d.buildings.filter((r:any) => r.name === q.building) }
      // 按类型筛选
      if (q.room_type) { d.types = d.types.filter((r:any) => r.name === q.room_type) }
      // 热力图微调
      Object.keys(d.heatmap).forEach(day => {
        Object.keys(d.heatmap[day]).forEach(k => { d.heatmap[day][k] = Math.min(100, d.heatmap[day][k] + Math.round(bias * 8)) })
      })
      return { data: d }
    }
    if (base.startsWith('/api/admin/operation/schedule-changes')) {
      const d = clone(MOCKS['/api/admin/operation/schedule-changes'].data)
      const bias = qHash + semBias
      d.kpis[0].value = String(187 + Math.round(bias * 40))
      d.kpis[1].value = String(24 + Math.round(bias * 8))
      d.kpis[2].value = (12850 + Math.round(bias * 2000)).toLocaleString()
      if (q.college) { d.deptRanks = d.deptRanks.filter((r:any) => r.id === q.college) }
      d.deptRanks.forEach((r:any) => { r.changeCount += Math.round(bias * 4); r.pct = (r.changeCount / r.totalLessons * 100 + bias).toFixed(2) })
      d.monthlyTrend.forEach((t:any) => { t.count += Math.round(bias * 5) })
      return { data: d }
    }
    if (base.startsWith('/api/admin/operation/teacher-load')) {
      const d = clone(MOCKS['/api/admin/operation/teacher-load'].data)
      const bias = qHash + semBias
      d.kpis[1].value = String(185 + Math.round(bias * 20))
      d.kpis[3].value = String(48 + Math.round(bias * 15))
      if (q.title) { d.titleLoad = d.titleLoad.filter((r:any) => r.title === q.title) }
      if (q.college) { d.deptLoad = d.deptLoad.filter((r:any) => r.id === q.college) }
      d.titleLoad.forEach((r:any) => { r.avgHours += Math.round(bias * 10); r.teachingRate = Math.min(100, r.teachingRate + bias * 5) })
      d.deptLoad.forEach((r:any) => { r.loadLevel = Math.min(100, r.loadLevel + Math.round(bias * 10)) })
      return { data: d }
    }

    // ── 师资结构 ──
    if (base.startsWith('/api/admin/faculty/structure')) {
      const d = clone(MOCKS['/api/admin/faculty/structure'].data)
      const bias = qHash + semBias
      d.facultyKpis[0].value = (1203 + Math.round(bias * 30)).toLocaleString()
      d.facultyKpis[3].value = (91.2 + bias * 5).toFixed(1) + '%'
      if (q.college) { d.teachingRates = d.teachingRates.filter((r:any) => r.id === q.college) }
      if (q.title) { d.structure.forEach((s:any) => { s.items = s.items.filter((it:any) => it.label === q.title) }) }
      d.structure.forEach((s:any) => { s.items.forEach((it:any) => { it.value += Math.round(bias * 20) }) })
      return { data: d }
    }
    if (base.startsWith('/api/admin/faculty/')) {
      const id = base.split('/').pop()
      const bias = qHash + semBias
      const names = ['陈XX','李XX','王XX','张XX','刘XX']; const ni = hash01(id||'0')
      return { data: {
        name: names[Math.floor(ni * 5)], code: 'T0' + Math.floor(ni*99+1), deptName: '地球物理与信息工程学院',
        title: '教授', education: '博士研究生', degree: '工学博士', school: '清华大学',
        kpis: [
          { label:'本学期授课', value: String(2 + Math.round(bias*3)) + '门', formula:'当前学期承担课程' },
          { label:'修读学生', value: String(120 + Math.round(bias*50)) + '人', formula:'本学期教学班学生合计' },
          { label:'近5学期均分', value: (86 + bias*6).toFixed(1), formula:'教学班学生平均分均值' },
          { label:'科研论文', value: String(10 + Math.round(bias*8)) + '篇', formula:'近三年核心期刊论文' },
        ],
        semesters: ['2023-2024-1','2023-2024-2','2024-2025-1','2024-2025-2','2025-2026-1','2025-2026-2'],
        scoreTrend: [82,84,85,87,88,86].map(v => Math.round(v + bias*5)),
        currentCourses: [
          { courseName:'通信原理', className:'通信211+通信212(合班)', students:68 + Math.round(bias*20), hours:64, id:'EE301' },
          { courseName:'数字信号处理', className:'通信211(单班)', students:38 + Math.round(bias*10), hours:48, id:'EE302' },
          { courseName:'毕业设计', className:'通信211', students:12, hours:32, id:'EE399' },
        ],
        teachingHistory: [
          { semester:'2025-2026-2',courseName:'通信原理',students:68,avgScore:Math.round(86+bias*4),passRate:(92.5+bias*5).toFixed(1)+'%' },
          { semester:'2025-2026-2',courseName:'数字信号处理',students:38,avgScore:Math.round(82+bias*3),passRate:(88.2+bias*4).toFixed(1)+'%' },
          { semester:'2024-2025-2',courseName:'通信原理',students:72,avgScore:Math.round(87+bias*3),passRate:(94.1+bias*2).toFixed(1)+'%' },
          { semester:'2024-2025-1',courseName:'电磁场理论',students:42,avgScore:Math.round(85+bias*4),passRate:(90.5+bias*3).toFixed(1)+'%' },
          { semester:'2023-2024-2',courseName:'高频电子线路',students:58,avgScore:Math.round(84+bias*3),passRate:(89.8+bias*2).toFixed(1)+'%' },
        ],
      }}
    }

    // ── 学生学业分析（带查询参数）──
    if (base.startsWith('/api/admin/students/analysis')) {
      const d = clone(MOCKS['/api/admin/students/analysis'].data)
      const bias = qHash + semBias
      d.studentKpis[1].value = (2.82 + bias * 0.3).toFixed(2)
      d.studentKpis[2].value = (18.5 + bias * 5).toFixed(1) + '%'
      d.studentKpis[4].value = (1482 + Math.round(bias * 200)).toLocaleString()
      if (q.college) {
        const cm = MOCKS['/api/admin/meta/filters'].data.colleges
        const cn = cm.find((c:any) => c.value === q.college)
        if (cn) d.studentKpis.unshift({ label:'当前学院', value: cn.label, formula:'已应用学院筛选', tone:'teal' })
        d.gradeGpa.forEach((g:any) => { g.students = Math.round(g.students / 10) })
      }
      if (q.grade) { d.gradeGpa = d.gradeGpa.filter((g:any) => g.grade === q.grade) }
      if (q.retake === '重修') { d.studentKpis[2].value = '85.2%'; d.clusters = d.clusters.map((c:any) => ({...c, count: Math.round(c.count * 0.2)})) }
      d.clusters.forEach((c:any) => { c.count += Math.round(bias * 200) })
      d.failCourses.forEach((f:any) => { f.failRate = (f.failRate + bias * 2).toFixed(1); f.avgScore += Math.round(bias * 4) })
      return { data: d }
    }

    // ── Meta filters ──
    if (base.startsWith('/api/admin/meta/filters')) return MOCKS['/api/admin/meta/filters']

    if (base.startsWith('/api/admin/student/')) {
      return MOCKS['/api/admin/student/2021012345']
    }
    if (base.startsWith('/api/admin/college/')) {
      const id = base.split('/').pop()
      const c = MOCKS['/api/admin/dashboard'].data.colleges.find((x:any)=>x.id===id)
      const collegeName = c?c.name:'地球科学学院'
      return { data: {
        name: collegeName,
        kpi: [
          { label:'本院学生', value:String(c?c.students:2156), formula:'在籍本科生' },
          { label:'本学期开课', value:'312', formula:'当前学期开课门数' },
          { label:'本院教师', value:'87', formula:'专任教师数' },
          { label:'预警学生', value:'52', formula:'当前预警人数' },
          { label:'学位率', value:'95.1%', formula:'学位授予率' },
        ],
        majors: [
          { id:'PE1',name:'石油工程',students:890,gpa:3.22,failRate:'5.8%',alertCount:16,trend:'up'},
          { id:'PE2',name:'油气储运',students:756,gpa:3.08,failRate:'7.2%',alertCount:22,trend:'up'},
          { id:'PE3',name:'海洋油气',students:510,gpa:2.82,failRate:'9.5%',alertCount:28,trend:'down'},
        ],
        gradeCompare: [
          { grade:'2024级',creditDone:78,gpaAvg:'3.25',failRate:'5.2%'},
          { grade:'2023级',creditDone:72,gpaAvg:'3.12',failRate:'6.8%'},
          { grade:'2022级',creditDone:68,gpaAvg:'2.95',failRate:'8.1%'},
          { grade:'2021级',creditDone:62,gpaAvg:'2.78',failRate:'9.5%'},
        ],
        failCourses: [
          { id:'EE301',name:'油藏工程',failCount:18,totalCount:156,failRate:'11.5',avgScore:70.8,credits:3 },
          { id:'EE302',name:'钻井工程',failCount:12,totalCount:142,failRate:'8.5',avgScore:73.2,credits:4 },
          { id:'EE303',name:'采油工程',failCount:10,totalCount:130,failRate:'7.7',avgScore:74.5,credits:3 },
        ],
      }}
    }
    if (base.startsWith('/api/admin/major/')) {
      return { data: {
        name: '通信工程', college: '地球科学学院',
        kpi: [
          { label:'在校生', value:'386', formula:'在籍学生总数' },
          { label:'培养方案完成率', value:'74.5%', formula:'平均已修÷要求学分' },
          { label:'预警学生', value:'12', formula:'当前预警人数' },
          { label:'毕业率', value:'97.2%', formula:'应届毕业率' },
        ],
        gradeDetail: [
          { grade:'2024级',students:98,gpaAvg:'3.25',failRate:'5.2%',alertCount:2,creditDone:78,courses:[
            { name:'高等数学A(一)',failCount:5,totalCount:98,failRate:'5.1' },
          ]},
          { grade:'2023级',students:102,gpaAvg:'3.12',failRate:'6.8%',alertCount:3,creditDone:72,courses:[
            { name:'通信原理',failCount:8,totalCount:102,failRate:'7.8' },
            { name:'数字信号处理',failCount:6,totalCount:102,failRate:'5.9' },
          ]},
          { grade:'2022级',students:95,gpaAvg:'2.95',failRate:'8.1%',alertCount:4,creditDone:68,courses:[
            { name:'电磁场理论',failCount:9,totalCount:95,failRate:'9.5' },
            { name:'高频电子线路',failCount:7,totalCount:95,failRate:'7.4' },
          ]},
          { grade:'2021级',students:91,gpaAvg:'2.78',failRate:'9.5%',alertCount:3,creditDone:62,courses:[]},
        ],
        goalDistribution: { '升学读研':42,'签约就业':45,'灵活就业':8,'待业':5 },
      }}
    }
    if (base.startsWith('/api/admin/course/')) {
      return { data: {
        name: '通信原理', credits: 4, type: '专业必修', college: '信息学院',
        kpi:[
          { label:'修读人数', value:'328', formula:'本学期修读该课程学生数' },
          { label:'平均分', value:'73.2', formula:'加权平均分', detail:'满分100' },
          { label:'优秀率', value:'12.8%', formula:'≥90分占比', detail:'42人≥90分' },
          { label:'挂科率', value:'11.3%', formula:'<60分占比', detail:'37人挂科' },
        ],
        scoreDistribution: [
          { range:'90-100', label:'优秀', count:42, pct:12.8 },
          { range:'80-89', label:'良好', count:60, pct:18.3 },
          { range:'70-79', label:'中等', count:107, pct:32.6 },
          { range:'60-69', label:'及格', count:92, pct:28.1 },
          { range:'0-59', label:'不及格', count:27, pct:8.2 },
        ],
        history: [
          { semester:'2022-2023-2', avgScore:68, failRate:'18.0%', totalStudents:298 },
          { semester:'2023-2024-1', avgScore:70, failRate:'15.0%', totalStudents:305 },
          { semester:'2023-2024-2', avgScore:71, failRate:'13.0%', totalStudents:312 },
          { semester:'2024-2025-1', avgScore:73.2, failRate:'11.3%', totalStudents:328 },
        ],
        classDetail: [
          { className:'通信211', students:42, avgScore:75.2, failRate:'9.5%', teacher:'王教授' },
          { className:'通信212', students:38, avgScore:71.8, failRate:'13.2%', teacher:'王教授' },
          { className:'通信213', students:40, avgScore:72.5, failRate:'11.0%', teacher:'李副教授' },
        ],
      }}
    }
    // 报表中心 - 9种报表类型
    if (base.startsWith('/api/admin/reports')) {
      const u = new URL(url, 'http://localhost')
      const type = u.searchParams.get('type') || ''
      return { data: getReportData(type) }
    }
    // 培养方案数据
    if (base.startsWith('/api/admin/curriculum/plan')) {
      return { data: getPlanData() }
    }
    // 数据同步明细
    if (base.startsWith('/api/admin/sync-detail')) {
      const u = new URL(url, 'http://localhost')
      const type = u.searchParams.get('type') || 'student'
      return { data: getSyncDetailData(type) }
    }
    return { data: {} }
  }

  function getPlanData() {
    return {
      name: '石油工程', grade: '2007级', college: '石油工程学院', level: '本科',
      totalCredits: 196, requiredCredits: 104, electiveMinCredits: 48.5, practiceCredits: 43.5,
      modules: [
        {
          name: '通识教育课（必修）', credits: 68.5, required: true,
          subModules: [
            { name:'数学与物理基础', courses:[
              { code:'100616M001',name:'高等数学（Ⅰ）',credits:6, hours:96, term:'1', dept:'理学院' },
              { code:'100616M002',name:'高等数学（Ⅱ）',credits:6, hours:96, term:'2', dept:'理学院' },
              { code:'100616M003',name:'线性代数',credits:3, hours:48, term:'3', dept:'理学院' },
              { code:'100616M005',name:'概率统计基础',credits:3, hours:48, term:'3', dept:'理学院' },
              { code:'100627M001',name:'大学物理（Ⅰ）',credits:4, hours:64, term:'2', dept:'理学院' },
              { code:'100627M002',name:'大学物理（Ⅱ）',credits:4, hours:64, term:'3', dept:'理学院' },
              { code:'100627M003',name:'大学物理实验（Ⅰ）',credits:2, hours:30, term:'3', dept:'理学院' },
              { code:'100627M004',name:'大学物理实验（Ⅱ）',credits:1.5, hours:26, term:'4', dept:'理学院' },
              { code:'Y10617E001',name:'大学化学（Ⅰ）',credits:4.5, hours:72, term:'2', dept:'理学院' },
            ]},
            { name:'外语', courses:[
              { code:'100925M001',name:'大学英语（Ⅰ）',credits:4, hours:64, term:'1', dept:'外国语学院' },
              { code:'100925M002',name:'大学英语（Ⅱ）',credits:4, hours:64, term:'2', dept:'外国语学院' },
              { code:'100925M003',name:'大学英语（Ⅲ）',credits:4, hours:64, term:'3', dept:'外国语学院' },
              { code:'100925M004',name:'大学英语（Ⅳ）',credits:4, hours:64, term:'4', dept:'外国语学院' },
            ]},
            { name:'思政与体育', courses:[
              { code:'100844M001',name:'思想道德修养与法律基础',credits:2, hours:32, term:'1', dept:'马克思主义学院' },
              { code:'100844M002',name:'中国近现代史纲要',credits:2, hours:32, term:'1', dept:'马克思主义学院' },
              { code:'100844M003',name:'马克思主义基本原理概论',credits:3, hours:48, term:'1', dept:'马克思主义学院' },
              { code:'100844M006',name:'毛泽东思想邓小平理论概论（Ⅰ）',credits:2.5, hours:40, term:'3', dept:'马克思主义学院' },
              { code:'100844M007',name:'毛泽东思想邓小平理论概论（Ⅱ）',credits:2, hours:32, term:'4', dept:'马克思主义学院' },
              { code:'101099M001',name:'大学体育Ⅰ',credits:1, hours:32, term:'1', dept:'教育学院' },
              { code:'101099M002',name:'大学体育Ⅱ',credits:1, hours:32, term:'2', dept:'教育学院' },
              { code:'101099M003',name:'大学体育Ⅲ',credits:1, hours:32, term:'3', dept:'教育学院' },
              { code:'101099M004',name:'大学体育Ⅳ',credits:1, hours:32, term:'4', dept:'教育学院' },
            ]},
            { name:'计算机', courses:[
              { code:'Y10514M002',name:'大学计算机基础',credits:3, hours:48, term:'1', dept:'地球物理学院' },
            ]},
          ]
        },
        {
          name: '单独设置的实践环节（必修）', credits: 43.5, required: true,
          subModules: [{ name:'实践环节', courses:[
            { code:'100408P005',name:'计算机辅助绘图',credits:1, hours:20, term:'1', dept:'石油工程学院' },
            { code:'100925X001',name:'大学英语实践（Ⅰ）',credits:1, hours:16, term:'1', dept:'外国语学院' },
            { code:'101200X001',name:'军事训练（Ⅰ）',credits:2, hours:32, term:'1', dept:'武装部' },
            { code:'101500X001',name:'入学教育与安全教育',credits:1, hours:16, term:'1', dept:'教育学院' },
            { code:'100101P011',name:'地质实习',credits:2, hours:32, term:'1S', dept:'地球科学学院' },
            { code:'100203P008',name:'金工实习',credits:2, hours:32, term:'2S', dept:'石油工程学院' },
            { code:'100204P006',name:'生产实习',credits:4, hours:64, term:'3S', dept:'石油工程学院' },
            { code:'100203P006',name:'油层物理课程设计',credits:1, hours:0, term:'4', dept:'石油工程学院' },
            { code:'100203P005',name:'渗流力学课程设计',credits:1, hours:0, term:'5', dept:'石油工程学院' },
            { code:'100203P002',name:'钻井工程课程设计',credits:1, hours:16, term:'6', dept:'石油工程学院' },
            { code:'100203P003',name:'油藏工程课程设计',credits:1, hours:16, term:'6', dept:'石油工程学院' },
            { code:'100203P001',name:'采油工程课程设计',credits:1, hours:16, term:'7', dept:'石油工程学院' },
            { code:'100203P004',name:'完井工程课程设计',credits:1, hours:16, term:'7', dept:'石油工程学院' },
            { code:'100203P010',name:'毕业设计',credits:12, hours:256, term:'8', dept:'石油工程学院' },
            { code:'100844X004',name:'毛泽东思想社会实践',credits:1.5, hours:24, term:'', dept:'马克思主义学院' },
            { code:'101200X004',name:'大学生科技创新与文体活动',credits:4, hours:0, term:'', dept:'武装部' },
          ]}]
        },
        {
          name: '专业基础课（必修）', credits: 23.5, required: true,
          subModules: [{ name:'必修', courses:[
            { code:'100408T005',name:'机械制图',credits:2.5, hours:40, term:'1', dept:'石油工程学院' },
            { code:'100101E001',name:'普通地质学',credits:3, hours:48, term:'2', dept:'地球科学学院' },
            { code:'100410D001',name:'工程力学（双语）',credits:5, hours:80, term:'3', dept:'安全与海洋工程学院' },
            { code:'100203E001',name:'油层物理',credits:3, hours:48, term:'4', dept:'石油工程学院' },
            { code:'100203E009',name:'流体力学（双语）',credits:4, hours:64, term:'4', dept:'石油工程学院' },
            { code:'100203E005',name:'渗流力学',credits:3.5, hours:56, term:'5', dept:'石油工程学院' },
            { code:'100203E002',name:'油田化学工程',credits:2.5, hours:40, term:'6', dept:'石油工程学院' },
          ]}]
        },
        {
          name: '专业基础课（选修）', credits: 9.5, required: false, electiveRequired: 9.5,
          subModules: [{ name:'选修', courses:[
            { code:'100513L001',name:'电工电子学实验',credits:1, hours:16, term:'4', dept:'人工智能学院' },
            { code:'101400G001',name:'信息检索与网络资源利用',credits:1.5, hours:24, term:'4', dept:'图书馆' },
            { code:'Y10513T001',name:'电工电子学',credits:3.5, hours:56, term:'4', dept:'地球物理学院' },
            { code:'Y20408T012',name:'机械设计基础',credits:3, hours:48, term:'4', dept:'机械与储运工程学院' },
            { code:'100203T003',name:'油气田地面工程概论',credits:2, hours:32, term:'5', dept:'石油工程学院' },
            { code:'100410C001',name:'工程热力学与传热学',credits:3, hours:48, term:'5', dept:'机械与储运工程学院' },
            { code:'100515T025',name:'测井解释与生产测井',credits:3, hours:48, term:'5', dept:'地球物理学院' },
            { code:'100203T029',name:'石油工程专业英语',credits:2, hours:32, term:'7', dept:'石油工程学院' },
            { code:'100203T027',name:'石油工程新理论与新技术讲座',credits:2, hours:32, term:'8', dept:'石油工程学院' },
            { code:'100203T043',name:'石油工程案例分析',credits:2, hours:32, term:'8', dept:'石油工程学院' },
          ]}]
        },
        {
          name: '专业课（必修）', credits: 12, required: true,
          subModules: [{ name:'核心课程', courses:[
            { code:'100203E011',name:'钻井工程 ★',credits:3, hours:48, term:'6', dept:'石油工程学院' },
            { code:'100203T001',name:'油藏工程 ★',credits:3, hours:48, term:'6', dept:'石油工程学院' },
            { code:'100203E003',name:'采油工程 ★',credits:3, hours:48, term:'7', dept:'石油工程学院' },
            { code:'100203E004',name:'完井工程 ★',credits:3, hours:48, term:'7', dept:'石油工程学院' },
          ]}]
        },
        {
          name: '专业课（选修·三方向选一）', credits: 24, required: false, electiveRequired: 16,
          subModules: [
            {
              name: '方向A：油气井工程（选修≥16学分）', courses: [
                { code:'100203T010',name:'石油工程测控基础',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100203T012',name:'油气井工程设备与工具',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100203T016',name:'油气钻采管柱设计',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100203T030',name:'综合录井技术',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100204T009',name:'岩石力学',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100203E012',name:'油气层产能保护',credits:2, hours:32, term:'7', dept:'石油工程学院' },
                { code:'100203T005',name:'水射流基础与应用',credits:2, hours:32, term:'7', dept:'石油工程学院' },
                { code:'100203T009',name:'油气井流体力学',credits:2, hours:32, term:'7', dept:'石油工程学院' },
                { code:'100203T038',name:'钻井复杂事故与处理',credits:2, hours:32, term:'7', dept:'石油工程学院' },
                { code:'Y10203T006',name:'钻井液工艺原理',credits:2, hours:32, term:'7', dept:'石油工程学院' },
              ]
            },
            {
              name: '方向B：油气田开发工程（选修≥18学分）', courses: [
                { code:'100203T014',name:'油气田开发基础',credits:3, hours:48, term:'5', dept:'石油工程学院' },
                { code:'100203T022',name:'工业流变学',credits:2, hours:32, term:'5', dept:'石油工程学院' },
                { code:'100203C002',name:'气藏工程',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'Y10203T033',name:'提高采收率基础',credits:2, hours:32, term:'6', dept:'石油工程学院' },
                { code:'100203C001',name:'油藏数值模拟基础',credits:3, hours:48, term:'7', dept:'石油工程学院' },
                { code:'100203L001',name:'油气田开发实验',credits:1, hours:16, term:'7', dept:'石油工程学院' },
              ]
            },
            {
              name: '方向C：海洋石油工程（选修≥14学分）', courses: [
                { code:'100204T008',name:'海洋法',credits:1, hours:16, term:'4', dept:'石油工程学院' },
                { code:'100203T018',name:'海洋地质学和海洋环境',credits:3, hours:48, term:'5', dept:'石油工程学院' },
                { code:'100204T025',name:'船舶与海洋工程概论',credits:2, hours:32, term:'5', dept:'安全与海洋工程学院' },
                { code:'100204T016',name:'海洋油气装备',credits:2, hours:32, term:'6', dept:'安全与海洋工程学院' },
                { code:'100203T023',name:'海洋石油工程',credits:2, hours:32, term:'7', dept:'石油工程学院' },
              ]
            },
          ]
        },
        {
          name: '通识选修（校级模块）', credits: 15, required: false, electiveRequired: 15,
          subModules: [
            { name:'计算机类（要求≥4学分）', electiveRequired: 4, courses:[
              { code:'0108012229',name:'C语言程序设计',credits:2.5, hours:40, term:'', dept:'地球物理学院' },
              { code:'100616C005',name:'MATLAB语言',credits:2, hours:32, term:'', dept:'理学院' },
              { code:'Y11400G001',name:'信息检索与网络资源',credits:1.5, hours:24, term:'', dept:'图书馆' },
              { code:'Y50514G001',name:'C语言程序设计',credits:4, hours:64, term:'', dept:'地球物理学院' },
            ]},
            { name:'人文科学类（要求≥4学分）', electiveRequired: 4, courses:[
              { code:'0107012242',name:'中国古代诗赋赏析',credits:1.5, hours:24, term:'', dept:'马克思主义学院' },
              { code:'0107012266',name:'西方哲学思潮',credits:1.5, hours:24, term:'', dept:'马克思主义学院' },
              { code:'100855G001',name:'大学语文',credits:2, hours:32, term:'', dept:'教育学院' },
              { code:'100866G006',name:'乐理与视唱',credits:2, hours:32, term:'', dept:'教育学院' },
              { code:'100866G013',name:'大学美育',credits:1.5, hours:24, term:'', dept:'马克思主义学院' },
            ]},
            { name:'外语类（要求≥2学分）', electiveRequired: 2, courses:[
              { code:'0106012361',name:'强化综合英语I（四级）',credits:4, hours:64, term:'', dept:'外国语学院' },
              { code:'100925G009',name:'口译（Ⅰ）',credits:2, hours:32, term:'', dept:'外国语学院' },
              { code:'100925G029',name:'英文版石油概论',credits:2, hours:32, term:'', dept:'外国语学院' },
            ]},
            { name:'社会科学类（要求≥1.5学分）', electiveRequired: 1.5, courses:[
              { code:'0107012292',name:'社会学概论',credits:2, hours:32, term:'', dept:'马克思主义学院' },
              { code:'100719G001',name:'经济学基础',credits:2, hours:32, term:'', dept:'经济管理学院' },
              { code:'100723G001',name:'管理学原理',credits:2, hours:32, term:'', dept:'经济管理学院' },
            ]},
            { name:'体育与健康教育类（要求≥2学分）', electiveRequired: 2, courses:[
              { code:'101099G002',name:'体育选修（篮球）',credits:1, hours:24, term:'', dept:'教育学院' },
              { code:'101099G010',name:'体育选修（游泳）',credits:1, hours:24, term:'', dept:'教育学院' },
            ]},
            { name:'自然科学类（要求≥1.5学分）', electiveRequired: 1.5, courses:[
              { code:'100616G001',name:'复变函数',credits:2.5, hours:40, term:'', dept:'理学院' },
              { code:'100616G009',name:'数学建模',credits:2, hours:32, term:'', dept:'理学院' },
            ]},
          ]
        },
      ],
      // 毕业要求
      graduationRequirements: [
        '具有扎实的数学、物理、化学、力学、地质学、计算机应用基础及与石油工程有关的基础知识',
        '具有应用数学、地质学方法及系统的力学理论进行油气田开发设计的基本能力',
        '具有应用基础理论和基本知识进行油气钻采工程设计的基本能力',
        '具有一般钻采工具和设备部件机械设计的初步能力',
        '具有运用基础理论分析和解决石油工程实际问题、进行技术革新和科学研究的初步能力',
        '具有应用系统工程方法和现代经济知识进行石油工程生产、经营与管理的初步能力',
        '具有较强的外语和计算机应用能力',
        '具有自我学习和获取新知识的能力',
      ],
      // 学位要求
      degreeRequirement: '除满足学校规定的其它学位授予条件外，英语必须达到学校规定的国家CET四级考试成绩要求。',
    }
  }

  function getReportData(type: string): any[] {
    const all: Record<string, any[]> = {
      score: [
        { course:'高等数学A(二)',college:'理学院',avgScore:58.2,median:56,stddev:18.5,score90:48,score80:152,score70:380,score60:598,scoreFail:342 },
        { course:'大学物理A',college:'理学院',avgScore:65.8,median:67,stddev:15.2,score90:85,score80:210,score70:420,score60:510,scoreFail:195 },
        { course:'C语言程序设计',college:'信息学院',avgScore:68.5,median:70,stddev:14.8,score90:72,score80:185,score70:310,score60:248,scoreFail:75 },
        { course:'工程力学',college:'机械学院',avgScore:62.8,median:63,stddev:17.1,score90:38,score80:125,score70:230,score60:215,scoreFail:112 },
        { course:'有机化学',college:'化工学院',avgScore:70.2,median:72,stddev:13.5,score90:32,score80:88,score70:92,score60:48,scoreFail:25 },
        { course:'通信原理',college:'信息学院',avgScore:73.2,median:74,stddev:12.8,score90:42,score80:60,score70:107,score60:92,scoreFail:27 },
      ],
      passrank: [
        { course:'大学英语IV',college:'外国语学院',teacher:'陈教授',passRate:98.2,failRate:1.8,avgScore:82.5,excellent:35.2,rank:1 },
        { course:'体育IV',college:'体育部',teacher:'刘教授',passRate:97.8,failRate:2.2,avgScore:85.1,excellent:42.5,rank:2 },
        { course:'马克思主义原理',college:'马克思主义学院',teacher:'张教授',passRate:95.5,failRate:4.5,avgScore:78.2,excellent:18.5,rank:3 },
        { course:'通信原理',college:'信息学院',teacher:'王教授',passRate:88.7,failRate:11.3,avgScore:73.2,excellent:12.8,rank:4 },
        { course:'高等数学A(二)',college:'理学院',teacher:'李教授',passRate:77.5,failRate:22.5,avgScore:58.2,excellent:5.2,rank:5 },
      ],
      discipline: [
        { college:'信息学院',semester:'2025-2026-2',violation:5,cheat:3,rate:0.64 },
        { college:'机械学院',semester:'2025-2026-2',violation:3,cheat:2,rate:0.51 },
        { college:'理学院',semester:'2025-2026-2',violation:8,cheat:4,rate:1.07 },
        { college:'化工学院',semester:'2025-2026-2',violation:2,cheat:1,rate:0.35 },
      ],
      alert: [
        { name:'张XX',class:'通信211',college:'地球科学学院',major:'通信工程',level:'严重',type:'挂科累积',failCourses:5,failCredits:16,gapCredits:21,status:'未处理' },
        { name:'李XX',class:'通信212',college:'地球科学学院',major:'通信工程',level:'警告',type:'GPA下降',failCourses:2,failCredits:8,gapCredits:12,status:'已通知' },
        { name:'王XX',class:'石工221',college:'石油工程学院',major:'石油工程',level:'严重',type:'挂科累积',failCourses:4,failCredits:14,gapCredits:18,status:'已约谈' },
        { name:'赵XX',class:'化工231',college:'化学工程学院',major:'化学工程',level:'警告',type:'学分缺口',failCourses:3,failCredits:10,gapCredits:15,status:'未处理' },
      ],
      credit: [
        { major:'通信工程',grade:'2023级',generalReq:88,majorReq:44,gap:18 },
        { major:'计算机科学',grade:'2023级',generalReq:92,majorReq:68,gap:10 },
        { major:'软件工程',grade:'2023级',generalReq:90,majorReq:62,gap:12 },
        { major:'电子信息工程',grade:'2023级',generalReq:85,majorReq:52,gap:16 },
      ],
      attrition: [
        { college:'理学院',grade:'2023级',total:980,suspend:5,resume:2,dropout:2,transfer:8,rate:1.5 },
        { college:'信息学院',grade:'2023级',total:2030,suspend:3,resume:1,dropout:1,transfer:12,rate:0.8 },
        { college:'机械学院',grade:'2023级',total:1820,suspend:4,resume:2,dropout:3,transfer:6,rate:0.7 },
        { college:'化工学院',grade:'2023级',total:1650,suspend:2,resume:1,dropout:1,transfer:5,rate:0.5 },
      ],
      graduate: [
        { major:'通信工程',grade:'2021级',total:120,onTime:95.8,degree:94.2,finish:3.3,delay:0.8 },
        { major:'石油工程',grade:'2021级',total:135,onTime:97.0,degree:95.6,finish:2.2,delay:0.7 },
        { major:'计算机科学',grade:'2021级',total:150,onTime:94.7,degree:92.0,finish:4.0,delay:1.3 },
        { major:'英语',grade:'2021级',total:68,onTime:98.5,degree:97.1,finish:1.5,delay:0 },
      ],
      exam: [
        { college:'信息学院',grade:'2023级',cet4:'88.5%',cet6:'58.2%',nc2:'72.0%',nc3:'35.5%' },
        { college:'机械学院',grade:'2023级',cet4:'82.0%',cet6:'45.8%',nc2:'55.0%',nc3:'22.0%' },
        { college:'外国语学院',grade:'2023级',cet4:'96.0%',cet6:'78.5%',nc2:'48.0%',nc3:'18.0%' },
        { college:'理学院',grade:'2023级',cet4:'80.5%',cet6:'42.0%',nc2:'60.0%',nc3:'28.0%' },
      ],
      attend: [
        { college:'外国语学院',course:'大学英语IV',rate:96.5,absentGT3:12,absentGT3Pct:'1.8',trend:'stable' },
        { college:'信息学院',course:'通信原理',rate:92.1,absentGT3:28,absentGT3Pct:'8.5',trend:'down' },
        { college:'机械学院',course:'工程力学',rate:91.2,absentGT3:85,absentGT3Pct:'4.7',trend:'down' },
        { college:'理学院',course:'高等数学A(二)',rate:89.8,absentGT3:52,absentGT3Pct:'5.3',trend:'down' },
        { college:'化工学院',course:'有机化学',rate:94.5,absentGT3:8,absentGT3Pct:'2.8',trend:'up' },
      ],
    }
    return all[type] || []
  }

  // ── Auth Mock 数据 ──
  const ALL_MENUS: { menu_id: string; title: string; path: string; icon: string; sort_order: number }[] = [
    { menu_id: '/admin/dashboard', title: '数据大屏', path: '/admin/dashboard', icon: 'Odometer', sort_order: 1 },
    { menu_id: '/admin/alert', title: '预警查看', path: '/admin/alert', icon: 'Warning', sort_order: 2 },
    { menu_id: '/admin/operation/courses', title: '教学运行分析', path: '/admin/operation/courses', icon: 'Calendar', sort_order: 3 },
    { menu_id: '/admin/curriculum', title: '培养质量分析', path: '/admin/curriculum', icon: 'Reading', sort_order: 4 },
    { menu_id: '/admin/faculty', title: '师资保障分析', path: '/admin/faculty', icon: 'User', sort_order: 5 },
    { menu_id: '/admin/students/analysis', title: '学生学业分析', path: '/admin/students/analysis', icon: 'DataLine', sort_order: 6 },
    { menu_id: '/admin/reports', title: '管理决策专题', path: '/admin/reports', icon: 'Document', sort_order: 7 },
    { menu_id: '/admin/system/accounts', title: '账号管理', path: '/admin/system/accounts', icon: 'User', sort_order: 8 },
    { menu_id: '/admin/system/menus', title: '菜单管理', path: '/admin/system/menus', icon: 'Menu', sort_order: 9 },
    { menu_id: '/admin/system/roles', title: '角色管理', path: '/admin/system/roles', icon: 'UserFilled', sort_order: 10 },
    { menu_id: '/admin/settings', title: '系统设置', path: '/admin/settings', icon: 'Setting', sort_order: 11 },
  ]
  const ROLE_MENU_KEYS: Record<string, string[]> = {
    school_leader:        ['/admin/dashboard', '/admin/alert'],
    dean:                 ALL_MENUS.map(m => m.menu_id),
    dept_operation:       ['/admin/dashboard', '/admin/operation/courses'],
    dept_research:        ['/admin/dashboard', '/admin/curriculum', '/admin/reports', '/admin/faculty'],
    dept_practice:        ['/admin/dashboard', '/admin/reports'],
    quality_office:       ['/admin/dashboard', '/admin/curriculum', '/admin/reports'],
    college_dean:         ['/admin/dashboard', '/admin/alert', '/admin/curriculum', '/admin/reports', '/admin/operation/courses', '/admin/faculty', '/admin/students/analysis'],
    college_secretary:    ['/admin/dashboard', '/admin/alert', '/admin/curriculum', '/admin/reports', '/admin/operation/courses', '/admin/students/analysis'],
    counselor:            ['/admin/alert'],
    dept_director:        ['/admin/dashboard', '/admin/curriculum', '/admin/faculty'],
  }
  const ROLE_NAMES: Record<string, string> = {
    school_leader: '校领导', dean: '教务处处长', dept_operation: '教务处·运行科',
    dept_research: '教务处·教研科', dept_practice: '教务处·实践科', quality_office: '质量办/评估中心',
    college_dean: '二级学院·院长', college_secretary: '二级学院·教学秘书',
    counselor: '辅导员', dept_director: '系主任',
  }
  function getMenusForRole(role: string) {
    const keys = ROLE_MENU_KEYS[role] || ALL_MENUS.map(m => m.menu_id)
    return ALL_MENUS.filter(m => keys.includes(m.menu_id))
  }
  // token → { username, role } 映射（内存）
  const tokenStore: Record<string, { username: string; role: string }> = {}

  return {
    name: 'mock-api',
    configureServer(server) {
      // Auth mock（/api/auth/*）
      server.middlewares.use('/api/auth', (req, res, next) => {
        const url = req.url || ''
        res.setHeader('Content-Type', 'application/json; charset=utf-8')

        if (url === '/login' && req.method === 'POST') {
          let body = ''
          req.on('data', (chunk: Buffer) => { body += chunk.toString() })
          req.on('end', () => {
            try {
              const { username, password } = JSON.parse(body)
              if (!username || !password) {
                res.end(JSON.stringify({ code: 401, msg: '用户名或密码错误', data: null }))
                return
              }
              // 已知角色或默认 dean
              const role = ROLE_NAMES[username] ? username : 'dean'
              const displayRole = role === 'admin' ? 'dean' : role
              const roleName = username === 'admin' ? '系统管理员' : (ROLE_NAMES[role] || '教务处处长')
              const token = 'mock_' + Buffer.from(JSON.stringify({ username, role: displayRole })).toString('base64')
              tokenStore[token] = { username, role: displayRole }
              res.end(JSON.stringify({ code: 0, msg: 'ok', data: {
                token,
                user: { username: username === 'admin' ? 'admin' : role, name: roleName, role: displayRole, roleName,
                        menus: getMenusForRole(displayRole) }
              }}))
            } catch {
              res.end(JSON.stringify({ code: 401, msg: '用户名或密码错误', data: null }))
            }
          })
          return
        }

        if (url === '/me' && req.method === 'GET') {
          const auth = req.headers.authorization || ''
          const token = auth.replace('Bearer ', '')
          const info = tokenStore[token]
          if (!info) {
            res.statusCode = 401
            res.end(JSON.stringify({ code: 401, msg: 'Token 已过期', data: null }))
            return
          }
          const roleName = info.username === 'admin' ? '系统管理员' : (ROLE_NAMES[info.role] || '教务处处长')
          res.end(JSON.stringify({ code: 0, msg: 'ok', data: {
            username: info.username, name: roleName, role: info.role, roleName,
            menus: getMenusForRole(info.role)
          }}))
          return
        }

        if (url === '/logout' && req.method === 'POST') {
          const auth = req.headers.authorization || ''
          const token = auth.replace('Bearer ', '')
          delete tokenStore[token]
          res.end(JSON.stringify({ code: 0, msg: '已登出', data: null }))
          return
        }

        res.statusCode = 404
        res.end(JSON.stringify({ code: 404, msg: 'not found', data: null }))
      })

      // Admin mock（/api/admin/*）
      server.middlewares.use('/api/admin', (req, res, next) => {
        const url = req.url || '/'
        const fullUrl = '/api/admin' + url
        let result = MOCKS[fullUrl]
        if (!result) result = getDynamicMock(fullUrl)
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify(result))
      })
    },
  }
}

export default ({ mode }: { mode: string }) => {
  const root = process.cwd()
  const env = loadEnv(mode, root)
  const { VITE_VERSION, VITE_PORT, VITE_BASE_URL } = env

  console.log(`🚀 VERSION = ${VITE_VERSION}`)

  return defineConfig({
    define: { __APP_VERSION__: JSON.stringify(VITE_VERSION) },
    base: VITE_BASE_URL,
    server: {
      port: Number(VITE_PORT), host: true,
      proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@styles': resolvePath('src/assets/styles')
      }
    },
    build: {
      target: 'es2015', outDir: 'dist', chunkSizeWarningLimit: 2000,
      minify: 'terser',
      terserOptions: { compress: { drop_console: true, drop_debugger: true } },
    },
    plugins: [
      vue(),
      tailwindcss(),
      AutoImport({
        imports: ['vue', 'vue-router', 'pinia', '@vueuse/core'],
        dts: 'src/types/import/auto-imports.d.ts',
        resolvers: [ElementPlusResolver()],
        eslintrc: { enabled: true, filepath: './.auto-import.json', globalsPropValue: true }
      }),
      Components({ dts: 'src/types/import/components.d.ts', resolvers: [ElementPlusResolver()] }),
      ElementPlus({ useSource: true }),
      viteCompression({ verbose: false, disable: false, algorithm: 'gzip', ext: '.gz', threshold: 10240, deleteOriginFile: false }),
      // mockPlugin() 已停用：连接真实后端 (:8000)
    ],
    optimizeDeps: {
      include: ['echarts/core','echarts/charts','echarts/components','echarts/renderers','element-plus/es','element-plus/es/components/*/style/css']
    },
    css: {
      preprocessorOptions: { scss: { additionalData: `` } },
      postcss: { plugins: [{ postcssPlugin:'internal:charset-removal', AtRule:{ charset:(atRule:any)=>{ if(atRule.name==='charset') atRule.remove() } } }] }
    }
  })
}

function resolvePath(paths: string) { return path.resolve(__dirname, paths) }
