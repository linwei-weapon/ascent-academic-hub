"""V2 数据源登记与字段白名单。

只声明允许进入分析链路的业务字段类别，不复制原始文件。提取器必须拒绝未登记字段，
尤其不能把证件号、银行卡、电话、地址和家庭联系人写入 V2 库。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    code: str
    filename: str
    target: str
    key_fields: tuple[str, ...]
    allowed_fields: tuple[str, ...]
    required: bool = True


SOURCES = (
    SourceSpec("semester", "学年学期.xlsx", "stg_semester", ("学年学期代码",),
               ("学年学期代码", "学年学期名称", "学年", "学期", "开始日期", "结束日期", "状态")),
    SourceSpec("organization", "组织机构.xlsx", "stg_organization", ("组织机构代码",),
               ("组织机构代码", "组织机构名称", "上级组织机构代码", "组织机构类型", "状态")),
    SourceSpec("course", "课程信息.xlsx", "stg_course", ("课程代码",),
               ("课程代码", "课程名称", "课程类别", "课程性质", "学分", "总学时", "理论学时", "实验学时", "实践学时", "考核方式", "开课部门", "状态")),
    SourceSpec("student_current", "学籍信息.xlsx", "stg_student", ("学号",),
               ("学号", "姓名", "性别", "入学年级", "培养层次", "学院", "专业", "行政班", "培养方案", "学籍状态", "预计毕业日期")),
    SourceSpec("student_history", "学籍信息-2021级往届学生.xlsx", "stg_student", ("学号",),
               ("学号", "姓名", "性别", "入学年级", "培养层次", "学院", "专业", "行政班", "培养方案", "学籍状态", "毕业状态", "学位状态", "毕业日期")),
    SourceSpec("plan_course", "专业方案全部计划课程 (1).xlsx", "stg_plan_course", ("培养方案", "课程代码"),
               ("培养方案", "年级", "专业", "课程代码", "课程名称", "课程模块", "课程性质", "学分", "总学时", "建议修读学期", "开课学期")),
    SourceSpec("grade", "2021级学生成绩.xlsx", "stg_grade_attempt", ("学号", "课程代码", "学年学期"),
               ("学号", "课程代码", "课程名称", "教学班代码", "学年学期", "教师工号", "教师姓名", "成绩", "等级", "绩点", "是否通过", "是否重修", "补考成绩", "缓考成绩", "发布状态", "备注")),
    SourceSpec("substitution", "课程替代.xlsx", "stg_course_substitution", ("学号", "原课程代码", "替代课程代码"),
               ("学号", "原课程代码", "原课程名称", "替代课程代码", "替代课程名称", "认定学分", "审核状态", "审核时间")),
    SourceSpec("building", "楼宇.xlsx", "stg_building", ("楼宇代码",),
               ("楼宇代码", "楼宇名称", "校区", "状态")),
    SourceSpec("room", "房间.xlsx", "stg_room", ("房间代码",),
               ("房间代码", "房间名称", "楼宇代码", "楼宇名称", "房间类型", "座位数", "是否可用", "是否虚拟", "状态")),
    SourceSpec("period", "课表时间.xlsx", "stg_period", ("节次代码",),
               ("节次代码", "节次名称", "大节", "开始时间", "结束时间")),
    SourceSpec("class_adviser", "行政班班主任.xlsx", "stg_staff_student_scope", ("行政班", "教师工号"),
               ("行政班", "教师工号", "教师姓名", "关系类型", "开始日期", "结束日期")),
    SourceSpec("student_adviser", "学生导师库.xls", "stg_staff_student_scope", ("学号", "教师工号"),
               ("学号", "教师工号", "教师姓名", "关系类型", "开始日期", "结束日期")),
    SourceSpec("lesson", "教学任务-历史学期.xls", "stg_lesson", ("教学班代码", "学年学期"),
               ("教学班代码", "学年学期", "课程代码", "课程名称", "开课部门", "教师工号", "教师姓名", "教学时间", "教学地点", "容量", "选课人数")),
)

FORBIDDEN_FIELD_TOKENS = (
    "身份证", "证件号", "银行卡", "银行账号", "手机号", "手机号码", "联系电话",
    "家庭地址", "通讯地址", "邮政编码", "紧急联系人", "父亲", "母亲",
)


def source_by_code(code: str) -> SourceSpec:
    return next(item for item in SOURCES if item.code == code)


def validate_selected_fields(code: str, fields: list[str]) -> None:
    """在读取数据前校验字段；发现敏感或白名单外字段立即失败。"""
    spec = source_by_code(code)
    blocked = [f for f in fields if any(token in f for token in FORBIDDEN_FIELD_TOKENS)]
    unknown = [f for f in fields if f not in spec.allowed_fields]
    if blocked:
        raise ValueError(f"{code} 包含禁止字段: {blocked}")
    if unknown:
        raise ValueError(f"{code} 包含白名单外字段: {unknown}")
