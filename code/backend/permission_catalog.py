"""角色动作权限目录。角色只定义能力上限，数据对象仍由权限上下文限制。"""

ACTION_CATALOG = {
    "student.detail": ("业务数据", "查看学生明细", "读取授权范围内学生档案与成绩明细"),
    "college.compare": ("业务数据", "查看跨学院聚合对比", "只能查看满足最小群体规模的聚合结果"),
    "export.authorized": ("业务数据", "导出授权范围数据", "导出时仍按当前工作身份重新鉴权"),
    "ai.analyze": ("AI管理决策", "运行AI研判", "在授权数据范围内运行管理专家和情景测算"),
    "system.manage": ("系统管理", "进入系统管理", "读取并维护系统管理配置"),
    "rbac.manage": ("系统管理", "维护账号角色菜单", "账号、角色、菜单和动作权限配置"),
    "permission.manage": ("系统管理", "维护数据权限", "工作身份、人员关联和组织范围配置"),
    "definition.manage": ("系统管理", "维护指标与分析方案", "发布指标展示配置和学校分析方案"),
    "operation.quality.manage": ("教学运行", "维护教学运行质量核查", "处理教学运行数据质量核查事项"),
    "alert.event.manage_all": ("学业预警", "管理全校预警事件", "查看与管理全校授权范围内预警事件"),
    "curriculum.governance.edit": ("培养质量", "编辑培养质量治理配置", "创建培养质量治理变更"),
    "curriculum.governance.review": ("培养质量", "审核培养质量治理配置", "复核培养质量治理变更"),
    "curriculum.governance.activate": ("培养质量", "激活培养质量治理配置", "激活已审批治理版本"),
    "curriculum.governance.audit": ("培养质量", "查看培养质量治理记录", "查看治理版本和审计证据"),
    "rule.discovery.manage": ("学业预警", "管理规则自发现", "运行规则发现并创建候选变更"),
}

ROLE_ACTIONS = {
    "school_leader": {
        "student.detail", "college.compare", "export.authorized", "ai.analyze",
        "curriculum.governance.activate", "curriculum.governance.audit",
    },
    "dean": {
        "student.detail", "college.compare", "export.authorized", "ai.analyze",
        "system.manage", "rbac.manage", "permission.manage", "definition.manage",
        "operation.quality.manage", "alert.event.manage_all",
        "curriculum.governance.edit", "curriculum.governance.audit",
        "rule.discovery.manage",
    },
    "dept_operation": {
        "student.detail", "college.compare", "export.authorized",
        "operation.quality.manage",
    },
    "dept_research": {
        "student.detail", "college.compare", "export.authorized", "ai.analyze",
        "curriculum.governance.edit", "curriculum.governance.audit",
    },
    "dept_practice": {"student.detail", "college.compare", "export.authorized", "ai.analyze"},
    "quality_office": {
        "student.detail", "college.compare", "export.authorized", "ai.analyze",
        "curriculum.governance.review", "curriculum.governance.audit",
    },
    "college_dean": {"student.detail", "college.compare", "export.authorized", "ai.analyze"},
    "college_secretary": {"student.detail", "college.compare", "export.authorized", "ai.analyze"},
    "counselor": {"student.detail", "export.authorized"},
    "dept_director": {"student.detail", "college.compare", "export.authorized"},
    "teacher": {"student.detail"},
    "class_adviser": {"student.detail"},
    "mentor": {"student.detail"},
}
