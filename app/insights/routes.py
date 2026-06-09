from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Insight, InsightEvidence, utcnow

insights_bp = Blueprint("insights", __name__, url_prefix="/insights")


def _normalise(value):
    return (value or "").strip().lower()


def _insight_theme(insight):
    raw = insight.business_area or insight.category or insight.insight_type or "Unclassified"
    key = _normalise(raw)

    if "workforce" in key or "hr" in key or "recruit" in key:
        return "Workforce"
    if "finance" in key or "cost" in key or "pay" in key:
        return "Finance"
    if "operation" in key or "service" in key or "delivery" in key:
        return "Operations"
    if "compliance" in key or "quality" in key or "regulation" in key:
        return "Compliance"
    if "commercial" in key or "contract" in key or "buyer" in key:
        return "Commercial"
    if "technology" in key or "systems" in key or "it" == key:
        return "Technology"
    if "exit" in key or "diligence" in key or "pe" in key:
        return "Exit Readiness"
    if "risk" in key or "governance" in key:
        return "Risk & Governance"
    return raw


def _is_high_value(insight):
    severity = _normalise(insight.severity)
    confidence = _normalise(insight.confidence)
    buyer_relevance = _normalise(insight.buyer_relevance)
    status = _normalise(insight.status)

    if status in {"closed", "dismissed"}:
        return False
    return (
        severity in {"red", "critical", "high"}
        or confidence == "high"
        or "high" in buyer_relevance
        or "buyer" in buyer_relevance
        or "exit" in buyer_relevance
    )


@insights_bp.route("/")
@login_required
def index():
    items = Insight.query.order_by(Insight.created_at.desc()).all()

    themes = {}
    for insight in items:
        theme = _insight_theme(insight)
        themes.setdefault(theme, []).append(insight)

    high_value = [insight for insight in items if _is_high_value(insight)]
    open_items = [insight for insight in items if _normalise(insight.status) not in {"closed", "dismissed"}]

    stats = {
        "total": len(items),
        "open": len(open_items),
        "high_value": len(high_value),
        "themes": len(themes),
        "monitoring": len([insight for insight in items if _normalise(insight.status) == "monitoring"]),
        "closed": len([insight for insight in items if _normalise(insight.status) in {"closed", "dismissed"}]),
    }

    return render_template(
        "insights/index.html",
        insights=items,
        themes=themes,
        high_value=high_value[:12],
        stats=stats,
    )


@insights_bp.route("/<int:insight_id>")
@login_required
def detail(insight_id):
    insight = Insight.query.get_or_404(insight_id)
    evidence_items = (
        InsightEvidence.query
        .filter_by(insight_id=insight.id)
        .order_by(InsightEvidence.created_at.desc())
        .all()
    )
    return render_template("insights/detail.html", insight=insight, evidence_items=evidence_items)


@insights_bp.route("/<int:insight_id>/status/<status>", methods=["POST"])
@login_required
def update_status(insight_id, status):
    insight = Insight.query.get_or_404(insight_id)

    allowed = {"open", "monitoring", "closed", "dismissed"}
    if status not in allowed:
        flash("Invalid insight status.", "error")
        return redirect(url_for("insights.detail", insight_id=insight.id))

    insight.status = status
    insight.updated_at = utcnow()
    db.session.commit()

    flash("Insight status updated.", "success")
    return redirect(url_for("insights.detail", insight_id=insight.id))
