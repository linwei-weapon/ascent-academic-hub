"""抽取 extract：从脱敏 Excel 读原始数据为 DataFrame。
- 成绩 236MB → openpyxl read_only 流式（数据字典实测全量约 39s）。
- 教学任务 .xls → xlrd。
"""
import openpyxl
import pandas as pd
import xlrd

from . import config


def read_grades(path=None, limit=None) -> pd.DataFrame:
    """流式读成绩表全量（或 limit 行抽样）→ DataFrame，列为中文表头。"""
    path = path or config.GRADE_XLSX
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = list(next(rows_iter))
    data = []
    for i, row in enumerate(rows_iter):
        if limit is not None and i >= limit:
            break
        data.append(row)
    wb.close()
    return pd.DataFrame(data, columns=header)


def read_tasks(path=None) -> pd.DataFrame:
    """读教学任务 .xls → DataFrame。"""
    path = path or config.TASK_XLS
    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    header = [str(v) for v in sheet.row_values(0)]
    data = [sheet.row_values(r) for r in range(1, sheet.nrows)]
    return pd.DataFrame(data, columns=header)


if __name__ == "__main__":
    import time
    t = time.time()
    g = read_grades(limit=2000)
    print(f"成绩抽样 {len(g)} 行 / {len(g.columns)} 列  ({time.time()-t:.1f}s)")
    print("学期枚举:", sorted(g['学期'].dropna().unique().tolist()))
    print("管理部门枚举:", sorted(g['管理部门'].dropna().unique().tolist()))
    t = time.time()
    tk = read_tasks()
    print(f"教学任务 {len(tk)} 行 / {len(tk.columns)} 列  ({time.time()-t:.1f}s)")
