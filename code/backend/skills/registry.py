"""Skill 注册表：数据驱动，Skill 数量由数据可支撑的管理问题决定。"""
from __future__ import annotations

from .alert_priority import AlertPrioritySkill
from .course_quality import CourseQualitySkill
from .faculty_structure import FacultyStructureSkill
from .graduation_gap import GraduationGapSkill

SKILLS: dict[str, type] = {
    GraduationGapSkill.skill_id: GraduationGapSkill,
    CourseQualitySkill.skill_id: CourseQualitySkill,
    AlertPrioritySkill.skill_id: AlertPrioritySkill,
    FacultyStructureSkill.skill_id: FacultyStructureSkill,
}


def list_skills() -> list:
    return [cls() for cls in SKILLS.values()]


def get_skill(skill_id: str):
    cls = SKILLS.get(skill_id)
    return cls() if cls else None
