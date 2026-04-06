"""
BreakFromValley Dashboard — IMC Prosperity 4
Universal visualizer for any round, any product.

Modes:
  python dashboard.py results/54220.json          # Single algo result
  python dashboard.py results/54220.json results/5413.json  # Compare algos
  python dashboard.py --market                     # Raw market data from p4_data/

Features:
  - Auto-detects all products (works for any round)
  - Order book depth (3 levels, bid/ask)
  - PNL curve per product
  - Position tracking (estimated from PNL + price changes)
  - Algo comparison overlay
  - Stats: final PNL, max drawdown, win rate, avg win/loss
"""

import json
import csv
import sys
import os
import webbrowser
from collections import defaultdict


def load_chartjs():
    path = os.path.join(os.path.dirname(__file__), "chart.min.js")
    if os.path.exists(path):
        return open(path).read()
    # Fallback: try to download
    import urllib.request
    url = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
    data = urllib.request.urlopen(url).read().decode()
    with open(path, "w") as f:
        f.write(data)
    return data


COLORS = [
    "#10b981", "#ef4444", "#3b82f6", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
]


def parse_result(filepath):
    """Parse an IMC result JSON into per-product time series."""
    with open(filepath) as f:
        data = json.load(f)

    profit = data.get("profit", 0)
    lines = data["activitiesLog"].strip().split("\n")
    header = lines[0].split(";")

    products = {}
    for line in lines[1:]:
        parts = line.split(";")
        row = dict(zip(header, parts))
        product = row.get("product", "")
        if not product:
            continue

        if product not in products:
            products[product] = []

        day = int(row.get("day", 0))
        ts = int(row.get("timestamp", 0))

        entry = {"ts": day * 1_000_000 + ts, "day": day, "raw_ts": ts}

        for level in [1, 2, 3]:
            for side, key in [("bp", "bid_price_"), ("bv", "bid_volume_"),
                              ("ap", "ask_price_"), ("av", "ask_volume_")]:
                val = row.get(f"{key}{level}", "")
                if side in ("bp", "ap"):
                    entry[f"{side}{level}"] = float(val) if val else None
                else:
                    entry[f"{side}{level}"] = int(float(val)) if val else 0

        entry["mid"] = float(row["mid_price"]) if row.get("mid_price") else None
        entry["pnl"] = float(row.get("profit_and_loss", 0))
        products[product].append(entry)

    # Estimate positions
    for product, entries in products.items():
        positions = [0]
        for i in range(1, len(entries)):
            delta_pnl = entries[i]["pnl"] - entries[i - 1]["pnl"]
            delta_mid = (entries[i]["mid"] or 0) - (entries[i - 1]["mid"] or 0)
            prev = positions[-1]
            if delta_mid != 0:
                est = delta_pnl / delta_mid
                positions.append(round(est) if abs(est - prev) < 50 else prev)
            else:
                positions.append(prev)
        for i, e in enumerate(entries):
            e["pos"] = positions[i]

    return profit, products


def compute_stats(entries):
    pnl_list = [e["pnl"] for e in entries]
    changes = [pnl_list[i] - pnl_list[i - 1]
               for i in range(1, len(pnl_list)) if pnl_list[i] != pnl_list[i - 1]]
    wins = [c for c in changes if c > 0]
    losses = [c for c in changes if c < 0]

    peak = 0
    max_dd = 0
    for p in pnl_list:
        if p > peak:
            peak = p
        dd = p - peak
        if dd < max_dd:
            max_dd = dd

    return {
        "final_pnl": round(pnl_list[-1], 1),
        "max_pnl": round(max(pnl_list), 1),
        "min_pnl": round(min(pnl_list), 1),
        "max_drawdown": round(max_dd, 1),
        "trades": len(changes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(changes) * 100, 1) if changes else 0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
    }


def downsample(entries, max_points=800):
    step = max(1, len(entries) // max_points)
    sampled = entries[::step]
    return {
        "ts": [e["ts"] for e in sampled],
        "bp1": [e["bp1"] for e in sampled],
        "bp2": [e["bp2"] for e in sampled],
        "bp3": [e["bp3"] for e in sampled],
        "bv1": [e["bv1"] for e in sampled],
        "bv2": [e["bv2"] for e in sampled],
        "bv3": [e["bv3"] for e in sampled],
        "ap1": [e["ap1"] for e in sampled],
        "ap2": [e["ap2"] for e in sampled],
        "ap3": [e["ap3"] for e in sampled],
        "av1": [e["av1"] for e in sampled],
        "av2": [e["av2"] for e in sampled],
        "av3": [e["av3"] for e in sampled],
        "mid": [e["mid"] for e in sampled],
        "pnl": [e["pnl"] for e in sampled],
        "pos": [e["pos"] for e in sampled],
    }


def load_market_data():
    """Load raw market CSVs from p4_data/."""
    data_dir = os.path.join(os.path.dirname(__file__), "p4_data")
    if not os.path.exists(data_dir):
        print("No p4_data/ directory found")
        sys.exit(1)

    price_files = sorted(f for f in os.listdir(data_dir) if f.startswith("prices_"))
    trade_files = sorted(f for f in os.listdir(data_dir) if f.startswith("trades_"))

    all_products = defaultdict(list)
    for pf in price_files:
        with open(os.path.join(data_dir, pf)) as f:
            for row in csv.DictReader(f, delimiter=";"):
                product = row["product"]
                day = int(row.get("day", -1))
                ts = int(row["timestamp"])
                entry = {
                    "ts": day * 1_000_000 + ts, "day": day, "raw_ts": ts,
                    "mid": float(row["mid_price"]) if row.get("mid_price") else None,
                    "pnl": 0, "pos": 0,
                }
                for level in [1, 2, 3]:
                    bp = row.get(f"bid_price_{level}", "")
                    bv = row.get(f"bid_volume_{level}", "")
                    ap = row.get(f"ask_price_{level}", "")
                    av = row.get(f"ask_volume_{level}", "")
                    entry[f"bp{level}"] = float(bp) if bp else None
                    entry[f"bv{level}"] = int(bv) if bv else 0
                    entry[f"ap{level}"] = float(ap) if ap else None
                    entry[f"av{level}"] = int(av) if av else 0
                all_products[product].append(entry)

    # Load trades
    all_trades = defaultdict(list)
    for tf in trade_files:
        with open(os.path.join(data_dir, tf)) as f:
            for row in csv.DictReader(f, delimiter=";"):
                all_trades[row["symbol"]].append({
                    "ts": int(row["timestamp"]),
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })

    return all_products, all_trades


def generate_html(runs, mode="result"):
    """
    runs: list of (label, profit, {product: entries}, stats_dict)
    mode: "result" or "market"
    """
    chartjs = load_chartjs()

    is_compare = len(runs) > 1
    all_products = sorted(set(p for _, _, products, _ in runs for p in products))
    product_colors = {p: COLORS[i % len(COLORS)] for i, p in enumerate(all_products)}

    # Build chart data
    all_chart_data = {}
    all_stats = {}
    for label, profit, products, stats in runs:
        all_chart_data[label] = {}
        all_stats[label] = {}
        for product in all_products:
            if product in products:
                all_chart_data[label][product] = downsample(products[product])
                all_stats[label][product] = stats.get(product, {})

    # Title
    if is_compare:
        title = "Algo Comparison"
        subtitle = " vs ".join(r[0] for r in runs)
    elif mode == "market":
        title = "Market Data"
        subtitle = "Raw NPC order book from p4_data/"
    else:
        title = f"Run #{runs[0][0]}"
        subtitle = ""

    total_pnl = sum(r[1] for r in runs) / len(runs) if runs else 0
    pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>BreakFromValley — {title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace; background: #0a0e1a; color: #c8d0e0; font-size: 12px; }}

.header {{
  padding: 14px 20px; background: #111827; border-bottom: 1px solid #1e293b;
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}}
.header h1 {{ font-size: 15px; color: #e2e8f0; }}
.header .pnl {{ font-size: 20px; font-weight: bold; color: {pnl_color}; }}
.header .sub {{ color: #64748b; font-size: 11px; }}
.controls {{
  display: flex; gap: 8px; align-items: center; margin-left: auto;
}}
.controls label {{ color: #64748b; font-size: 11px; }}
.controls select, .controls button {{
  background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
  padding: 4px 10px; border-radius: 4px; font-size: 11px; font-family: inherit; cursor: pointer;
}}
.controls button.active {{ background: #3b82f6; border-color: #3b82f6; }}

.dashboard {{ padding: 10px; display: flex; flex-direction: column; gap: 10px; }}

.stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }}
.stat-card {{ background: #111827; border: 1px solid #1e293b; border-radius: 6px; padding: 10px 14px; }}
.stat-card .label {{ color: #64748b; font-size: 10px; text-transform: uppercase; margin-bottom: 3px; }}
.stat-card .value {{ font-size: 16px; font-weight: bold; }}
.stat-card .sub {{ color: #64748b; font-size: 11px; margin-top: 2px; }}

.panel {{
  background: #111827; border: 1px solid #1e293b; border-radius: 6px; overflow: hidden;
}}
.panel-header {{
  padding: 6px 14px; background: #0f172a; border-bottom: 1px solid #1e293b;
  font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;
  display: flex; justify-content: space-between;
}}
.chart-wrap {{ position: relative; height: 320px; padding: 8px; }}
.chart-wrap.small {{ height: 180px; }}

.pos {{ color: #22c55e; }}
.neg {{ color: #ef4444; }}

.legend {{
  display: flex; gap: 16px; padding: 8px 14px; flex-wrap: wrap;
}}
.legend-item {{
  display: flex; align-items: center; gap: 4px; font-size: 11px; color: #94a3b8;
}}
.legend-dot {{
  width: 10px; height: 10px; border-radius: 2px; display: inline-block;
}}
</style>
</head><body>

<div class="header">
  <h1>{title}</h1>
  {"<span class='pnl'>" + ('+' if total_pnl >= 0 else '') + f"{total_pnl:.1f}</span>" if mode == 'result' else ""}
  <span class="sub">{subtitle}</span>
  <div class="controls">
    <label>Product:</label>
    <select id="productSelect" onchange="switchProduct()">
      {''.join(f'<option value="{p}">{p}</option>' for p in all_products)}
    </select>
    <label>OB:</label>
    <button id="togL1" class="active" onclick="toggleLevel(1)">L1</button>
    <button id="togL2" class="active" onclick="toggleLevel(2)">L2</button>
    <button id="togL3" onclick="toggleLevel(3)">L3</button>
  </div>
</div>

<div class="dashboard">
  <div class="stats-row" id="statsRow"></div>

  <div class="panel">
    <div class="panel-header"><span>Order Book + Price</span><span id="hoverInfo"></span></div>
    <div class="chart-wrap"><canvas id="priceChart"></canvas></div>
  </div>

  <div class="panel">
    <div class="panel-header"><span>PNL</span><span id="pnlInfo"></span></div>
    <div class="chart-wrap small"><canvas id="pnlChart"></canvas></div>
  </div>

  <div class="panel">
    <div class="panel-header"><span>Position (estimated)</span><span id="posInfo"></span></div>
    <div class="chart-wrap small"><canvas id="posChart"></canvas></div>
  </div>
</div>

<script>""" + chartjs + """</script>
<script>
const allChartData = """ + json.dumps(all_chart_data) + """;
const allStats = """ + json.dumps(all_stats) + """;
const productNames = """ + json.dumps(all_products) + """;
const runLabels = """ + json.dumps([r[0] for r in runs]) + """;
const isCompare = """ + json.dumps(is_compare) + """;
const runColors = ['#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6'];

let currentProduct = productNames[0];
let showLevels = { 1: true, 2: true, 3: false };
let priceChart, pnlChart, posChart;

function switchProduct() {
  currentProduct = document.getElementById('productSelect').value;
  renderAll();
}

function toggleLevel(level) {
  showLevels[level] = !showLevels[level];
  document.getElementById('togL' + level).classList.toggle('active');
  renderAll();
}

function buildStats() {
  const row = document.getElementById('statsRow');
  // Use first run's stats
  const s = allStats[runLabels[0]]?.[currentProduct];
  if (!s) { row.innerHTML = '<div class="stat-card"><div class="label">No data</div></div>'; return; }

  let html = '';

  if (isCompare) {
    // Show comparison stats
    runLabels.forEach((label, idx) => {
      const st = allStats[label]?.[currentProduct];
      if (!st) return;
      const cls = st.final_pnl >= 0 ? 'pos' : 'neg';
      html += '<div class="stat-card"><div class="label">' + label + '</div>' +
        '<div class="value ' + cls + '">' + st.final_pnl + '</div>' +
        '<div class="sub">DD: ' + st.max_drawdown + ' | WR: ' + st.win_rate + '%</div></div>';
    });
  } else {
    const cls = s.final_pnl >= 0 ? 'pos' : 'neg';
    const ddCls = s.max_drawdown < 0 ? 'neg' : '';
    html = `
      <div class="stat-card"><div class="label">Final PNL</div>
        <div class="value ${cls}">${s.final_pnl}</div>
        <div class="sub">Max: ${s.max_pnl} / Min: ${s.min_pnl}</div></div>
      <div class="stat-card"><div class="label">Max Drawdown</div>
        <div class="value ${ddCls}">${s.max_drawdown}</div></div>
      <div class="stat-card"><div class="label">Trades</div>
        <div class="value">${s.trades}</div>
        <div class="sub">${s.wins}W / ${s.losses}L (${s.win_rate}%)</div></div>
      <div class="stat-card"><div class="label">Avg Win / Loss</div>
        <div class="value"><span class="pos">+${s.avg_win}</span> / <span class="neg">${s.avg_loss}</span></div></div>
    `;
  }
  row.innerHTML = html;
}

function buildPriceData() {
  // Use first run for order book
  const label = runLabels[0];
  const d = allChartData[label]?.[currentProduct];
  if (!d) return { labels: [], datasets: [] };

  const datasets = [];
  const bidColors = ['#3b82f6', '#2563eb', '#1d4ed8'];
  const askColors = ['#ef4444', '#dc2626', '#b91c1c'];

  let maxVol = 1;
  for (let i = 0; i < d.ts.length; i++) {
    for (let l = 1; l <= 3; l++) {
      maxVol = Math.max(maxVol, d['bv'+l][i] || 0, d['av'+l][i] || 0);
    }
  }

  for (let level = 1; level <= 3; level++) {
    if (!showLevels[level]) continue;
    datasets.push({
      label: 'Bid L' + level,
      data: d['bp'+level],
      borderColor: bidColors[level-1],
      backgroundColor: bidColors[level-1] + (level === 1 ? 'cc' : '55'),
      pointRadius: d['bv'+level].map(v => Math.max(1, Math.min(4, (v||0)/maxVol*6))),
      pointStyle: 'rect',
      showLine: level === 1,
      borderWidth: level === 1 ? 1 : 0,
      fill: false,
    });
    datasets.push({
      label: 'Ask L' + level,
      data: d['ap'+level],
      borderColor: askColors[level-1],
      backgroundColor: askColors[level-1] + (level === 1 ? 'cc' : '55'),
      pointRadius: d['av'+level].map(v => Math.max(1, Math.min(4, (v||0)/maxVol*6))),
      pointStyle: 'rect',
      showLine: level === 1,
      borderWidth: level === 1 ? 1 : 0,
      fill: false,
    });
  }

  // Mid line
  datasets.push({
    label: 'Mid',
    data: d.mid,
    borderColor: '#fbbf24',
    borderWidth: 1.5,
    pointRadius: 0,
    fill: false,
  });

  return { labels: d.ts, datasets };
}

function renderAll() {
  buildStats();

  const firstLabel = runLabels[0];
  const d = allChartData[firstLabel]?.[currentProduct];
  if (!d) return;

  // Price chart
  if (priceChart) priceChart.destroy();
  priceChart = new Chart(document.getElementById('priceChart'), {
    type: 'line',
    data: buildPriceData(),
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { boxWidth: 8, font: { size: 10 } } },
        tooltip: {
          callbacks: {
            title: items => 't=' + d.ts[items[0].dataIndex],
            afterBody: items => {
              const i = items[0].dataIndex;
              return [
                'Bid: ' + (d.bp1[i]||'-') + ' (' + (d.bv1[i]||0) + ')',
                'Ask: ' + (d.ap1[i]||'-') + ' (' + (d.av1[i]||0) + ')',
                'Spread: ' + ((d.ap1[i]||0) - (d.bp1[i]||0)),
                'Pos: ~' + (d.pos[i]||0),
              ];
            }
          }
        }
      },
      scales: {
        x: { display: false },
        y: { grid: { color: '#1e293b' } }
      },
      onHover: (e, els) => {
        if (els.length) {
          const i = els[0].index;
          document.getElementById('hoverInfo').textContent =
            't=' + d.ts[i] + '  mid=' + (d.mid[i]||'-') +
            '  spread=' + ((d.ap1[i]||0)-(d.bp1[i]||0)) + '  pos~' + (d.pos[i]||0);
        }
      }
    }
  });

  // PNL chart
  if (pnlChart) pnlChart.destroy();
  const pnlDatasets = runLabels.map((label, idx) => {
    const rd = allChartData[label]?.[currentProduct];
    if (!rd) return null;
    return {
      label: isCompare ? label : 'PNL',
      data: rd.pnl,
      borderColor: isCompare ? runColors[idx % runColors.length] : '#22c55e',
      backgroundColor: (isCompare ? runColors[idx % runColors.length] : '#22c55e') + '11',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: !isCompare,
    };
  }).filter(Boolean);

  pnlChart = new Chart(document.getElementById('pnlChart'), {
    type: 'line',
    data: { labels: d.ts, datasets: pnlDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: isCompare, position: 'top', labels: { boxWidth: 8, font: { size: 10 } } },
        tooltip: { callbacks: { title: items => 't=' + d.ts[items[0].dataIndex] } }
      },
      scales: {
        x: { display: false },
        y: { grid: { color: '#1e293b' }, ticks: { callback: v => v.toFixed(0) } }
      },
      onHover: (e, els) => {
        if (els.length) {
          const i = els[0].index;
          const txt = runLabels.map(l => {
            const rd = allChartData[l]?.[currentProduct];
            return rd ? (l + ': ' + rd.pnl[i].toFixed(1)) : '';
          }).filter(Boolean).join(' | ');
          document.getElementById('pnlInfo').textContent = txt;
        }
      }
    }
  });

  // Position chart
  if (posChart) posChart.destroy();
  const posDatasets = runLabels.map((label, idx) => {
    const rd = allChartData[label]?.[currentProduct];
    if (!rd) return null;
    return {
      label: isCompare ? label : 'Position',
      data: rd.pos,
      borderColor: isCompare ? runColors[idx % runColors.length] : '#a78bfa',
      backgroundColor: (isCompare ? runColors[idx % runColors.length] : '#a78bfa') + '11',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: !isCompare,
      stepped: 'middle',
    };
  }).filter(Boolean);

  posChart = new Chart(document.getElementById('posChart'), {
    type: 'line',
    data: { labels: d.ts, datasets: posDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: isCompare, position: 'top', labels: { boxWidth: 8, font: { size: 10 } } },
      },
      scales: {
        x: { display: false },
        y: { grid: { color: '#1e293b' }, suggestedMin: -80, suggestedMax: 80,
             ticks: { callback: v => v.toFixed(0) } }
      },
      onHover: (e, els) => {
        if (els.length) {
          const i = els[0].index;
          const txt = runLabels.map(l => {
            const rd = allChartData[l]?.[currentProduct];
            return rd ? (l + ': ' + rd.pos[i]) : '';
          }).filter(Boolean).join(' | ');
          document.getElementById('posInfo').textContent = txt;
        }
      }
    }
  });
}

renderAll();
</script>
</body></html>"""

    return html


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args[0] == "--market":
        # Market data mode
        products, trades = load_market_data()
        stats = {}
        for p in products:
            mids = [e["mid"] for e in products[p] if e["mid"]]
            spreads = [(e["ap1"] or 0) - (e["bp1"] or 0) for e in products[p] if e["bp1"] and e["ap1"]]
            returns = [mids[i+1] - mids[i] for i in range(len(mids)-1)]
            mean_r = sum(returns) / len(returns) if returns else 0
            var_r = sum((r - mean_r)**2 for r in returns) / len(returns) if returns else 0
            autocorr = 0
            if var_r > 0 and len(returns) > 10:
                cov = sum((returns[i] - mean_r) * (returns[i+1] - mean_r)
                          for i in range(len(returns)-1)) / (len(returns)-1)
                autocorr = cov / var_r

            stats[p] = {
                "final_pnl": 0, "max_pnl": 0, "min_pnl": 0, "max_drawdown": 0,
                "trades": len(trades.get(p, [])),
                "wins": 0, "losses": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                "mid_range": f"{min(mids):.0f}-{max(mids):.0f}" if mids else "N/A",
                "avg_spread": round(sum(spreads) / len(spreads), 1) if spreads else 0,
                "autocorr": round(autocorr, 3),
            }

        runs = [("market", 0, products, stats)]
        html = generate_html(runs, mode="market")
        out = os.path.join(os.path.dirname(__file__), "dashboard_market.html")
    else:
        # Result mode (single or compare)
        runs = []
        for filepath in args:
            label = os.path.basename(filepath).replace(".json", "")
            profit, products = parse_result(filepath)
            stats = {p: compute_stats(entries) for p, entries in products.items()}
            runs.append((label, profit, products, stats))

        html = generate_html(runs, mode="result")
        out = os.path.join(os.path.dirname(__file__), "dashboard.html")

    with open(out, "w") as f:
        f.write(html)

    print(f"Saved: {out}")
    webbrowser.open("file://" + os.path.abspath(out))


if __name__ == "__main__":
    main()
