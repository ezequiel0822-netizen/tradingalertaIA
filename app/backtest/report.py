"""Reporte del Backtest Replay Harness (ESPEC §11 / §12).

Lee los backtest_trades de un run y genera, en exports/backtest_<run_id>/:
  - report.md  : resumen del run, tabla global por estrategia, slices por
                 simbolo/sesion/direccion/año/regime_trend/regime_vol (marca
                 [OK] solo slices con n >= 30), context completeness (B11) y el
                 VEREDICTO por estrategia criterio por criterio (§11), con el
                 stress de costos ×1.5 presente.
  - trades.csv : todos los trades simulados.
  - equity_r.csv : curva de R_net acumulado por estrategia.

NO promueve nada: el reporte informa una decision humana. El backtest abre la
puerta de paper, nunca la de MT5 (§11).
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

from app.backtest.trade_simulator import net_r
from app.config.settings import Settings

SLICE_MIN_SAMPLES = 30  # igual filosofia que EDGE_SLICE_MIN_SAMPLES
SLICE_DIMENSIONS = ("symbol", "session", "direction", "year",
                    "regime_trend", "regime_vol")

# Criterios de aceptacion (§11), defaults.
MIN_SAMPLE = 150
MIN_EXPECTANCY_R = 0.10
STRESS_MIN_R = 0.0
MIN_YEARS_POSITIVE_FRAC = 0.60
MAX_DRAWDOWN_R = 25.0
MIN_PROFIT_FACTOR = 1.15

_TRADE_COLUMNS = (
    "id", "run_id", "config_id", "strategy", "symbol", "category", "direction",
    "signal_bar_utc", "entry_utc", "entry_price", "sl_initial", "tp_initial",
    "exit_utc", "exit_price", "exit_reason", "bars_held", "r_gross", "cost_r",
    "r_net", "mfe_r", "mae_r", "session", "regime_trend", "regime_vol", "year",
)


def generate_report(repository, run_id: int, settings: Settings,
                    out_base: str = "exports") -> dict:
    run = repository.fetch_backtest_run(run_id) or {}
    trades = repository.fetch_backtest_trades(run_id)
    out_dir = Path(out_base) / f"backtest_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_strategy[t["strategy"]].append(t)

    trades_csv = out_dir / "trades.csv"
    _write_trades_csv(trades_csv, trades)
    equity_csv = out_dir / "equity_r.csv"
    _write_equity_csv(equity_csv, by_strategy)

    report_md = out_dir / "report.md"
    report_md.write_text(
        _build_markdown(run, run_id, trades, by_strategy, settings),
        encoding="utf-8",
    )
    return {
        "report_md": str(report_md),
        "trades_csv": str(trades_csv),
        "equity_csv": str(equity_csv),
    }


# -- estadistica ----------------------------------------------------------


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _max_drawdown_r(r_nets: list[float]) -> float:
    """Maximo drawdown (en R) de la curva de R_net acumulado."""
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for r in r_nets:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return max_dd


def _profit_factor(r_nets: list[float]) -> float:
    gains = sum(r for r in r_nets if r > 0)
    losses = sum(-r for r in r_nets if r < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _top_trade_share(r_nets: list[float]) -> tuple[float, float]:
    """Cuanta de la ganancia BRUTA la cargan el mejor trade y el top-10. Si un
    solo trade explica casi todo, el 'edge' es un artefacto (data sintetica, un
    outlier), no una ventaja repetible. Es la defensa anti-autoengaño del reporte
    contra un avg/PF inflado por pocos monstruos."""
    gains = sorted((r for r in r_nets if r > 0), reverse=True)
    total = sum(gains)
    if total <= 0:
        return 0.0, 0.0
    return gains[0] / total, sum(gains[:10]) / total


def _stress_r_nets(trades: list[dict], settings: Settings) -> list[float]:
    out = []
    for t in trades:
        _, r_net = net_r(
            float(t["r_gross"]), float(t["entry_price"]), float(t["sl_initial"]),
            str(t["category"]), settings, stress=True,
        )
        out.append(r_net)
    return out


def _slice_rows(trades: list[dict], dimension: str) -> list[tuple]:
    groups: dict = defaultdict(list)
    for t in trades:
        groups[t.get(dimension)].append(float(t["r_net"]))
    rows = []
    for value, r_nets in sorted(groups.items(), key=lambda kv: str(kv[0])):
        rows.append((value, len(r_nets), _avg(r_nets)))
    return rows


# -- veredicto (§11) ------------------------------------------------------


def evaluate_verdict(trades: list[dict], settings: Settings) -> dict:
    """Evalua una estrategia contra los criterios del §11, criterio por criterio."""
    r_nets = [float(t["r_net"]) for t in sorted(trades, key=lambda t: t["entry_utc"])]
    n = len(r_nets)
    stress_avg = _avg(_stress_r_nets(trades, settings))

    # consistencia temporal: % de años con sum positiva + ambas mitades positivas
    by_year: dict = defaultdict(float)
    for t in trades:
        by_year[t.get("year")] += float(t["r_net"])
    years = list(by_year.values())
    years_pos_frac = (
        sum(1 for s in years if s > 0) / len(years) if years else 0.0
    )
    half = n // 2
    first_half_pos = sum(r_nets[:half]) > 0 if half else False
    second_half_pos = sum(r_nets[half:]) > 0 if n - half else False
    temporal_ok = years_pos_frac >= MIN_YEARS_POSITIVE_FRAC and first_half_pos and second_half_pos

    avg = _avg(r_nets)
    max_dd = _max_drawdown_r(r_nets)
    pf = _profit_factor(r_nets)

    criteria = [
        ("Muestra (n>=150)", n >= MIN_SAMPLE, f"n={n}"),
        ("Expectancy (avg R neto >= +0.10, x1.25)", avg >= MIN_EXPECTANCY_R, f"avg={avg:+.3f}R"),
        ("Stress de costos (avg R neto >= 0, x1.5)", stress_avg >= STRESS_MIN_R, f"avg_x1.5={stress_avg:+.3f}R"),
        ("Consistencia temporal (>=60% años + ambas mitades)", temporal_ok,
         f"años+={years_pos_frac:.0%}, mitades={'OK' if first_half_pos and second_half_pos else 'NO'}"),
        ("Drawdown (max DD <= 25R)", max_dd <= MAX_DRAWDOWN_R, f"maxDD={max_dd:.2f}R"),
        ("Profit factor (>=1.15)", pf >= MIN_PROFIT_FACTOR, f"PF={pf:.2f}"),
        ("Robustez de vecindad", None, "N/A (Modo A: 1 config, sin grid)"),
    ]
    passed = all(ok for _, ok, _ in criteria if ok is not None)
    return {"n": n, "avg_r_net": avg, "passes": passed, "criteria": criteria}


# -- salida ---------------------------------------------------------------


def _write_trades_csv(path: Path, trades: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_TRADE_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            writer.writerow(t)


def _write_equity_csv(path: Path, by_strategy: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["strategy", "trade_index", "entry_utc", "r_net", "cum_r_net"])
        for strategy, trades in by_strategy.items():
            cum = 0.0
            for i, t in enumerate(sorted(trades, key=lambda x: x["entry_utc"])):
                cum += float(t["r_net"])
                writer.writerow([strategy, i, t["entry_utc"], t["r_net"], round(cum, 6)])


def _build_markdown(run, run_id, trades, by_strategy, settings) -> str:
    lines: list[str] = []
    lines.append(f"# Backtest Replay — run {run_id} (Modo {run.get('mode', '?')})")
    lines.append("")

    # Banner de SURVIVORSHIP BIAS para runs de acciones (ESPEC_BACKTEST_STOCKS §2).
    cfg = _safe_json(run.get("config_json"))
    is_stock = str(cfg.get("category", "")) == "stock" or any(
        str(t.get("category")) == "stock" for t in trades
    )
    if is_stock:
        lines.append("> ⚠️ **SESGO DE SUPERVIVENCIA.** Este run usa el universo de acciones")
        lines.append("> ACTUAL — los nombres que quebraron / fueron delisted desaparecieron de")
        lines.append("> Yahoo. Backtestear sobre los SOBREVIVIENTES infla los resultados: nadie")
        lines.append("> sabia en el pasado cuales iban a sobrevivir. **Este reporte solo sirve")
        lines.append("> para DESCARTAR, nunca para confirmar.** 'Gana sobre sobrevivientes' NO es")
        lines.append("> edge. NO habilita paper por si solo: requiere decision humana consciente.")
        lines.append("")
    lines.append(f"- Timeframe: **{run.get('timeframe', '?')}**")
    lines.append(f"- Simbolos: {run.get('symbols', '?')}")
    lines.append(f"- Estrategias: {run.get('strategies', '?')}")
    lines.append(f"- Cost multiplier: ×{run.get('cost_multiplier', '?')} "
                 f"(stress ×{settings.backtest_stress_cost_multiplier})")
    lines.append(f"- n_configs_tested: {run.get('n_configs_tested', '?')} "
                 "(Modo A: 1 config por estrategia — sin data-dredging)")
    lines.append(f"- Trades simulados: **{len(trades)}**")
    lines.append("")

    # rango real de data por simbolo
    ranges = _safe_json(run.get("data_ranges_json"))
    if ranges:
        lines.append("## Profundidad de data por simbolo")
        lines.append("")
        lines.append("| symbol | bars | nota |")
        lines.append("|---|---|---|")
        for sym, info in ranges.items():
            lines.append(f"| {sym} | {info.get('bars', '?')} | {info.get('note', '')} |")
        lines.append("")

    # tabla global por estrategia
    lines.append("## Global por estrategia (R neto, costos ×1.25)")
    lines.append("")
    lines.append("| estrategia | n | avg R | mediana R | win% | sum R | maxDD R | PF |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for strategy in sorted(by_strategy):
        ts = by_strategy[strategy]
        r = [float(t["r_net"]) for t in sorted(ts, key=lambda x: x["entry_utc"])]
        wins = sum(1 for x in r if x > 0)
        pf = _profit_factor(r)
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        lines.append(
            f"| {strategy} | {len(r)} | {_avg(r):+.3f} | {_median(r):+.3f} | "
            f"{(wins / len(r) * 100 if r else 0):.0f}% | {sum(r):+.2f} | "
            f"{_max_drawdown_r(r):.2f} | {pf_s} |"
        )
    lines.append("")

    # concentracion: anti-autoengaño contra un avg/PF inflado por pocos outliers
    lines.append("## Concentracion (robustez del resultado)")
    lines.append("")
    lines.append("Que parte de la ganancia BRUTA cargan el mejor trade y el top-10. "
                 "Si un solo trade explica casi todo, el 'edge' es un artefacto "
                 "(data sintetica / outlier), no una ventaja repetible.")
    lines.append("")
    lines.append("| estrategia | mejor trade % | top-10 % | aviso |")
    lines.append("|---|---|---|---|")
    for strategy in sorted(by_strategy):
        r = [float(t["r_net"]) for t in by_strategy[strategy]]
        top1, top10 = _top_trade_share(r)
        warn = "ARTEFACTO: 1 trade carga el resultado" if top1 >= 0.5 else (
            "concentrado" if top10 >= 0.8 else "")
        lines.append(f"| {strategy} | {top1 * 100:.0f}% | {top10 * 100:.0f}% | {warn} |")
    lines.append("")

    # slices por estrategia
    for strategy in sorted(by_strategy):
        ts = by_strategy[strategy]
        lines.append(f"## Slices — {strategy}")
        lines.append("")
        for dim in SLICE_DIMENSIONS:
            lines.append(f"**{dim}**")
            lines.append("")
            lines.append("| valor | n | avg R neto | |")
            lines.append("|---|---|---|---|")
            for value, count, avg in _slice_rows(ts, dim):
                ok = "[OK]" if count >= SLICE_MIN_SAMPLES else ""
                lines.append(f"| {value} | {count} | {avg:+.3f} | {ok} |")
            lines.append("")

    # context completeness (B11)
    lines.append("## Context completeness (B11)")
    lines.append("")
    lines.append("En v1 cada contexto poblo **price + candles + pattern**; "
                 "**pro/news/macro = None** (sin registro historico) ⇒ 50%. "
                 "Prohibido inventar valores historicos.")
    lines.append("")

    # veredicto por estrategia (§11)
    lines.append("## VEREDICTO por estrategia (§11)")
    lines.append("")
    for strategy in sorted(by_strategy):
        verdict = evaluate_verdict(by_strategy[strategy], settings)
        head = "PASA" if verdict["passes"] else "NO PASA"
        lines.append(f"### {strategy}: **{head}** (n={verdict['n']}, avg={verdict['avg_r_net']:+.3f}R)")
        lines.append("")
        lines.append("| criterio | resultado | detalle |")
        lines.append("|---|---|---|")
        for name, ok, detail in verdict["criteria"]:
            mark = "N/A" if ok is None else ("PASA" if ok else "NO PASA")
            lines.append(f"| {name} | {mark} | {detail} |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*El backtest abre la puerta de PAPER, nunca la de MT5. Prohibido "
                 "ajustar hasta que pase: si no cumple, se documenta y listo.*")
    return "\n".join(lines)


def _safe_json(raw):
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}
