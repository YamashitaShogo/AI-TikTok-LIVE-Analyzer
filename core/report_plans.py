"""Plan/feature mapping for the unattended observation report.

DESIGN ONLY in this phase: enforcement is OFF by default and nothing
here restricts any feature. The mapping exists so a future licensing
change can gate features per plan without reworking call sites.

To experiment locally, set LIVEMETRY_PLAN_ENFORCEMENT=1 and
LIVEMETRY_PLAN=free|pro|agency. Shipped builds leave both unset, so
every feature stays available (spec: do not enable plan restrictions
or billing decisions unilaterally).
"""
import os

PLANS = ("free", "pro", "agency")

FEATURES = {
    "report.basic": {"label": "無人観測レポート（基本統計）", "min_plan": "free"},
    "report.charts": {"label": "スコア・視聴者数グラフ", "min_plan": "free"},
    "report.json_csv": {"label": "JSON / CSV 出力", "min_plan": "free"},
    "report.pdf": {"label": "PDF出力", "min_plan": "pro"},
    "report.compare": {"label": "前回レポートとの比較", "min_plan": "pro"},
    "report.ai": {"label": "AI改善提案", "min_plan": "pro"},
    "report.multi_streamer": {"label": "複数配信者の比較レポート", "min_plan": "agency"},
    "report.agency_rollup": {"label": "事務所向け集計", "min_plan": "agency"},
}


def enforcement_enabled():
    return os.environ.get("LIVEMETRY_PLAN_ENFORCEMENT") == "1"


def current_plan():
    plan = str(os.environ.get("LIVEMETRY_PLAN") or "free").lower()
    return plan if plan in PLANS else "free"


def feature_allowed(feature, plan=None):
    """True unless enforcement is explicitly enabled and plan is short."""
    if not enforcement_enabled():
        return True
    info = FEATURES.get(feature)
    if info is None:
        return True
    plan = plan or current_plan()
    return PLANS.index(plan) >= PLANS.index(info["min_plan"])
