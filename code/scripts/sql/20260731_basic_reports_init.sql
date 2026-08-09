-- 基础报表控制数据初始化（SQLite，幂等）。
-- 说明：不创建、不修改任何业务事实表；完整角色授权和指标绑定由
-- code/scripts/migrate_basic_reports.py 编排，本文件供迁移审查和最小初始化。
BEGIN IMMEDIATE;

INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order)
VALUES('/admin/basic-reports',NULL,'基础报表','/admin/basic-reports','Tickets',3)
ON CONFLICT(menu_id) DO UPDATE SET title=excluded.title,path=excluded.path,icon=excluded.icon,sort_order=excluded.sort_order;
UPDATE sys_menu SET sort_order=4 WHERE menu_id='/admin/system';
UPDATE sys_menu SET sort_order=sort_order+100
WHERE parent_id='/admin/system' AND sort_order BETWEEN 301 AND 309;

INSERT INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order) VALUES
 ('/admin/basic-reports/failure-overview','/admin/basic-reports','入学年级总体挂科情况','/admin/basic-reports/failure-overview','DataBoard',301),
 ('/admin/basic-reports/major-makeup-comparison','/admin/basic-reports','各专业补考前后挂科率比较','/admin/basic-reports/major-makeup-comparison','TrendCharts',302),
 ('/admin/basic-reports/major-gender-failure','/admin/basic-reports','各专业整体与男女挂科率比较','/admin/basic-reports/major-gender-failure','DataAnalysis',303),
 ('/admin/basic-reports/class-failure-count','/admin/basic-reports','各班级挂科门数具体情况','/admin/basic-reports/class-failure-count','Histogram',304),
 ('/admin/basic-reports/class-score-distribution','/admin/basic-reports','各班级成绩分布','/admin/basic-reports/class-score-distribution','PieChart',305),
 ('/admin/basic-reports/course-makeup-comparison','/admin/basic-reports','补考前后课程通过情况对比','/admin/basic-reports/course-makeup-comparison','Finished',306),
 ('/admin/basic-reports/cet4-pass','/admin/basic-reports','各班大学英语四级通过情况','/admin/basic-reports/cet4-pass','Reading',307),
 ('/admin/basic-reports/focus-students','/admin/basic-reports','重点关注学生名单','/admin/basic-reports/focus-students','Warning',308),
 ('/admin/basic-reports/academic-warning-roster','/admin/basic-reports','校级学业警示学生名单','/admin/basic-reports/academic-warning-roster','Bell',309)
ON CONFLICT(menu_id) DO UPDATE SET parent_id=excluded.parent_id,title=excluded.title,
 path=excluded.path,icon=excluded.icon,sort_order=excluded.sort_order;

WITH eligible_roles(role_id) AS (VALUES
 ('school_leader'),('dean'),('dept_operation'),('dept_research'),('dept_practice'),
 ('quality_office'),('college_dean'),('college_secretary'),('dept_director'),
 ('counselor'),('class_adviser'),('mentor')
), report_menus(menu_id) AS (VALUES
 ('/admin/basic-reports/failure-overview'),('/admin/basic-reports/major-makeup-comparison'),
 ('/admin/basic-reports/major-gender-failure'),('/admin/basic-reports/class-failure-count'),
 ('/admin/basic-reports/class-score-distribution'),('/admin/basic-reports/course-makeup-comparison'),
 ('/admin/basic-reports/cet4-pass'),('/admin/basic-reports/focus-students'),
 ('/admin/basic-reports/academic-warning-roster')
)
INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id)
SELECT r.role_id,m.menu_id FROM eligible_roles r CROSS JOIN report_menus m
WHERE (r.role_id NOT IN ('counselor','class_adviser','mentor'))
   OR (r.role_id IN ('counselor','class_adviser') AND m.menu_id<>'/admin/basic-reports/major-makeup-comparison')
   OR (r.role_id='mentor' AND m.menu_id IN (
       '/admin/basic-reports/failure-overview','/admin/basic-reports/focus-students',
       '/admin/basic-reports/academic-warning-roster'));

INSERT INTO sys_system_parameter(parameter_key,category,name,value_json,value_type,description,editable,options_json)
VALUES
 ('basic_reports.rule_version','基础报表','基础报表口径版本','"basic-report-v1.4"','string','九张基础报表查询时计算规则版本；v1.4同步RPT-02专业人数、补考前后挂科学生数、留降级括号人数及学生通过率口径。',0,'[]'),
 ('basic_reports.cet4_source_mode','基础报表','四级报表来源模式','"cumulative_as_of_semester"','string','查询时读取截至所选学期的 external_exams 明细，按通过学生去重动态累计；不生成或保存统计快照。',0,'[]'),
 ('basic_reports.official_warning_source','基础报表','校级学业警示名单来源','"source_unavailable"','string','未接入正式名单时禁止使用系统推导预警冒充。',0,'[]')
ON CONFLICT(parameter_key) DO UPDATE SET value_json=excluded.value_json,description=excluded.description,
 updated_at=datetime('now','localtime'),version=sys_system_parameter.version+1;

COMMIT;
