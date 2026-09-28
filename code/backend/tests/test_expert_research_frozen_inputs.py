"""Frozen-input replay tests: synthetic writes and explicitly read-only live probes."""
import copy
import json
import sqlite3
import unittest
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch

from backend.api import settings
from backend.api.envelope import ApiError
from backend.expert_research import frozen_inputs, service
from backend.expert_team import analysis, course_quality, graduation
from backend.tests import test_expert_team_quality as fixtures


def assert_replay(test, frozen, live):
    replay = frozen_inputs.replay_graduation(frozen)
    for key in ('population', 'counts', 'courses'):
        test.assertEqual(replay[key], live['snapshot'][key])
    test.assertEqual(replay['modules'], live['modules'])
    test.assertEqual(replay['classes'], live['classes'])
    return replay


class FrozenInputTests(unittest.TestCase):
    plan = fixtures.ExpertQualityTests.plan
    course = fixtures.ExpertQualityTests.course
    student = fixtures.ExpertQualityTests.student
    grade = fixtures.ExpertQualityTests.grade
    progress = fixtures.ExpertQualityTests.progress
    course_status = fixtures.ExpertQualityTests.course_status
    analyze = fixtures.ExpertQualityTests.analyze
    tearDown = fixtures.ExpertQualityTests.tearDown

    def setUp(self):
        fixtures.ExpertQualityTests.setUp(self)
        self.v2.executescript('''CREATE TABLE dim_semester(semester_id,start_date,end_date);
            INSERT INTO dim_semester VALUES('Z-early','2024-09-01','2025-01-31');
            INSERT INTO dim_semester VALUES('A-late','2025-09-01','2026-01-31');''')

    def test_pure_graduation_replay_keeps_mutually_exclusive_student_counts(self):
        self.progress(); self.progress('s2', state='candidate')
        self.course_status(); self.course_status(status='not_completed')
        self.course_status('s2', status='unknown')
        # Duplicate joined course records must not duplicate a student's debt.
        self.course_status(); self.course_status('s2', status='not_completed')
        live = graduation.facts(self.v2, self.user, 'a')
        frozen = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        before = copy.deepcopy(frozen)
        with patch.object(analysis, 'rows', side_effect=AssertionError('replay queried source')):
            replay = assert_replay(self, json.loads(json.dumps(frozen)), live)
        self.assertEqual(replay['courses'], [{'course_id': 'base', 'failed': 1, 'pending': 1}])
        self.assertEqual(replay['population'], 2)
        self.assertEqual(frozen, before)

    def test_completed_choice_module_does_not_count_unused_course_as_debt(self):
        self.progress(complete=1, state='no_due_issue'); self.course_status()
        self.progress('s2', assessable=0, state='not_assessable'); self.course_status('s2')
        frozen = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        replay = assert_replay(self, frozen, graduation.facts(self.v2, self.user, 'a'))
        self.assertEqual(replay['courses'], [])
        self.assertEqual(replay['counts']['rule_gap'], 1)

    def test_old_progress_and_wrong_plan_grade_remain_separate_unknowns(self):
        self.progress(version='old-growth'); self.course_status()
        self.progress('s2'); self.course_status('s2')
        self.v2.execute("UPDATE dim_student SET entry_grade=2021 WHERE student_id='s2'")
        frozen = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        replay = assert_replay(self, frozen, graduation.facts(self.v2, self.user, 'a'))
        self.assertEqual(replay['counts']['unknown'], 1)
        self.assertEqual(replay['counts']['binding_issue'], 1)
        self.assertEqual(replay['courses'], [])

    def test_frozen_replay_survives_later_source_changes(self):
        self.progress(); self.course_status()
        frozen = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        original = frozen_inputs.replay_graduation(frozen)
        self.v2.execute("UPDATE student_plan_progress_summary SET evidence_status='no_due_issue'")
        self.v2.execute('UPDATE student_plan_module_status SET is_complete=1')
        current = graduation.facts(self.v2, self.user, 'a')
        self.assertNotEqual(original['counts'], current['snapshot']['counts'])
        self.assertEqual(frozen_inputs.replay_graduation(frozen), original)

    def test_join_keys_are_per_bundle_and_do_not_retain_names_or_student_ids(self):
        self.progress(); self.progress('s2'); self.course_status(); self.course_status('s2')
        first = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        second = frozen_inputs.graduation_inputs(self.v2, self.user, 'a')
        encoded = json.dumps(first, ensure_ascii=False)
        for forbidden in ('student_id', 'display_name', '测试学生', '"s1"', '"s2"', 'salt'):
            self.assertNotIn(forbidden, encoded)
        keys = lambda data, group: {row['subject_key'] for row in data[group]}
        self.assertEqual(keys(first, 'progress'), keys(first, 'modules'))
        self.assertEqual(keys(first, 'progress'), keys(first, 'courses'))
        self.assertTrue(keys(first, 'progress').isdisjoint(keys(second, 'progress')))
        self.assertEqual(frozen_inputs.replay_graduation(first), frozen_inputs.replay_graduation(second))

    def test_missing_permission_scope_is_not_all_students(self):
        denied = copy.deepcopy(self.user); denied['permission_context']['detailScope'] = {}
        with self.assertRaises(ApiError):
            frozen_inputs.graduation_inputs(self.v2, denied, 'a')

    def test_graduation_bundle_rejects_changed_snapshot_counts(self):
        self.progress(); self.course_status()
        result = self.analyze('graduation', 'readiness')
        result['scope'] = {'plan_id': 'a', 'expert_id': 'graduation', 'scenario': 'readiness'}
        bundle = service.freeze_sources(self.v2, self.team, self.user, result['scope'], [result])
        self.assertEqual(len(bundle['calculation_inputs']), 1)
        result['snapshot']['counts']['explicit_gap'] += 1
        with self.assertRaises(ApiError) as error:
            service.freeze_sources(self.v2, self.team, self.user, result['scope'], [result])
        self.assertEqual(error.exception.status_code, 409)

    def test_course_aggregates_support_replay_without_student_detail_or_source_access(self):
        self.grade('private-grade-a', term='Z-early', passed=1)
        self.grade('private-grade-b', term='A-late')
        self.grade('private-grade-c', sid='s2', term='A-late', passed=1)
        self.grade('private-retake', term='A-late', kind='retake')
        scope = {'plan_id': 'a', 'expert_id': 'course', 'scenario': 'diagnosis',
                 'semester': 'A-late', 'course_id': 'base', '_semester_order': course_quality.calendar_order(self.v2)}
        original = analysis.analyze(self.v2, self.team, self.user, scope)
        original['scope'] = scope
        bundle = service.freeze_sources(self.v2, self.team, self.user, scope, [original])
        data = bundle['calculation_inputs'][0]
        encoded = json.dumps(data, ensure_ascii=False)
        for forbidden in ('student_id', 'display_name', 'private-grade', 'private-retake', '测试学生'):
            self.assertNotIn(forbidden, encoded)
        current = next(row for row in data['history'] if row['semester'] == 'A-late')
        self.assertEqual((current['attempts'], current['fails'], current['students']), (2, 1, 2))
        frozen_copy = copy.deepcopy(data)
        replay = {'methods': [], 'limitations': [], 'missing': [], 'tables': []}
        with patch.object(course_quality, 'history', return_value=copy.deepcopy(data['history'])), \
                patch.object(course_quality, 'class_distribution', return_value=copy.deepcopy(data['classes'])), \
                patch.object(analysis, 'assert_plan', return_value={'major_name': '甲'}), \
                patch.object(analysis, 'courses', return_value=copy.deepcopy(bundle['plans'][0]['normalized_courses'])):
            course_quality.analyze(None, None, self.user, {**scope, '_semester_order': data['calendar']}, replay)
        self.assertEqual(replay['tables'], original['tables'])
        self.assertEqual(data, frozen_copy)


class RealSourceReplayTests(unittest.TestCase):
    """These tests never migrate or open the configured school source writable."""
    def setUp(self):
        target = Path(settings.V2_DB_PATH)
        if not target.is_file():
            self.skipTest('configured read-only V2 source is not present')
        self.conn = sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute('PRAGMA query_only=ON')
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                   sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_RECURSIVE}
        self.conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        self.conn.execute('BEGIN')
        self.user = fixtures.user('director')

    def test_actual_graduation_source_replays_in_one_read_only_transaction(self):
        plans = self.conn.execute("""SELECT DISTINCT p.plan_id FROM curriculum_plan p
            JOIN dim_student s ON s.plan_id=p.plan_id
            JOIN student_plan_progress_summary ps ON ps.student_id=s.student_id AND ps.plan_id=s.plan_id
            WHERE p.source='real' AND s.source IN ('real','real_legacy') AND s.student_status='在校'
            ORDER BY p.plan_id LIMIT 3""").fetchall()
        self.assertTrue(plans, 'real-source probe needs at least one applicable plan')
        for index, row in enumerate(plans):
            with self.subTest(sample=index):
                live = graduation.facts(self.conn, self.user, row[0])
                frozen = frozen_inputs.graduation_inputs(self.conn, self.user, row[0])
                assert_replay(self, json.loads(json.dumps(frozen)), live)
                self.assertGreater(len(frozen['progress']), 0)
                self.assertNotIn('student_id', json.dumps(frozen))
                self.assertNotIn('display_name', json.dumps(frozen))
        self.assertEqual(self.conn.total_changes, 0)
        self.assertTrue(self.conn.in_transaction)

    def test_actual_course_aggregates_recompute_rates_without_individual_records(self):
        selected = self.conn.execute("""SELECT s.plan_id FROM grade_attempt g
            JOIN dim_student s ON s.student_id=g.student_id
            JOIN curriculum_plan p ON p.plan_id=s.plan_id
            WHERE p.source='real' AND """ + course_quality.VALID_FIRST + " LIMIT 1").fetchone()
        self.assertIsNotNone(selected, 'real-source probe needs usable first-attempt records')
        rows = course_quality.history(self.conn, self.user, selected[0])
        self.assertTrue(rows)
        for row in rows:
            # Existing SQLite ROUND rounds a positive half away from zero;
            # Python's built-in round uses ties-to-even and is not equivalent.
            rate = (Decimal(100) * row['fails'] / row['attempts']).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            self.assertEqual(row['fail_rate'], float(rate))
            self.assertLessEqual(row['failed_students'], row['students'])
            self.assertLessEqual(row['students'], row['attempts'])
            self.assertNotIn('student_id', row)
        self.assertEqual(self.conn.total_changes, 0)


if __name__ == '__main__':
    unittest.main()
