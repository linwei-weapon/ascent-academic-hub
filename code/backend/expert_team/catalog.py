"""Business-facing experts and bounded scenarios, independent of Skill registry."""

EXPERTS = [
    {"id": "program", "name": "专业建设专家", "group": "建设与改进", "icon": "Collection",
     "purpose": "比较专业、课程重复与特色", "question": "选择一个专业，看看哪些专业最值得放在一起比较。",
     "scenarios": [("similarity", "相近专业", "找出培养结构最接近的专业"),
                   ("overlap", "课程重复", "查看共同课程与双方不同课程"),
                   ("features", "特色支撑", "对照培养目标与方案原文"),
                   ("sequence", "课程衔接", "查看专业内部课程安排"),
                   ("options", "调整讨论", "比较调整的条件与影响")]},
    {"id": "course", "name": "课程质量建设专家", "group": "建设与改进", "icon": "Reading",
     "purpose": "找准问题，研究建设重点", "question": "从课程表现入手，明确哪些问题值得进一步研究。",
     "scenarios": [("priority", "建设对象", "查看值得关注的课程"),
                   ("diagnosis", "问题分析", "区分问题表现与可能原因"),
                   ("alignment", "目标与考核", "对照教学与考核资料"),
                   ("options", "建设做法", "讨论不同改进做法"),
                   ("outcomes", "效果观察", "查看同一课程的学期变化")]},
    {"id": "transfer", "name": "转专业专家", "group": "培养与资格", "icon": "Switch",
     "purpose": "转入方向与后续培养衔接", "question": "先比较培养衔接，再讨论申请与接收条件。",
     "scenarios": [("paths", "衔接专业", "比较最多三个培养衔接对象"),
                   ("conditions", "申请条件", "查看所需规则与资料"),
                   ("recognition", "认定与补修", "区分已认定和待确认课程"),
                   ("capacity", "接收影响", "查看课程需求与安排限制"),
                   ("history", "历史异动", "查看授权范围内已发生的转专业情况")]},
    {"id": "recommendation", "name": "保研专家", "group": "培养与资格", "icon": "Medal",
     "purpose": "推免条件与准备差距", "question": "以当年度已确认的推免办法为准，逐项讨论条件。",
     "scenarios": [("conditions", "资格条件", "明确适用条件与资料"),
                   ("gaps", "准备差距", "区分可以准备与待认定事项"),
                   ("ranking", "排名解释", "对照课程、权重和并列规则"),
                   ("rules", "规则比较", "比较现行与讨论中的规则"),
                   ("targets", "接收要求", "区分校内推免与院校接收")]},
    {"id": "graduation", "name": "毕业资格审核专家", "group": "培养与资格", "icon": "Checked",
     "purpose": "审核准备与待解决事项", "question": "查看适用方案下的完成情况，不把资料缺失当作不符合。",
     "scenarios": [("readiness", "审核准备", "区分已知课程问题和资料缺口"),
                   ("conditions", "条件说明", "毕业条件和学位条件分别查看"),
                   ("bottlenecks", "共同课程", "查看集中影响的课程"),
                   ("records", "资料问题", "查看方案绑定及记录异常"),
                   ("changes", "前后变化", "保留规则与数据时点边界")]},
]


def catalog():
    return [{**x, "scenarios": [{"id": i, "name": n, "description": d}
                                for i, n, d in x["scenarios"]]} for x in EXPERTS]


def expert(expert_id):
    return next((x for x in catalog() if x["id"] == expert_id), None)
