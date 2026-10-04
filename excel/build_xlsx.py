"""生成《投资决策看板.xlsx》：配置总览/定投计划/估值跟踪/信号面板/持仓记录/月度清单/Review。

估值与信号预填引擎当前真实输出；其余为活公式模板，蓝色字体=手动输入项。
用法：python excel/build_xlsx.py（在项目根目录运行）
"""
import sys
from datetime import date

SKILL = r"C:\Users\31297\.zcode\cli\plugins\cache\zcode-plugins-official\spreadsheets\0.1.7\skills\xlsx"
for p in (SKILL, SKILL + r"\templates"):
    if p not in sys.path:
        sys.path.insert(0, p)

import base  # noqa: E402
base.use_palette_explicit("bloomberg")
from base import (FONT_NAME, HEADER_BOLD, PRIMARY, ACCENT_POSITIVE, ACCENT_NEGATIVE,  # noqa: E402
                  ACCENT_WARNING, NEUTRAL_600, NEUTRAL_900,
                  setup_sheet, style_header_row, style_data_row, style_total_row,
                  auto_fit_columns, auto_fit_row_heights, font_caption)
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Font, Alignment  # noqa: E402
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

sys.path.insert(0, ".")
from src.engine import scorer  # noqa: E402
from src import universe  # noqa: E402

INPUT_FONT = Font(name=FONT_NAME, size=11, color="0000FF")   # 蓝=手动输入
LINK_FONT = Font(name=FONT_NAME, size=11, color="008000")    # 绿=跨表引用
PCT, MONEY, NUM1 = '0.0%', '¥#,##0', '0.0'

sigs = scorer.score_all()
plan = scorer.build_plan(sigs)
sig_by = {s.key: s for s in sigs}

wb = Workbook()
wb.properties.creator = "Z.ai"


def write_headers(ws, headers, row=4):
    for i, h in enumerate(headers, start=2):
        ws.cell(row=row, column=i, value=h)
    style_header_row(ws, row_num=row, col_start=2, col_end=len(headers) + 1)


def caption(ws, row, text):
    c = ws.cell(row=row, column=2, value=text)
    c.font = font_caption()


# ============================================================ 1 配置总览
ws = wb.active
ws.title = "配置总览"
headers = ["资产", "角色", "目标权重", "当前市值(输入)", "当前权重", "偏离(pp)", "调仓金额", "触发再平衡"]
last_col = len(headers) + 1
setup_sheet(ws, title="资产配置与再平衡计算器", last_col=last_col)
write_headers(ws, headers)
assets_order = [a for a in universe.ASSETS if plan["weights"].get(a.key, 0) > 0 or a.role == "core"]
assets_order = sorted(assets_order, key=lambda a: -plan["weights"].get(a.key, 0))
r0 = 5
for i, a in enumerate(assets_order):
    r = r0 + i
    tw = plan["weights"].get(a.key, 0) / 100
    ws.cell(row=r, column=2, value=a.name)
    ws.cell(row=r, column=3, value={"core": "核心", "defensive": "防守", "industry": "行业卫星",
                                    "region": "国别卫星", "cash": "现金"}[a.role])
    ws.cell(row=r, column=4, value=tw).number_format = PCT
    ws.cell(row=r, column=5, value=None).number_format = MONEY      # 手动输入
    ws.cell(row=r, column=6, value=f"=IF(E{r}=\"\",\"\",E{r}/$E${r0 + len(assets_order)})").number_format = PCT
    ws.cell(row=r, column=7, value=f"=IF(F{r}=\"\",\"\",(F{r}-D{r})*100)").number_format = NUM1
    ws.cell(row=r, column=8, value=f"=IF(F{r}=\"\",\"\",D{r}*$E${r0 + len(assets_order)}-E{r})").number_format = MONEY
    ws.cell(row=r, column=9, value=f"=IF(F{r}=\"\",\"\",IF(ABS(G{r})>=5,\"触发\",\"—\"))")
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
    ws.cell(row=r, column=5).font = INPUT_FONT
    for c in (6, 7, 8):
        ws.cell(row=r, column=c).alignment = Alignment(horizontal="right", vertical="center")
tr = r0 + len(assets_order)
ws.cell(row=tr, column=2, value="合计")
ws.cell(row=tr, column=4, value=f"=SUM(D{r0}:D{tr - 1})").number_format = PCT
ws.cell(row=tr, column=5, value=f"=SUM(E{r0}:E{tr - 1})").number_format = MONEY
style_total_row(ws, row_num=tr, col_start=2, col_end=last_col)
ws.freeze_panes = "C5"
ws.conditional_formatting.add(f"G{r0}:G{tr - 1}",
    CellIsRule(operator="greaterThan", formula=["5"], font=Font(color=ACCENT_WARNING)))
ws.conditional_formatting.add(f"G{r0}:G{tr - 1}",
    CellIsRule(operator="lessThan", formula=["-5"], font=Font(color=ACCENT_WARNING)))
ws.conditional_formatting.add(f"I{r0}:I{tr - 1}",
    CellIsRule(operator="equal", formula=['"触发"'],
               font=Font(color=ACCENT_WARNING)))
caption(ws, tr + 2, "使用：每月/每季把各资产最新市值填入蓝色列 → 当前权重、偏离与调仓金额自动计算；偏离≥±5pp 即触发再平衡。")
caption(ws, tr + 3, "调仓优先用新定投资金『只买不卖』实现；卖出优先卖超配的卫星仓。")
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 2 定投计划
ws = wb.create_sheet("定投计划")
headers = ["资产", "目标权重", "基准月投额", "估值分位(输入)", "定投倍数", "实际定投额"]
last_col = len(headers) + 1
setup_sheet(ws, title="估值加权定投计划", last_col=last_col)
ws.cell(row=2, column=6, value=None)
# 月投总额输入
ws.cell(row=3, column=2, value="每月定投总额(输入)").font = Font(name=FONT_NAME, size=11, color=NEUTRAL_600)
ws.cell(row=3, column=3, value=10000).number_format = MONEY
ws.cell(row=3, column=3).font = INPUT_FONT
write_headers(ws, headers)
# 全部正权重资产进定投表：股票按估值倍数，债券/黄金/现金固定 1x（ Review 校验合计=月投总额）
dca_assets = [a for a in assets_order if plan["weights"].get(a.key, 0) > 0]
r0 = 5
for i, a in enumerate(dca_assets):
    r = r0 + i
    s = sig_by[a.key]
    ws.cell(row=r, column=2, value=a.name)
    ws.cell(row=r, column=3, value=f"='{ '配置总览' }'!D{5 + [x.key for x in assets_order].index(a.key)}").number_format = PCT
    ws.cell(row=r, column=3).font = LINK_FONT
    ws.cell(row=r, column=4, value=f"=C{r}*$C$3").number_format = MONEY
    ws.cell(row=r, column=5, value=(s.val_pct if s.val_pct is not None else None)).number_format = PCT
    ws.cell(row=r, column=5).font = INPUT_FONT
    ws.cell(row=r, column=6, value=(f"=IF(E{r}=\"\",1,IF(E{r}<0.2,2,IF(E{r}<0.4,1.5,"
                                    f"IF(E{r}<0.6,1,IF(E{r}<0.8,0.5,0)))))")).number_format = '0.0"x"'
    ws.cell(row=r, column=7, value=f"=D{r}*F{r}").number_format = MONEY
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
    ws.cell(row=r, column=5).font = INPUT_FONT
    ws.cell(row=r, column=3).font = LINK_FONT
tr = r0 + len(dca_assets)
ws.cell(row=tr, column=2, value="合计")
ws.cell(row=tr, column=4, value=f"=SUM(D{r0}:D{tr - 1})").number_format = MONEY
ws.cell(row=tr, column=7, value=f"=SUM(G{r0}:G{tr - 1})").number_format = MONEY
style_total_row(ws, row_num=tr, col_start=2, col_end=last_col)
ws.freeze_panes = "C5"
caption(ws, tr + 2, "定投倍数规则（股票资产）：<20%→2x｜20-40%→1.5x｜40-60%→1x｜60-80%→0.5x｜≥80%→停投(0x)；债券/黄金/现金固定 1x。")
caption(ws, tr + 3, "估值分位每月初从网站『估值温度』页复制更新（蓝色列），倍数与金额自动重算。")
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 3 估值跟踪
ws = wb.create_sheet("估值跟踪")
headers = ["资产", "指数代码", "估值口径", "当前PE", "历史分位", "估值区", "数据截至", "备注"]
last_col = len(headers) + 1
setup_sheet(ws, title="估值分位跟踪（近10年滚动）", last_col=last_col)
write_headers(ws, headers)
val_assets = [a for a in universe.ASSETS if a.valuation != "none" and a.key != "cash"]
r0 = 5
for i, a in enumerate(val_assets):
    r = r0 + i
    s = sig_by[a.key]
    label = {"pe_ttm": "PE-TTM", "shiller": "席勒PE", "price_fallback": "价格分位"}[a.valuation]
    ws.cell(row=r, column=2, value=a.name)
    ws.cell(row=r, column=3, value=a.ts_index or a.ts_global or a.etf)
    ws.cell(row=r, column=4, value=label)
    ws.cell(row=r, column=5, value=(s.flows_detail.get("current_pe") if False else None))
    ws.cell(row=r, column=5).number_format = NUM1
    ws.cell(row=r, column=6, value=s.val_pct).number_format = PCT
    ws.cell(row=r, column=7, value=f"=IF(F{r}=\"\",\"\",IF(F{r}<0.2,\"低估\",IF(F{r}<0.4,\"合理偏低\","
                                   f"IF(F{r}<0.6,\"合理\",IF(F{r}<0.8,\"合理偏高\",\"高估\")))))")
    ws.cell(row=r, column=8, value=s.last_date)
    note = "；".join(s.flags) if s.flags else ""
    ws.cell(row=r, column=9, value=note)
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
    ws.cell(row=r, column=5).font = INPUT_FONT
tr = r0 + len(val_assets)
ws.conditional_formatting.add(f"F{r0}:F{tr - 1}",
    ColorScaleRule(start_type="num", start_value=0, start_color="63BE7B",
                   mid_type="num", mid_value=0.5, mid_color="FFEB84",
                   end_type="num", end_value=1, end_color="F8696B"))
ws.freeze_panes = "C5"
caption(ws, tr + 2, "绿色=便宜(低分位)，红色=贵(高分位)。当前值预填自引擎最新输出，PE 列可从网站『估值温度』页核对更新。")
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 4 信号面板
ws = wb.create_sheet("信号面板")
headers = ["资产", "估值分", "趋势分", "资金分", "宏观分", "总分", "建议"]
last_col = len(headers) + 1
setup_sheet(ws, title="四维打分卡（0-100，估值40/趋势30/资金15/宏观15）", last_col=last_col)
write_headers(ws, headers)
score_assets = [s for s in sigs if s.role != "cash"]
r0 = 5
for i, s in enumerate(score_assets):
    r = r0 + i
    ws.cell(row=r, column=2, value=s.name)
    for j, v in enumerate([s.val_score, s.trend_score, s.flows_score, s.macro_score]):
        ws.cell(row=r, column=3 + j, value=v).number_format = NUM1
    total_f = (f"=IF(COUNT(C{r}:F{r})=0,\"—\",ROUND((IF(ISNUMBER(C{r}),C{r}*40,0)"
               f"+IF(ISNUMBER(D{r}),D{r}*30,0)+IF(ISNUMBER(E{r}),E{r}*15,0)"
               f"+IF(ISNUMBER(F{r}),F{r}*15,0))/(IF(ISNUMBER(C{r}),40,0)"
               f"+IF(ISNUMBER(D{r}),30,0)+IF(ISNUMBER(E{r}),15,0)"
               f"+IF(ISNUMBER(F{r}),15,0)),1))")
    ws.cell(row=r, column=7, value=total_f).number_format = NUM1
    ws.cell(row=r, column=8, value=(f"=IF(G{r}=\"—\",\"待补数据\",IF(G{r}>=65,\"偏多：按倍数定投/持有\","
                                    f"IF(G{r}<=40,\"偏空：控制仓位\",\"中性：按计划定投\")))"))
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
tr = r0 + len(score_assets)
ws.conditional_formatting.add(f"G{r0}:G{tr - 1}",
    DataBarRule(start_type="num", start_value=0, end_type="num", end_value=100,
                color=PRIMARY, showValue=True))
ws.freeze_panes = "C5"
caption(ws, tr + 2, "各维度分预填自引擎最新输出（每次刷新后可从网站复制更新）；总分为活公式，缺项自动归一。")
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 5 持仓记录
ws = wb.create_sheet("持仓记录")
headers = ["日期", "代码", "名称", "方向", "份额", "单价", "金额", "费率", "费用", "备注"]
last_col = len(headers) + 1
setup_sheet(ws, title="买卖流水", last_col=last_col)
write_headers(ws, headers)
samples = [
    (str(date.today()), "510300", "沪深300ETF", "买入", 10000, 4.10, 0.0003),
    (str(date.today()), "110020", "易方达沪深300联接A", "买入", 30000, 1.42, 0.0012),
]
r0 = 5
for i, (d, code, name, side, sh, px, fee) in enumerate(samples):
    r = r0 + i
    for j, v in enumerate([d, code, name, side, sh, px]):
        ws.cell(row=r, column=2 + j, value=v)
    ws.cell(row=r, column=8, value=f"=F{r}*G{r}").number_format = MONEY
    ws.cell(row=r, column=9, value=fee).number_format = '0.00%'
    ws.cell(row=r, column=9).font = INPUT_FONT
    ws.cell(row=r, column=10, value=f"=H{r}*I{r}").number_format = MONEY
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
for r in range(r0 + len(samples), r0 + 22):  # 预留空行（带公式）
    ws.cell(row=r, column=8, value=f"=IF(OR(F{r}=\"\",G{r}=\"\"),\"\",F{r}*G{r})").number_format = MONEY
    ws.cell(row=r, column=10, value=f"=IF(OR(H{r}=\"\",I{r}=\"\"),\"\",H{r}*I{r})").number_format = MONEY
tr = r0 + 22
ws.cell(row=tr, column=2, value="累计买入")
ws.cell(row=tr, column=8, value=f"=SUMIF(E{r0}:E{tr - 1},\"买入\",H{r0}:H{tr - 1})").number_format = MONEY
ws.cell(row=tr + 1, column=2, value="累计卖出")
ws.cell(row=tr + 1, column=8, value=f"=SUMIF(E{r0}:E{tr - 1},\"卖出\",H{r0}:H{tr - 1})").number_format = MONEY
style_total_row(ws, row_num=tr, col_start=2, col_end=last_col)
caption(ws, tr + 3, "方向列填『买入/卖出』；份额、单价、费率为蓝色输入列，金额与费用自动计算。")
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 6 月度清单
ws = wb.create_sheet("月度清单")
headers = ["频率", "事项", "对应工具", "完成(√)"]
last_col = len(headers) + 1
setup_sheet(ws, title="执行清单", last_col=last_col)
write_headers(ws, headers)
items = [
    ("每日", "看网站总览页有无红色预警（溢价/陈旧数据/回撤提醒），不交易", "网站-总览"),
    ("每月", "按当月估值分位更新定投倍数，执行定投", "定投计划 / 网站-当前策略"),
    ("每月", "检查行业卫星动量排名变化", "网站-趋势与动量"),
    ("每月", "录入本月买卖流水", "持仓记录"),
    ("每季", "更新各资产市值，跑再平衡计算器，偏离≥±5pp 执行调仓", "配置总览"),
    ("每季", "核对 QDII 溢价，超 3% 的品种暂停买入", "网站-资金面"),
    ("每年", "复核基金费率/规模/跟踪误差，必要时换同类替代", "基金筛选标准"),
    ("每年", "复盘：每笔交易是否对应手册规则，写 3 条改进", "策略手册"),
]
r0 = 5
for i, (freq, item, tool) in enumerate(items):
    r = r0 + i
    ws.cell(row=r, column=2, value=freq)
    ws.cell(row=r, column=3, value=item)
    ws.cell(row=r, column=4, value=tool)
    ws.cell(row=r, column=5, value="").font = INPUT_FONT
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
ws.conditional_formatting.add(f"E{r0}:E{r0 + len(items) - 1}",
    CellIsRule(operator="equal", formula=['"√"'], font=Font(color=ACCENT_POSITIVE)))
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ============================================================ 7 Review
ws = wb.create_sheet("Review")
ws.sheet_properties.tabColor = "FFC000"
headers = ["检查项", "期望", "实际", "状态"]
last_col = len(headers) + 1
setup_sheet(ws, title="交叉校验", last_col=last_col)
write_headers(ws, headers)
n_alloc = len(assets_order)
checks = [
    ("目标权重合计 = 100%", 1, f"=SUM(配置总览!D5:D{4 + n_alloc})"),
    ("定投基准合计 = 月投总额", "=定投计划!C3", f"=SUM(定投计划!D5:D{4 + len(dca_assets)})"),
    ("流水样本金额 = 份额×单价", f"=SUMPRODUCT(持仓记录!F5:F{4 + len(samples)},持仓记录!G5:G{4 + len(samples)})",
     f"=SUM(持仓记录!H5:H{4 + len(samples)})"),
]
r0 = 5
for i, (name, exp, act) in enumerate(checks):
    r = r0 + i
    ws.cell(row=r, column=2, value=name)
    ws.cell(row=r, column=3, value=exp)
    ws.cell(row=r, column=4, value=act)
    ws.cell(row=r, column=5, value=f"=IF(ABS(C{r}-D{r})<0.01,\"✓ PASS\",\"✗ FAIL\")")
    style_data_row(ws, row_num=r, col_start=2, col_end=last_col, row_index=i)
ws.conditional_formatting.add(f"E{r0}:E{r0 + len(checks) - 1}",
    CellIsRule(operator="equal", formula=['"✗ FAIL"'], font=Font(color=ACCENT_NEGATIVE)))
auto_fit_columns(ws, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

out = "excel/投资决策看板.xlsx"
wb.save(out)
print("saved:", out)
