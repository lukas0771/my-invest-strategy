/* 四维信号投资策略系统 — 前端逻辑 */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
let charts = {}; // tab -> [echart instances]

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json()).error || r.statusText);
  return r.json();
}
const fmt = (v, d = 1) => (v === null || v === undefined || v === "") ? "—" :
  (typeof v === "number" ? v.toFixed(d) : v);
const fmtPct = (v, d = 0) => (v === null || v === undefined) ? "—" : (v * 100).toFixed(d) + "%";
const cls = (v) => v > 0 ? "pos" : (v < 0 ? "neg" : "");
function zoneBadge(z, pct) {
  if (pct === null || pct === undefined) return `<span class="muted">—</span>`;
  const map = {"低估": "b-low", "合理偏低": "b-low", "合理": "b-fair", "合理偏高": "b-high", "高估": "b-extreme"};
  return `<span class="badge ${map[z] || "b-fair"}">${z}</span>`;
}
function chart(id) {
  if (charts[id]) charts[id].dispose();
  const el = document.getElementById(id);
  charts[id] = echarts.init(el, "dark");
  return charts[id];
}
const AXIS = { axisLine: { lineStyle: { color: "#2a3644" } }, axisLabel: { color: "#7d8b9c" } };

/* ---------------- 导航 ---------------- */
$("#nav").addEventListener("click", async (e) => {
  if (!e.target.dataset.tab) return;
  $$("#nav a").forEach(a => a.classList.remove("active"));
  e.target.classList.add("active");
  $$(".tab").forEach(t => t.classList.remove("active"));
  $("#tab-" + e.target.dataset.tab).classList.add("active");
  const renderers = { overview: renderOverview, valuation: renderValuation, trend: renderTrend,
    flows: renderFlows, macro: renderMacro, strategy: renderStrategy,
    portfolio: renderPortfolio, backtest: renderBacktest, report: renderReport,
    news: renderNews, watchlist: renderWatchlist, automation: renderAutomation };
  renderTicker();
  try { await renderers[e.target.dataset.tab](); } catch (err) { alert(err.message); }
});

/* ---------------- 行情指数条 ---------------- */
let TICKER_DATA = null;
async function renderTicker() {
  try {
    const d = await api("/api/ticker");
    TICKER_DATA = d.ticker;
    $("#ticker").innerHTML = d.ticker.map(t => `
      <div class="ticker-item" onclick="switchTab('trend')">
        <div class="tn">${t.name} <span class="tdate">${t.date}</span></div>
        <div class="tc">${t.close.toLocaleString()}</div>
        <div class="tg ${cls(t.chg)}">${t.chg >= 0 ? "▲" : "▼"} ${Math.abs(t.chg).toFixed(2)}%</div>
      </div>`).join("");
  } catch { $("#ticker").innerHTML = ""; }
}

/* ---------------- 总览 ---------------- */
const ROLE = { core: "核心", defensive: "防守", industry: "行业卫星", region: "国别卫星", cash: "现金" };
async function renderOverview() {
  const [sum, data, sys] = await Promise.all([api("/api/summary"), api("/api/assets"), api("/api/system")]);
  const good = sum.regime.includes("偏多");
  $("#ov-cards").innerHTML = `
    <div class="card-kpi"><div class="k">市场体制</div><div class="v ${good ? "good" : "bad"}">${sum.regime}</div></div>
    <div class="card-kpi"><div class="k">组合股票仓位</div><div class="v">${fmt(sum.equity_weight)}%</div></div>
    <div class="card-kpi"><div class="k">有效信号资产</div><div class="v">${sum.n_assets} / ${sum.n_assets_total}</div></div>
    <div class="card-kpi"><div class="k">最近数据刷新</div><div class="v" style="font-size:14px">${sum.last_refresh || "—"}</div></div>
    <div class="card-kpi"><div class="k">Tushare</div><div class="v ${sys.tushare_configured ? "good" : "warn"}" style="font-size:14px">${sys.tushare_configured ? "已配置" : "未配置"}</div></div>`;
  const rows = data.assets.map(a => `
    <tr><td><b>${a.name}</b></td><td>${ROLE[a.role] || a.role}</td>
    <td class="num">${fmt(a.close, 2)}</td>
    <td class="num">${a.val_pct === null ? "—" : fmtPct(a.val_pct)}</td>
    <td>${zoneBadge(a.val_zone, a.val_pct)}</td>
    <td class="num">${a.dca_multiplier === null ? "—" : a.dca_multiplier + "x"}</td>
    <td class="num">${fmt(a.trend_score)}</td><td class="num">${fmt(a.flows_score)}</td>
    <td class="num">${fmt(a.macro_score)}</td>
    <td class="num"><b>${fmt(a.total)}</b></td>
    <td class="num">${fmt(a.target_weight)}%</td>
    <td>${a.action || "—"}</td></tr>`).join("");
  $("#ov-scorecard").innerHTML = `<table><tr>
    <th>资产</th><th>角色</th><th>收盘</th><th>估值分位</th><th>估值区</th><th>定投</th>
    <th>趋势</th><th>资金</th><th>宏观</th><th>总分</th><th>目标权重</th><th>建议</th></tr>${rows}</table>`;
  const pie = chart("ov-pie");
  pie.setOption({ backgroundColor: "transparent", color: CHART_COLORS, tooltip: { trigger: "item", formatter: "{b}: {c}%" },
    legend: { bottom: 0, textStyle: { color: "#7d8b9c", fontSize: 11 },
      type: "scroll", pageIconColor: "#4cc9f0" },
    series: [{ type: "pie", radius: ["38%", "68%"], center: ["50%", "44%"],
      data: data.assets.filter(a => a.target_weight > 0).map(a => ({ name: a.name, value: a.target_weight })),
      label: { color: "#dbe4ee", fontSize: 11, formatter: "{b} {c}%" },
      itemStyle: { borderColor: "#11161d", borderWidth: 1 } }] });
  // 预警 + 数据源健康
  $("#ov-alerts").innerHTML = sum.alerts.length ?
    `<ul class="notes">${sum.alerts.map(a => `<li><b>${a.asset}</b>：${a.text}</li>`).join("")}</ul>` :
    '<p class="pos">✓ 无预警</p>';
  const okCnt = sys.sources.filter(s => s.status === "ok").length;
  $("#ov-sources").innerHTML = `
    <p class="muted small" style="margin-bottom:6px">数据源健康：${okCnt}/${sys.sources.length} 正常 ·
      最近刷新 ${sys.last_refresh || "—"} · <a href="#" onclick="switchTab('automation');return false;" style="color:var(--accent)">查看全部 →</a></p>
    ${sys.sources.slice(0, 8).map(s => `<div class="src-row">
      <span class="dot ${s.status === "ok" ? "dot-ok" : s.status === "skip" ? "dot-skip" : "dot-bad"}"></span>
      <span class="src-target">${s.target}</span>
      <span class="muted small">${s.source} · ${s.ts.slice(5, 16)}</span></div>`).join("")}`;
}
const CHART_COLORS = ["#4cc9f0", "#2fbf71", "#f5a524", "#e5484d", "#b388ff", "#26c6da", "#ef9a9a", "#9ccc65", "#ffb74d", "#4db6ac", "#7986cb", "#f06292"];
function switchTab(name) {
  document.querySelector(`#nav a[data-tab="${name}"]`)?.click();
}

/* ---------------- 估值 ---------------- */
async function renderValuation() {
  const { valuation } = await api("/api/valuation");
  const withPct = valuation.filter(v => v.pct !== null);
  const names = withPct.map(v => v.name);
  const pcts = withPct.map(v => +(v.pct * 100).toFixed(1));
  const colors = withPct.map(v => v.pct < 0.2 ? "#2fbf71" : v.pct < 0.4 ? "#6bd089" :
    v.pct < 0.6 ? "#7fb3e0" : v.pct < 0.8 ? "#f5a524" : "#e5484d");
  chart("val-bars").setOption({ backgroundColor: "transparent",
    tooltip: { formatter: p => `${p.name}：${p.value}% 分位` }, grid: { left: 90 },
    xAxis: { type: "value", max: 100, ...AXIS, splitLine: { lineStyle: { color: "#18222d" } } },
    yAxis: { type: "category", data: names, inverse: true, ...AXIS },
    series: [{ type: "bar", data: pcts.map((p, i) => ({ value: p, itemStyle: { color: colors[i] } })),
      label: { show: true, position: "right", color: "#dbe4ee", formatter: "{c}%" } }] });
  const sel = $("#val-select");
  sel.innerHTML = valuation.map(v => `<option value="${v.name}">${v.name}</option>`).join("");
  const draw = () => {
    const v = valuation.find(x => x.name === sel.value);
    chart("val-hist").setOption({ backgroundColor: "transparent", tooltip: { trigger: "axis" },
      xAxis: { type: "time", ...AXIS }, yAxis: { type: "value", scale: true, ...AXIS },
      series: [{ type: "line", name: v.type === "shiller" ? "席勒PE" : "PE-TTM", showSymbol: false,
        data: v.history, lineStyle: { color: "#4cc9f0" }, areaStyle: { opacity: 0.08 } }] });
  };
  sel.onchange = draw; draw();
}

/* ---------------- 趋势 ---------------- */
async function renderTrend() {
  const { trend } = await api("/api/trend");
  const names = trend.map(t => t.name);
  const mom = trend.map(t => t.momentum === null ? 0 : +(t.momentum * 100).toFixed(1));
  chart("tr-mom").setOption({ backgroundColor: "transparent", tooltip: { formatter: p => `${p.name}: ${p.value}%` },
    grid: { left: 90 },
    xAxis: { type: "value", ...AXIS, splitLine: { lineStyle: { color: "#18222d" } } },
    yAxis: { type: "category", data: names, ...AXIS },
    series: [{ type: "bar", data: mom.map(v => ({ value: v, itemStyle: { color: v >= 0 ? "#2fbf71" : "#e5484d" } })) }] });
  $("#tr-table").innerHTML = `<table><tr><th>资产</th><th>200日线上?</th><th>趋势分</th><th>动量排名</th></tr>` +
    trend.map(t => `<tr><td>${t.name}</td>
      <td>${t.above_ma200 === null ? "—" : (t.above_ma200 ? '<span class="pos">是</span>' : '<span class="neg">否</span>')}</td>
      <td class="num">${fmt(t.trend_score)}</td><td class="num">#${t.momentum_rank}</td></tr>`).join("") + "</table>";
  const sel = $("#tr-select");
  sel.innerHTML = trend.map(t => `<option value="${t.key}">${t.name}</option>`).join("");
  const draw = () => {
    const t = trend.find(x => x.key === sel.value);
    const c = chart("tr-chart");
    const base = { backgroundColor: "transparent", tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#7d8b9c" }, top: 0 },
      xAxis: { type: "category", data: t.kline.dates, ...AXIS },
      yAxis: { type: "value", scale: true, ...AXIS },
      dataZoom: [{ type: "inside", start: 55, end: 100 }, { type: "slider", start: 55, end: 100, height: 18, bottom: 4 }],
      grid: { left: 60, right: 20, top: 30, bottom: 46 } };
    if (t.kline.mode === "candle") {
      base.series = [
        { name: "K线", type: "candlestick", data: t.kline.kline,
          itemStyle: { color: "#e05656", color0: "#2fbf71", borderColor: "#e05656", borderColor0: "#2fbf71" } },
        { name: "MA20", type: "line", data: t.kline.ma20, showSymbol: false, lineStyle: { color: "#f5a524", width: 1 } },
        { name: "MA60", type: "line", data: t.kline.ma60, showSymbol: false, lineStyle: { color: "#4cc9f0", width: 1 } },
        { name: "MA200", type: "line", data: t.kline.ma200, showSymbol: false, lineStyle: { color: "#b388ff", width: 1.4 } }];
    } else {
      base.series = [
        { name: "收盘价", type: "line", showSymbol: false, data: t.kline.line, lineStyle: { color: "#4cc9f0" } },
        { name: "MA20", type: "line", data: t.kline.ma20, showSymbol: false, lineStyle: { color: "#f5a524", width: 1 } },
        { name: "MA60", type: "line", data: t.kline.ma60, showSymbol: false, lineStyle: { color: "#26c6da", width: 1 } },
        { name: "MA200", type: "line", data: t.kline.ma200, showSymbol: false, lineStyle: { color: "#b388ff", width: 1.4 } }];
    }
    c.setOption(base, true);
  };
  sel.onchange = draw; draw();
}

/* ---------------- 资金面 ---------------- */
async function renderFlows() {
  const [d, sys] = await Promise.all([api("/api/flows"), api("/api/system")]);
  if (d.margin_index.length) {
    chart("fl-margin").setOption({ backgroundColor: "transparent", tooltip: { trigger: "axis" },
      grid: { left: 80, right: 16 },
      xAxis: { type: "time", ...AXIS }, yAxis: { type: "value", scale: true, ...AXIS,
        axisLabel: { color: "#7d8b9c", formatter: (v) => (v / 100000000).toFixed(1) + "亿" } },
      series: [{ type: "line", name: "两融余额指数", showSymbol: false, data: d.margin_index,
        lineStyle: { color: "#4cc9f0" }, areaStyle: { opacity: 0.08 } }] });
  } else {
    $("#fl-margin").innerHTML = sys.tushare_configured ?
      '<p class="muted" style="padding:40px">✓ token 已配置但两融数据为空 —— 点左下「刷新数据」重新拉取；若仍为空，到「自动化」页查看刷新日志中的失败原因。</p>' :
      '<p class="muted" style="padding:40px">两融数据需要 tushare token：项目根目录 .env 填 TUSHARE_TOKEN= → 保存 → 点「刷新数据」（无需重启服务）。</p>';
  }
  $("#fl-note").textContent = (sys.tushare_configured ? "✓ Tushare 已配置；" : "⚠ Tushare 未配置；") + d.note;
  const vols = d.volume_ratios;
  if (vols.length) {
    chart("fl-vol").setOption({ backgroundColor: "transparent", tooltip: {},
      grid: { left: 90 },
      xAxis: { type: "value", ...AXIS }, yAxis: { type: "category", data: vols.map(v => v.name).reverse(), ...AXIS },
      series: [{ type: "bar", data: vols.map(v => ({ value: v.volume_ratio,
        itemStyle: { color: v.volume_ratio > 1.2 ? "#e5484d" : v.volume_ratio > 1 ? "#f5a524" : "#2fbf71" } })),
        markLine: { data: [{ xAxis: 1 }], lineStyle: { color: "#7d8b9c" }, label: { formatter: "1.0" } } }] });
  }
  $("#fl-prem").innerHTML = d.premiums.length ?
    `<table><tr><th>代码</th><th>名称</th><th>溢价率</th><th>状态</th><th>更新</th></tr>` +
    d.premiums.map(p => `<tr><td>${p.code}</td><td>${p.name}</td><td class="num">${p.premium}%</td>
      <td>${p.over_limit ? '<span class="badge b-extreme">超限拒买</span>' : '<span class="badge b-low">正常</span>'}</td>
      <td class="muted">${p.updated}</td></tr>`).join("") + "</table>" :
    '<p class="muted">QDII 溢价：配置 tushare token 后由「ETF收盘价 / 最新基金净值」自动计算（近似值）；当前无数据。</p>';
}

/* ---------------- 宏观 ---------------- */
async function renderMacro() {
  const d = await api("/api/macro");
  const line = (id, data, ref, color = "#4cc9f0", name = "") => {
    const c = chart(id);
    const opt = { backgroundColor: "transparent", tooltip: { trigger: "axis" },
      xAxis: { type: "time", ...AXIS }, yAxis: { type: "value", scale: true, ...AXIS },
      series: [{ type: "line", name, showSymbol: false, data, lineStyle: { color } }] };
    if (ref !== null) opt.series[0].markLine = { data: [{ yAxis: ref }], lineStyle: { color: "#7d8b9c", type: "dashed" }, silent: true };
    c.setOption(opt);
  };
  line("ma-pmi", d.pmi, 50, "#4cc9f0", "PMI");
  line("ma-gap", d.m1_m2_gap, 0, "#f5a524", "M1-M2");
  line("ma-ppi", d.ppi, 0, "#2fbf71", "PPI");
  line("ma-us10y", d.us10y, null, "#e5484d", "US10Y");
  line("ma-shiller", d.shiller, null, "#b388ff", "ShillerPE");
}

/* ---------------- 策略 ---------------- */
async function renderStrategy() {
  const d = await api("/api/strategy");
  const good = d.regime.includes("偏多");
  $("#st-cards").innerHTML = `
    <div class="card-kpi"><div class="k">市场体制</div><div class="v ${good ? "good" : "bad"}">${d.regime}</div></div>
    <div class="card-kpi"><div class="k">股票仓位</div><div class="v">${fmt(d.equity_weight)}%</div></div>
    <div class="card-kpi"><div class="k">生成时间</div><div class="v" style="font-size:14px">${d.generated_at}</div></div>`;
  const sig = Object.fromEntries(d.signals.map(s => [s.key, s]));
  // 定投计划
  const monthly = +$("#st-monthly").value || 10000;
  const dcaRows = d.signals.filter(s => ["equity_cn", "equity_global"].includes(s.asset_class)
    && (d.weights[s.key] || 0) >= 1).map(s => {
    const base = d.weights[s.key] / 100 * monthly;
    const mult = s.dca_multiplier === null ? 1 : s.dca_multiplier;
    return `<tr><td>${s.name}</td><td class="num">${fmt(d.weights[s.key])}%</td>
      <td class="num">${base.toFixed(0)}</td><td class="num"><b>${mult}x</b></td>
      <td class="num">${(base * mult).toFixed(0)}</td></tr>`;
  }).join("");
  $("#st-dca").innerHTML = `<table><tr><th>资产</th><th>目标权重</th><th>基准金额</th><th>估值倍数</th><th>实际定投</th></tr>${dcaRows}</table>`;
  // 权重与操作
  const wRows = Object.entries(d.weights).filter(([k, w]) => w > 0 || (sig[k] && sig[k].action))
    .sort((a, b) => b[1] - a[1]).map(([k, w]) => {
      const s = sig[k] || {};
      return `<tr><td><b>${s.name || k}</b></td><td>${ROLE[s.role] || s.role || ""}</td>
        <td class="num">${fmt(w)}%</td><td class="num">${fmt(s.total)}</td><td>${s.action || ""}</td></tr>`;
    }).join("");
  $("#st-weights").innerHTML = `<table><tr><th>资产</th><th>角色</th><th>目标权重</th><th>总分</th><th>当前建议</th></tr>${wRows}</table>`;
  $("#st-notes").innerHTML = d.notes.map(n => `<li>${n}</li>`).join("") || "<li>无</li>";
}
$("#st-monthly")?.addEventListener("change", renderStrategy);

/* ---------------- 持仓 ---------------- */
let pfRows = [];
let pfLast = { rows: [], total_value: 0, rebalance: [], rebalance_note: "" };
let UNIVERSE = null;   // [{key,name}]
async function loadUniverse() {
  if (!UNIVERSE) {
    const d = await api("/api/assets");
    UNIVERSE = d.assets.map(a => ({ key: a.key, name: a.name }));
  }
  return UNIVERSE;
}
async function renderPortfolio() {
  await loadUniverse();
  const d = await api("/api/portfolio");
  pfRows = d.rows.map(r => ({ ...r }));
  pfLast = d;
  drawPortfolio(d);
}
function drawPortfolio(d) {
  $("#pf-cards").innerHTML = `
    <div class="card-kpi"><div class="k">组合总市值</div><div class="v">¥ ${(+d.total_value).toLocaleString()}</div></div>
    <div class="card-kpi"><div class="k">持仓笔数</div><div class="v">${d.rows.length}</div></div>`;
  const ASSET_OPTS = (UNIVERSE || []).map(a => `<option value="${a.key}">${a.name}</option>`).join("");
  $("#pf-table").innerHTML = `<table><tr><th>代码</th><th>名称</th><th>资产类别</th><th>份额</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>盈亏%</th><th></th></tr>` +
    pfRows.map((r, i) => `<tr>
      <td><input value="${r.code || ""}" data-i="${i}" data-f="code" class="input-sm" style="width:80px"></td>
      <td><input value="${r.name || ""}" data-i="${i}" data-f="name" class="input-sm" style="width:110px"></td>
      <td><select data-i="${i}" data-f="asset_key" class="input-sm">${ASSET_OPTS}</select></td>
      <td><input value="${r.shares ?? ""}" data-i="${i}" data-f="shares" class="input-sm" style="width:80px"></td>
      <td><input value="${r.cost ?? ""}" data-i="${i}" data-f="cost" class="input-sm" style="width:80px"></td>
      <td class="num">${r.price || "—"}</td><td class="num">${r.value ? (+r.value).toLocaleString() : "—"}</td>
      <td class="num ${cls(r.pl)}">${r.pl ? (+r.pl).toLocaleString() : "—"}</td>
      <td class="num ${cls(r.pl_pct)}">${r.pl_pct === null ? "—" : r.pl_pct + "%"}</td>
      <td><button class="btn danger" data-del="${i}">删</button></td></tr>`).join("") + "</table>";
  $$("#pf-table [data-f]").forEach(el => el.addEventListener("change", (e) => {
    pfRows[+e.target.dataset.i][e.target.dataset.f] = e.target.value;
  }));
  $$("#pf-table select").forEach(el => { el.value = pfRows[+el.dataset.i].asset_key || "hs300"; });
  $$("#pf-table [data-del]").forEach(el => el.addEventListener("click", () => { pfRows.splice(+el.dataset.del, 1); drawPortfolio(d); }));
  $("#pf-rebal").innerHTML = `<table><tr><th>资产</th><th>当前权重</th><th>目标</th><th>偏离</th><th>当前市值</th><th>目标市值</th><th>调仓金额</th><th>触发</th></tr>` +
    d.rebalance.map(r => `<tr><td>${r.name}</td><td class="num">${fmt(r.cur_weight)}%</td>
      <td class="num">${fmt(r.target_weight)}%</td>
      <td class="num ${cls(r.dev)}">${fmt(r.dev)}pp</td>
      <td class="num">${(+r.cur_value).toLocaleString()}</td><td class="num">${(+r.target_value).toLocaleString()}</td>
      <td class="num ${cls(r.trade)}">${(+r.trade).toLocaleString()}</td>
      <td>${r.trigger ? '<span class="badge b-high">触发</span>' : "—"}</td></tr>`).join("") + "</table>";
  $("#pf-note").textContent = d.rebalance_note;
}
$("#pf-add")?.addEventListener("click", () => {
  pfRows.push({ code: "", name: "", asset_key: "hs300", shares: "", cost: "", price: 0, value: 0, pl: 0, pl_pct: null });
  drawPortfolio({ ...pfLast, rows: pfRows });
});
$("#pf-save")?.addEventListener("click", async () => {
  const payload = pfRows.map(r => ({ code: r.code, name: r.name, asset_key: r.asset_key,
    shares: +r.shares || 0, cost: +r.cost || 0 }));
  const d = await api("/api/portfolio", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  pfRows = d.rows.map(r => ({ ...r }));
  pfLast = d;
  drawPortfolio(d);
});

/* ---------------- 回测 ---------------- */
async function renderBacktest() {
  try {
    const d = await api("/api/backtest");
    drawBacktest(d);
  } catch { $("#bt-status").textContent = "尚未运行，点击按钮开始"; }
}
function drawBacktest(d) {
  $("#bt-note").textContent = d.note;
  const c = chart("bt-curves");
  const colors = ["#4cc9f0", "#f5a524", "#e5484d", "#2fbf71"];
  c.setOption({ backgroundColor: "transparent", color: colors, tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#7d8b9c" }, top: 0 },
    xAxis: { type: "time", ...AXIS }, yAxis: { type: "value", scale: true, ...AXIS },
    series: Object.entries(d.strategies).map(([k, m], i) => ({
      name: d.strategy_names[k] || k, type: "line", showSymbol: false,
      data: Object.entries(m.curve), itemStyle: { color: colors[i % 4] },
      lineStyle: { color: colors[i % 4] } })) });
  const metRows = Object.entries(d.strategies).map(([k, m]) =>
    `<tr><td>${d.strategy_names[k]}</td><td class="num ${cls(m.cagr)}">${(m.cagr * 100).toFixed(1)}%</td>
     <td class="num neg">${(m.max_drawdown * 100).toFixed(1)}%</td>
     <td class="num">${(m.vol * 100).toFixed(1)}%</td><td class="num">${m.sharpe}</td><td class="num">${m.months}</td></tr>`).join("");
  $("#bt-metrics").innerHTML = `<table><tr><th>策略</th><th>年化</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>月数</th></tr>${metRows}</table>`;
  const years = [...new Set(Object.values(d.strategies).flatMap(m => Object.keys(m.yearly)))].sort();
  const head = `<tr><th>策略</th>${years.map(y => `<th>${y}</th>`).join("")}</tr>`;
  const body = Object.entries(d.strategies).map(([k, m]) =>
    `<tr><td>${d.strategy_names[k]}</td>${years.map(y => {
      const v = m.yearly[y];
      return `<td class="num ${cls(v)}">${v === undefined ? "—" : (v * 100).toFixed(1) + "%"}</td>`;
    }).join("")}</tr>`).join("");
  $("#bt-yearly").innerHTML = `<table>${head}${body}</table>`;
}
$("#bt-run")?.addEventListener("click", async () => {
  $("#bt-status").textContent = "回测运行中（约1分钟）…";
  try { const d = await api("/api/backtest/run", { method: "POST" }); drawBacktest(d); $("#bt-status").textContent = "完成"; }
  catch (e) { $("#bt-status").textContent = "失败: " + e.message; }
});

/* ---------------- 报告 ---------------- */
function md2html(md) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>");
  const lines = esc(md).split("\n");
  let html = "", inTable = false, isFirstRow = false, inList = false;
  const closeTable = () => { if (inTable) { html += "</table>"; inTable = false; } };
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const ln of lines) {
    const t = ln.trim();
    if (/^\|.*\|$/.test(t)) {
      if (/^[\s\-:|]+$/.test(t)) continue;           // 分隔行
      const cells = t.split("|").slice(1, -1);
      if (!inTable) { html += "<table>"; inTable = true; isFirstRow = true; }
      const tag = isFirstRow ? "th" : "td";
      html += "<tr>" + cells.map(c => `<${tag}>${inline(c.trim())}</${tag}>`).join("") + "</tr>";
      isFirstRow = false;
      continue;
    }
    closeTable();
    if (/^### /.test(t)) { closeList(); html += `<h3>${inline(t.slice(4))}</h3>`; }
    else if (/^## /.test(t)) { closeList(); html += `<h2>${inline(t.slice(3))}</h2>`; }
    else if (/^# /.test(t)) { closeList(); html += `<h1>${inline(t.slice(2))}</h1>`; }
    else if (/^- /.test(t)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(t.slice(2))}</li>`; }
    else if (/^> /.test(t)) { html += `<blockquote>${inline(t.slice(2))}</blockquote>`; }
    else if (/^---+$/.test(t)) { html += "<hr>"; }
    else if (/^\*.+\*$/.test(t)) { html += `<p class="muted">${inline(t)}</p>`; }
    else if (t === "") { closeList(); }
    else { closeList(); html += `<p>${inline(t)}</p>`; }
  }
  closeTable(); closeList();
  return html;
}
async function renderReport() {
  const d = await api("/api/report");
  $("#rp-md").innerHTML = md2html(d.md);
}

/* ---------------- 刷新按钮 ---------------- */
$("#btn-refresh")?.addEventListener("click", async () => {
  await api("/api/refresh", { method: "POST" });
  $("#refresh-status").textContent = "刷新已启动…";
  const timer = setInterval(async () => {
    const s = await api("/api/refresh/status");
    $("#refresh-status").textContent = s.running ? `运行中… (${s.log.length} 步)` :
      `完成 ${s.finished || ""}`;
    if (!s.running) { clearInterval(timer); renderOverview(); }
  }, 3000);
});

/* ---------------- 新闻 ---------------- */
function newsListHtml(items) {
  if (!items || !items.length) return '<p class="muted">暂无新闻数据（数据源不可用或未刷新）。</p>';
  return items.map(n => `<div class="nw-item">
    <div class="nw-title">${n.title}</div>
    <div class="nw-sum">${n.summary}</div>
    <div class="nw-meta">${n.time} · ${n.source}</div></div>`).join("");
}
async function renderNews() {
  const d = await api("/api/news");
  $("#nw-src").textContent = d.source ? `财经新闻（来源：${d.source}）` : "财经新闻";
  $("#nw-list").innerHTML = newsListHtml(d.items);
  $("#ov-news").innerHTML = newsListHtml((d.items || []).slice(0, 5)) ||
    '<p class="muted">暂无数据</p>';
}

/* ---------------- 自选清单 ---------------- */
function renderWatchlistTable(d) {
  $("#wl-table").innerHTML = d.rows.length ?
    `<table><tr><th>代码</th><th>名称</th><th>最新价/净值</th><th>近1月</th><th>QDII溢价</th><th>日期</th><th></th></tr>` +
    d.rows.map(r => `<tr><td><b>${r.code}</b></td><td>${r.name || "—"}</td>
      <td class="num">${r.price ?? "—"}</td>
      <td class="num ${cls(r.chg1m)}">${r.chg1m === null ? "—" : r.chg1m + "%"}</td>
      <td class="num">${r.premium === null ? "—" :
        `<span class="badge ${r.premium > 3 ? "b-extreme" : "b-low"}">${r.premium}%</span>`}</td>
      <td class="muted">${r.price_date || "—"}</td>
      <td><button class="btn danger" data-wdel="${r.code}">删</button></td></tr>`).join("") + "</table>" :
    '<p class="muted">还没有自选，添加一个基金/ETF 代码试试。</p>';
  $$("#wl-table [data-wdel]").forEach(el => el.addEventListener("click", async () => {
    const d2 = await api("/api/watchlist/" + el.dataset.wdel, { method: "DELETE" });
    renderWatchlistTable(d2);
  }));
}
async function renderWatchlist() {
  const d = await api("/api/watchlist");
  renderWatchlistTable(d);
}
$("#wl-add")?.addEventListener("click", async () => {
  const code = $("#wl-code").value.trim(), name = $("#wl-name").value.trim();
  if (!/^\d{6}$/.test(code)) { $("#wl-status").textContent = "请输入 6 位数字代码"; return; }
  $("#wl-status").textContent = "添加中…";
  try {
    const d = await api("/api/watchlist", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, name }) });
    renderWatchlistTable(d);
    $("#wl-code").value = ""; $("#wl-name").value = ""; $("#wl-status").textContent = "✓ 已添加";
  } catch (e) { $("#wl-status").textContent = e.message; }
});

/* ---------------- 自动化 ---------------- */
async function renderAutomation() {
  const d = await api("/api/automation");
  const okCnt = d.log.filter(l => l.status === "ok").length;
  const failCnt = d.log.filter(l => l.status === "fail").length;
  $("#au-cards").innerHTML = `
    <div class="card-kpi"><div class="k">每日定时刷新</div>
      <div class="v ${d.scheduler.enabled ? "good" : "warn"}" style="font-size:15px">
        ${d.scheduler.enabled ? "已启用 · 下次 " + (d.scheduler.next_run || "").slice(0, 16) : "未启用（DISABLE_SCHEDULER=1）"}</div></div>
    <div class="card-kpi"><div class="k">最近刷新</div><div class="v" style="font-size:14px">${d.last_refresh || "—"}</div></div>
    <div class="card-kpi"><div class="k">日志成功/失败</div><div class="v">${okCnt} <span class="neg" style="font-size:15px">/ ${failCnt}</span></div></div>`;
  $("#au-log").innerHTML = d.log.length ?
    `<table><tr><th>时间</th><th>来源</th><th>目标</th><th>状态</th><th>详情</th></tr>` +
    d.log.map(l => `<tr><td class="muted">${(l.ts || "").slice(5, 16)}</td><td>${l.source}</td>
      <td>${l.target}</td>
      <td>${l.status === "ok" ? '<span class="pos">✓ ok</span>' : l.status === "skip" ? '<span class="muted">skip</span>' : '<span class="neg">✗ fail</span>'}</td>
      <td class="muted small">${l.detail}</td></tr>`).join("") + "</table>" :
    '<p class="muted">暂无日志。</p>';
}
$("#au-run")?.addEventListener("click", async () => {
  await api("/api/refresh", { method: "POST" });
  $("#au-status").textContent = "刷新已启动…";
  const timer = setInterval(async () => {
    const s = await api("/api/refresh/status");
    $("#au-status").textContent = s.running ? `运行中…` : "完成 " + (s.finished || "");
    if (!s.running) { clearInterval(timer); renderAutomation(); }
  }, 3000);
});

/* ---------------- 启动 ---------------- */
window.addEventListener("resize", () => Object.values(charts).forEach(c => c.resize()));
renderOverview();
