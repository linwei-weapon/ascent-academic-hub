"""API 层通用清洗：教师职称/部门脏串归一（与 ETL synth_business.norm_title 一致）。
真实 dim_teacher.title 为脏串（"教授;副教授;工程师"/"未知"/"研究员（自然科学）"），
dept 可含重复段（"机械与储运工程学院;机械与储运工程学院"）或为空。
"""

_TITLE_RANK = {"教授": 4, "副教授": 3, "讲师": 2, "助教": 1, "其他": 0}
TEACHER_LOAD_ANOMALY_LIMITS = {"classes": 200, "hours": 1000, "courses": 20}


def teacher_load_anomaly_reasons(classes=0, hours=0, courses=0) -> list[str]:
    """教师负荷启发式异常原因；页面统计与AI研判必须共用。"""
    values = {
        "教学班数": (classes or 0, TEACHER_LOAD_ANOMALY_LIMITS["classes"]),
        "学时": (hours or 0, TEACHER_LOAD_ANOMALY_LIMITS["hours"]),
        "课程数": (courses or 0, TEACHER_LOAD_ANOMALY_LIMITS["courses"]),
    }
    return [
        f"{label} {value:g} 超过阈值 {limit}"
        for label, (value, limit) in values.items()
        if value > limit
    ]


def is_teacher_load_anomaly(classes=0, hours=0, courses=0) -> bool:
    return bool(teacher_load_anomaly_reasons(classes, hours, courses))


def normalize_title(raw) -> str:
    """脏职称串 → 5 档（教授/副教授/讲师/助教/其他），取最高。"""
    s = str(raw or "")
    best = 0
    for tok in s.replace("；", ";").split(";"):
        if "副教授" in tok or "副研究员" in tok:
            r = 3
        elif "教授" in tok or ("研究员" in tok and "助理" not in tok):
            r = 4
        elif "讲师" in tok or "工程师" in tok or "实验师" in tok or "助理研究员" in tok:
            r = 2
        elif "助教" in tok:
            r = 1
        else:
            r = 0
        best = max(best, r)
    for name, rk in _TITLE_RANK.items():
        if rk == best:
            return name
    return "其他"


def clean_dept(raw) -> str | None:
    """部门脏串取首段（去重复尾），空值→None。"""
    s = str(raw or "").replace("；", ";").split(";")[0].strip()
    return s or None
