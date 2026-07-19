"""角色动作权限目录。角色只定义能力上限，数据对象仍由权限上下文限制。"""

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
