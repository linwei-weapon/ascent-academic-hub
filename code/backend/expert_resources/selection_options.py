"""Authorized UI selections, separate from versioned business calculations."""
from backend.metric_verification.database import connection
from .runtime import now, rows, scope_sql


def course_options(actor, semester_id, college_id=None):
    where, params = scope_sql(actor, 'c.organization_id', college_id)
    with connection('analytics', consistent=True) as db:
        courses = rows(db, f'''SELECT DISTINCT a.course_id id,
            COALESCE(NULLIF(a.course_name,''),c.name,a.course_id) name,
            c.organization_id college_id
            FROM agg_course_pass_stat a JOIN act_course c ON c.course_id=a.course_id
            WHERE a.semester_id=%s AND {where} AND a.course_id IS NOT NULL AND a.course_id<>''
            ORDER BY name,id''', [semester_id, *params])
    return {'items': courses, 'semesterId': semester_id, 'queriedAt': now(),
            'note': '仅列所选学期及授权开课院系已有统计的课程；选项不改变分析口径。'}
