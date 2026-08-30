import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


class ScheduleChangesUiContractTest(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (FRONTEND / relative_path).read_text(encoding="utf-8")

    def test_teacher_top_uses_non_stretched_side_stack(self):
        page = self.read("views/admin/operation/ScheduleChanges.vue")
        self.assertIn('class="schedule-side-stack"', page)
        self.assertIn(".schedule-side-stack {", page)

    def test_data_table_explicitly_forwards_row_click(self):
        table = self.read("components/DataTable.vue")
        self.assertIn("(e: 'row-click'", table)
        self.assertIn('@row-click="forwardRowClick"', table)

    def test_teacher_row_opens_reason_drawer(self):
        page = self.read("views/admin/operation/ScheduleChanges.vue")
        self.assertIn('@row-click="inspectTeacher"', page)
        self.assertIn('v-model="teacherDrawer"', page)
        self.assertIn("selectedTeacher.value = row", page)

    def test_teacher_top_copy_and_reason_drawer_copy(self):
        page = self.read("views/admin/operation/ScheduleChanges.vue")
        self.assertIn("教师调停课 TOP10", page)
        self.assertNotIn("本学期 ≥ 3 次 · 点击核查原因", page)
        self.assertIn(
            "统计每位教师的调停课事件总次数，进入列表条件为总次数 `≥3`；最多 10 人",
            page,
        )
        self.assertIn("'重点关注':'需关注'", page)
        self.assertNotIn("'AI重点':'需核查'", page)
        self.assertIn("调课原因信息", page)
        self.assertNotIn("语义分类仅用于汇总管理原因，核查时必须查看原始原因文本。", page)
        self.assertIn("查看调课研判", page)
        self.assertNotIn("查看 AI 调课研判", page)


if __name__ == "__main__":
    unittest.main()
