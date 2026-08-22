"""
dhl_logistics_intelligence.py — Management analytics over logistics projection.

All calculations are projections over existing shipment / carrier / customs /
attention authorities. Does NOT:
  - create a second tracking or Delivered authority
  - invent opaque AI risk scores
  - hide data-quality exclusions
  - persist DHL cost / Rating warehouse
  - execute customs or financial actions
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import dhl_logistics_projector as projector
from . import dhl_logistics_targets as targets


# Deterministic attention → suggested action (advice only — never auto-executes).
_ATTENTION_ACTIONS: Dict[str, Dict[str, str]] = {
    "no_carrier_movement_12h": {
        "issue": "No carrier movement 12h+",
        "suggested_action": "Check DHL tracking / contact shipper or destination facility",
        "owner": "logistics",
        "risk": "action_required",
    },
    "expected_delivery_passed": {
        "issue": "ETA passed",
        "suggested_action": "Confirm delivery status with DHL; update consignee if delayed",
        "owner": "logistics",
        "risk": "action_required",
    },
    "missed_delivery_or_ready_for_collection": {
        "issue": "Awaiting consignee collection / missed delivery",
        "suggested_action": "Contact consignee to collect or rebook delivery",
        "owner": "logistics",
        "risk": "action_required",
    },
    "carrier_exception": {
        "issue": "Carrier exception",
        "suggested_action": "Review carrier exception text and resolve hold",
        "owner": "logistics",
        "risk": "critical",
    },
    "tracking_stale": {
        "issue": "Tracking stale / refresh failed",
        "suggested_action": "Refresh tracking cache; verify AWB is still valid",
        "owner": "logistics",
        "risk": "watch",
    },
    "dhl_email_received_dsk_missing": {
        "issue": "DHL email received, DSK missing",
        "suggested_action": "Generate / chase DSK for customs package",
        "owner": "customs",
        "risk": "action_required",
    },
    "poland_arrival_no_customs_progress": {
        "issue": "Poland arrival beyond target without customs progress",
        "suggested_action": "Confirm DHL customs email / start clearance workflow",
        "owner": "customs",
        "risk": "action_required",
    },
    "stage_age_critical": {
        "issue": "Time in stage critically high",
        "suggested_action": "Escalate with carrier or customs owner for this stage",
        "owner": "logistics",
        "risk": "critical",
    },
}

_RISK_RANK = {"critical": 0, "action_required": 1, "watch": 2, "normal": 3}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> Optional[datetime]:
    return projector._parse_iso(value)  # noqa: SLF001 — shared ISO parser


def _hours_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    return projector._hours_between(a, b)  # noqa: SLF001


def _fmt_duration(hours: Optional[float]) -> Optional[str]:
    return projector._fmt_duration(hours)  # noqa: SLF001


def _independent_groups(samples, tolerance_seconds):
    """Group samples that describe ONE physical terminating event.

    ``tolerance_seconds`` is None for every event type without a proven burst
    boundary; then each sample stands alone and this returns the population
    unchanged. That default is the whole point -- clustering is opt-in per
    terminating event, on published evidence, never a blanket rule.

    Ordering is by ``end_ts``: two terminating events closer together than the
    tolerance are one handover scanned twice. Samples without an ``end_ts``
    cannot be placed on the timeline and are each kept as their own observation
    rather than being swept into a neighbouring group.

    This is a STATISTICAL WEIGHT decision. It does not touch, rewrite or
    deduplicate any stored tracking event -- raw event identity belongs to
    ``tracking_normalizer._dedup_key`` and is not this layer's business.
    """
    if not samples:
        return []
    if not tolerance_seconds:
        return [[s] for s in samples]
    placed = sorted((s for s in samples if s.get("end_ts")), key=lambda s: s["end_ts"])
    loose = [[s] for s in samples if not s.get("end_ts")]
    groups = []
    for sample in placed:
        if groups and (sample["end_ts"] - groups[-1][-1]["end_ts"]).total_seconds() <= tolerance_seconds:
            groups[-1].append(sample)
        else:
            groups.append([sample])
    return groups + loose


def _per_group_typical(groups):
    """The median of per-group medians.

    A group is one observation however many parcels it was scanned as, so nine
    repeats of one slow handover no longer outvote four fast ones.
    """
    per_group = []
    for g in groups:
        hours = sorted(float(x["hours"]) for x in g)
        mid = len(hours) // 2
        per_group.append(hours[mid] if len(hours) % 2 else (hours[mid - 1] + hours[mid]) / 2.0)
    if not per_group:
        return None
    per_group.sort()
    mid = len(per_group) // 2
    value = per_group[mid] if len(per_group) % 2 else (per_group[mid - 1] + per_group[mid]) / 2.0
    return round(float(value), 2)


def _cohort_stats(hours_list: List[float]) -> Dict[str, Any]:
    return projector._cohort_stats(hours_list)  # noqa: SLF001


def _delta_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 1)


def _enrich_inbound_attention(row: Dict[str, Any], now: datetime) -> List[str]:
    """Extra deterministic inbound intervention signals (advice-only)."""
    extra: List[str] = []
    if row.get("classification") not in ("active", "exception"):
        return extra
    if row.get("direction") != "inbound":
        return extra

    tsmap = projector._row_timestamp_map(row)  # noqa: SLF001
    dhl_email = tsmap.get("dhl_email")
    dsk = tsmap.get("dsk")
    arrived = tsmap.get("arrived_pl")
    if dhl_email is not None and dsk is None:
        extra.append("dhl_email_received_dsk_missing")

    poland_target = targets.target_hours("poland_to_dhl_email") or 24.0
    if arrived is not None and dhl_email is None and dsk is None:
        age = _hours_between(arrived, now)
        if age is not None and age > poland_target:
            extra.append("poland_arrival_no_customs_progress")
    return extra


def _risk_for_row(row: Dict[str, Any], reasons: List[str], now: datetime) -> str:
    if row.get("classification") == "delivered":
        return "normal"
    if row.get("classification") not in ("active", "exception"):
        return "normal"

    ranks: List[int] = []
    for r in reasons:
        base = r.split(":", 1)[0]
        meta = _ATTENTION_ACTIONS.get(base) or _ATTENTION_ACTIONS.get(r)
        if meta:
            ranks.append(_RISK_RANK.get(meta["risk"], 3))
        elif r.startswith("exception:") or r.startswith("workflow:"):
            ranks.append(_RISK_RANK["critical"] if r.startswith("exception:") else _RISK_RANK["action_required"])

    stage_age = row.get("stage_age_hours")
    if isinstance(stage_age, (int, float)):
        if stage_age >= targets.STAGE_AGE_CRITICAL_HOURS:
            ranks.append(_RISK_RANK["critical"])
            if "stage_age_critical" not in reasons:
                reasons.append("stage_age_critical")
        elif stage_age >= targets.STAGE_AGE_ACTION_HOURS:
            ranks.append(_RISK_RANK["action_required"])
        elif stage_age >= targets.STAGE_AGE_WATCH_HOURS:
            ranks.append(_RISK_RANK["watch"])

    if row.get("classification") == "exception":
        ranks.append(_RISK_RANK["critical"])

    if not ranks:
        return "normal"
    best = min(ranks)
    for name, rank in _RISK_RANK.items():
        if rank == best:
            return name
    return "normal"


def _required_action(reasons: List[str]) -> Optional[str]:
    for r in reasons:
        base = r.split(":", 1)[0]
        meta = _ATTENTION_ACTIONS.get(base) or _ATTENTION_ACTIONS.get(r)
        if meta and meta["risk"] in ("action_required", "critical"):
            return meta["suggested_action"]
    for r in reasons:
        base = r.split(":", 1)[0]
        meta = _ATTENTION_ACTIONS.get(base)
        if meta:
            return meta["suggested_action"]
    return None


def build_operations_now(rows: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now_utc()
    out: List[Dict[str, Any]] = []
    for row in rows:
        reasons = list(row.get("attention_reasons") or [])
        reasons.extend(_enrich_inbound_attention(row, now))
        # de-dupe preserve order
        seen = set()
        uniq: List[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        reasons = uniq

        classification = row.get("classification")
        delivered = classification == "delivered"
        risk = _risk_for_row(row, reasons, now)

        op = {
            "direction": row.get("direction"),
            "party": row.get("party"),
            "party_role": row.get("party_role"),
            "party_authority": row.get("party_authority"),
            "awb": row.get("awb"),
            "batch_id": row.get("batch_id"),
            "current_stage": row.get("current_stage_label") or row.get("transport_status"),
            "location": row.get("current_location"),
            "last_movement": row.get("latest_event"),
            "last_movement_at_warsaw": row.get("latest_event_at_warsaw"),
            "time_in_stage_hours": None if delivered else row.get("stage_age_hours"),
            "time_in_stage_human": None if delivered else row.get("stage_age_human"),
            "total_transit_hours": row.get("total_elapsed_hours"),
            "total_transit_human": row.get("total_elapsed_human"),
            "eta_warsaw": row.get("expected_delivery_warsaw"),
            "risk": risk,
            "required_action": None if delivered else _required_action(reasons),
            "attention_reasons": reasons,
            "classification": classification,
            "lane_id": row.get("lane_id"),
            "explainability": [
                {"rule": r, "evidence": _evidence_for_reason(row, r)}
                for r in reasons
            ],
        }
        if delivered:
            op["delivered_frozen"] = True
            op["operational_attention"] = False
        else:
            op["delivered_frozen"] = False
            op["operational_attention"] = risk in ("action_required", "critical") or bool(row.get("needs_attention"))
        out.append(op)

    out.sort(
        key=lambda r: (
            _RISK_RANK.get(str(r.get("risk") or "normal"), 9),
            -(r.get("time_in_stage_hours") or 0),
            str(r.get("awb") or ""),
        )
    )
    return out


def _evidence_for_reason(row: Dict[str, Any], reason: str) -> Dict[str, Any]:
    base = reason.split(":", 1)[0]
    ev: Dict[str, Any] = {
        "awb": row.get("awb"),
        "classification": row.get("classification"),
        "stage_age_hours": row.get("stage_age_hours"),
        "transport_status": row.get("transport_status"),
    }
    if base == "expected_delivery_passed":
        ev["expected_delivery_utc"] = row.get("expected_delivery_utc")
    if base == "dhl_email_received_dsk_missing":
        ev["dhl_email_kpi_at_utc"] = row.get("dhl_email_kpi_at_utc")
        ev["dsk"] = None
    if reason.startswith("exception:"):
        ev["exception"] = reason.split(":", 1)[1]
    return ev


def build_intervention_queue(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank non-terminal shipments that require human action (advice only)."""
    queue: List[Dict[str, Any]] = []
    for op in operations:
        if op.get("classification") not in ("active", "exception"):
            continue
        if op.get("risk") not in ("action_required", "critical"):
            continue
        reasons = op.get("attention_reasons") or []
        primary = reasons[0] if reasons else "action_required"
        base = primary.split(":", 1)[0]
        meta = _ATTENTION_ACTIONS.get(base) or {
            "issue": primary,
            "suggested_action": op.get("required_action") or "Review shipment and decide next step",
            "owner": "logistics",
        }
        age = op.get("time_in_stage_hours")
        queue.append({
            "awb": op.get("awb"),
            "party": op.get("party"),
            "direction": op.get("direction"),
            "issue": meta["issue"],
            "evidence": (op.get("explainability") or [{}])[0].get("evidence") if op.get("explainability") else {},
            "attention_reasons": reasons,
            "age_hours": age,
            "age_human": op.get("time_in_stage_human"),
            "suggested_action": meta["suggested_action"],
            "action_is_advice_only": True,
            "owner": meta.get("owner") or "logistics",
            "risk": op.get("risk"),
        })
    queue.sort(
        key=lambda r: (
            _RISK_RANK.get(str(r.get("risk") or "normal"), 9),
            -(r.get("age_hours") or 0),
        )
    )
    return queue


def _transition_period_dto(
    samples: List[Dict[str, Any]],
    *,
    transition_id: str,
    label: str,
    now: datetime,
    terminating_event: Optional[str] = None,
    scope: str = "",
) -> Dict[str, Any]:
    target = targets.target_hours(transition_id)
    all_hours = [float(s["hours"]) for s in samples]
    all_stats = _cohort_stats(all_hours)

    cur_start = now - timedelta(days=30)
    prev_start = now - timedelta(days=60)
    current_samples = [s for s in samples if s.get("end_ts") and cur_start <= s["end_ts"] < now]
    current = [float(s["hours"]) for s in current_samples]

    # Statistical independence, by terminating event, on published evidence.
    tolerance = targets.independence_tolerance_seconds(terminating_event, scope)
    groups = _independent_groups(current_samples, tolerance)
    n_shipments = len(current_samples)
    n_independent = len(groups)
    independence_basis = (
        "burst_tolerance_%ds" % tolerance if tolerance else "exact_event"
    )
    inflation_ratio = (
        round(n_shipments / n_independent, 2) if n_independent else None
    )
    inflation_flagged = bool(
        tolerance
        and inflation_ratio is not None
        and inflation_ratio >= targets.INDEPENDENCE_INFLATION_FLAG_RATIO
    )
    ranking_typical = _per_group_typical(groups) if tolerance else None
    previous = [float(s["hours"]) for s in samples if s.get("end_ts") and prev_start <= s["end_ts"] < cur_start]
    cur_stats = _cohort_stats(current)
    prev_stats = _cohort_stats(previous)

    typical = all_stats.get("median") if all_stats.get("median") is not None else all_stats.get("average")
    excess_vs_target = None
    if target is not None and typical is not None:
        excess_vs_target = round(float(typical) - float(target), 2)

    cur_typical = cur_stats.get("median") if cur_stats.get("median") is not None else cur_stats.get("average")
    prev_typical = prev_stats.get("median") if prev_stats.get("median") is not None else prev_stats.get("average")

    # A period-over-period percentage is only as trustworthy as its denominator.
    # Measured 2026-08-22: booking->first movement showed +1526.8% against a
    # previous window holding a single shipment. The number was arithmetically
    # correct and told the reader nothing except that one shipment moved fast in
    # July. Below the floor the delta is withheld and the reason is stated.
    prev_n = prev_stats.get("n") or 0
    if prev_n < targets.DELTA_MIN_PREVIOUS_N:
        delta_pct = None
        delta_suppressed = "previous_window_n_%d_below_%d" % (prev_n, targets.DELTA_MIN_PREVIOUS_N)
    else:
        delta_pct = _delta_pct(cur_typical, prev_typical)
        delta_suppressed = None

    return {
        "id": transition_id,
        "label": label,
        "median": all_stats.get("median"),
        "median_human": all_stats.get("median_human"),
        "average": all_stats.get("average"),
        "average_human": all_stats.get("average_human"),
        "p75": all_stats.get("p75"),
        "p75_human": all_stats.get("p75_human"),
        "p90": all_stats.get("p90"),
        "p90_human": all_stats.get("p90_human"),
        "typical": typical,
        "typical_human": all_stats.get("typical_human"),
        "target_hours": target,
        "target_human": _fmt_duration(target),
        "target_source": "explicit_configured",
        "current_30d": {
            "n": cur_stats.get("n"),
            "median": cur_stats.get("median"),
            "average": cur_stats.get("average"),
            "typical": cur_typical,
            "typical_human": cur_stats.get("typical_human"),
            "p90": cur_stats.get("p90"),
        },
        "previous_30d": {
            "n": prev_stats.get("n"),
            "median": prev_stats.get("median"),
            "average": prev_stats.get("average"),
            "typical": prev_typical,
            "typical_human": prev_stats.get("typical_human"),
            "p90": prev_stats.get("p90"),
        },
        "delta_pct_vs_previous_30d": delta_pct,
        "delta_suppressed_reason": delta_suppressed,
        "excess_vs_target_hours": excess_vs_target,
        "n": all_stats.get("n"),
        # Both counts are always published. A bare N is what let one handover
        # scanned five times read as five observations.
        "n_shipments": n_shipments,
        "n_independent": n_independent,
        "independence_basis": independence_basis,
        "independence_tolerance_seconds": tolerance,
        "inflation_ratio": inflation_ratio,
        "inflation_flagged": inflation_flagged,
        "observation_noun": _observation_noun(terminating_event, n_independent),
        "ranking_typical": ranking_typical,
        "excluded_n": None,  # filled by caller from projector analytics when available
    }


# What the stage actually terminates on. A count is meaningless without its
# noun: "13" is not evidence, "6 collections" is.
_OBSERVATION_NOUNS = {
    "acceptance": ("collection", "collections"),
    "delivered": ("delivery", "deliveries"),
    "departed": ("departure", "departures"),
    "destination": ("arrival", "arrivals"),
    "first_movement": ("collection", "collections"),
    "pz": ("receipt", "receipts"),
}


def _observation_noun(terminating_event: Optional[str], n: int) -> str:
    singular, plural = _OBSERVATION_NOUNS.get(
        terminating_event or "", ("observation", "observations"))
    return singular if n == 1 else plural


_DATA_QUALITY_FIELDS = (
    "cohort_n",
    "excluded_n",
    "coverage_excluded_n",
    "contaminated_n",
    "contamination_pct",
    "clean_data_sufficient",
    "contamination_block_pct",
    "publishable",
    "not_publishable_reason",
)


def _attach_data_quality(dto: Dict[str, Any], base: Dict[str, Any]) -> None:
    """Copy the projector's measured data-quality verdict onto the stage DTO.

    The projector owns the exclusion arithmetic; this layer never recomputes it,
    it only carries it to the surface so the page can show the same numbers the
    ranking gates on.
    """
    for field in _DATA_QUALITY_FIELDS:
        dto[field] = base.get(field)
    dto["exclusion_reason_counts"] = base.get("exclusion_reason_counts") or {}


def build_transition_kpis(
    inbound_rows: List[Dict[str, Any]],
    outbound_rows: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    analytics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = now or _now_utc()
    analytics = analytics or {}

    inbound: Dict[str, Any] = {}
    for key, label, pair in projector._INBOUND_FIXED_TRANSITIONS:  # noqa: SLF001
        samples = projector.collect_transition_samples(inbound_rows, key, pair)  # noqa: SLF001
        dto = _transition_period_dto(
            samples, transition_id=key, label=label, now=now,
            terminating_event=pair.split("|")[-1], scope="inbound")
        base = (analytics.get("fixed_transitions_inbound") or {}).get(key) or {}
        _attach_data_quality(dto, base)
        inbound[key] = dto

    outbound: Dict[str, Any] = {}
    for key, label, pair in projector._OUTBOUND_FIXED_TRANSITIONS:  # noqa: SLF001
        samples = projector.collect_transition_samples(outbound_rows, key, pair)  # noqa: SLF001
        dto = _transition_period_dto(
            samples, transition_id=key, label=label, now=now,
            terminating_event=pair.split("|")[-1], scope="outbound")
        base = (analytics.get("fixed_transitions_outbound") or {}).get(key) or {}
        _attach_data_quality(dto, base)
        outbound[key] = dto

    return {"inbound": inbound, "outbound": outbound}


def _ranking_exclusion(dto: Dict[str, Any]) -> Optional[str]:
    """Why this stage may not be ranked as a bottleneck, or None if it may.

    A bottleneck claim is an instruction to go and fix something, so it has to
    survive four questions before it earns a rank:

      is the stage even measurable?   publishable == False -> no
      is it slow *now*?               ranked on the current 30-day window, not
                                      an all-time median that can be dominated
                                      by a backfill nobody is going to relive
      is it actually over target?     a stage beating target is not a bottleneck
      are there enough shipments?     one shipment is an anecdote

    Nothing is dropped silently: every exclusion here is returned to the caller
    and published as excluded_from_ranking.
    """
    if dto.get("publishable") is False:
        return dto.get("not_publishable_reason") or "not_publishable"
    cur = dto.get("current_30d") or {}
    # Where an independence authority exists for this terminating event, the
    # floor counts INDEPENDENT observations. Otherwise it counts what it always
    # counted -- a stage with no proven burst boundary keeps its semantics.
    if dto.get("independence_tolerance_seconds"):
        n_now = dto.get("n_independent") or 0
    else:
        n_now = cur.get("n") or 0
    if n_now < targets.BOTTLENECK_MIN_N:
        return "insufficient_recent_samples"
    if cur.get("typical") is None or dto.get("target_hours") is None:
        return "no_current_typical"
    if float(cur["typical"]) - float(dto["target_hours"]) <= 0:
        return "meeting_target"
    return None


def build_bottleneck_ranking(transition_kpis: Dict[str, Any]) -> Dict[str, Any]:
    """Rank the stages genuinely costing time right now.

    Returns {"ranked": [...], "excluded": [...]} — the excluded list is part of
    the answer, not debris. A ranking that quietly drops two thirds of the
    stages reads as "these are the only stages" and that is how a stage stops
    being looked at.
    """
    ranked: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for scope in ("inbound", "outbound"):
        for tid, dto in (transition_kpis.get(scope) or {}).items():
            reason = _ranking_exclusion(dto)
            if reason is not None:
                excluded.append({
                    "id": tid,
                    "scope": scope,
                    "label": dto.get("label"),
                    "reason": reason,
                    "n": dto.get("n"),
                    "current_30d_n": (dto.get("current_30d") or {}).get("n"),
                    "contamination_pct": dto.get("contamination_pct"),
                })
                continue

            cur = dto["current_30d"]
            # Where an independence authority exists, the stage is ranked on the
            # median of per-observation medians -- nine repeats of one slow
            # handover must not outvote four fast ones. Where it does not, the
            # existing row median stands unchanged.
            typical_for_rank = dto.get("ranking_typical")
            if typical_for_rank is None:
                typical_for_rank = cur.get("typical")
            excess = round(float(typical_for_rank) - float(dto["target_hours"]), 2)
            if excess <= 0:
                # Removing inflation can move a stage back under target. It is
                # then not a bottleneck, and saying so is the point.
                excluded.append({
                    "id": tid, "scope": scope, "label": dto.get("label"),
                    "reason": "meeting_target_on_independent_observations",
                    "n": dto.get("n"),
                    "current_30d_n": cur.get("n"),
                    "contamination_pct": dto.get("contamination_pct"),
                })
                continue
            n_now = dto.get("n_independent") or 0
            if not dto.get("independence_tolerance_seconds"):
                n_now = cur.get("n") or 0
            ranked.append({
                "id": tid,
                "scope": scope,
                "label": dto.get("label"),
                "excess_vs_target_hours": excess,
                "excess_human": _fmt_duration(excess),
                "n": n_now,
                "n_shipments": dto.get("n_shipments"),
                "n_independent": dto.get("n_independent"),
                "observation_noun": dto.get("observation_noun"),
                "independence_basis": dto.get("independence_basis"),
                "inflation_ratio": dto.get("inflation_ratio"),
                "inflation_flagged": dto.get("inflation_flagged"),
                "n_all_time": dto.get("n"),
                "window": "current_30d",
                "contribution_hours": round(excess * float(n_now), 2),
                "typical": cur.get("typical"),
                "typical_human": cur.get("typical_human"),
                "target_hours": dto.get("target_hours"),
                "delta_pct_vs_previous_30d": dto.get("delta_pct_vs_previous_30d"),
                "delta_suppressed_reason": dto.get("delta_suppressed_reason"),
                "improved": (
                    dto.get("delta_pct_vs_previous_30d") is not None
                    and dto["delta_pct_vs_previous_30d"] < 0
                ),
            })
    ranked.sort(key=lambda r: (-(r.get("contribution_hours") or 0), -(r.get("excess_vs_target_hours") or 0)))
    excluded.sort(key=lambda r: (r.get("scope") or "", r.get("id") or ""))
    return {"ranked": ranked, "excluded": excluded}


def _lane_id_for_row(row: Dict[str, Any]) -> str:
    if row.get("lane_id"):
        return str(row["lane_id"])
    origin = str(row.get("origin_country") or ("IN" if row.get("direction") == "inbound" else "PL")).upper()
    dest = str(row.get("destination_country") or ("PL" if row.get("direction") == "inbound" else "XX")).upper()
    if len(origin) != 2:
        origin = "XX"
    if len(dest) != 2:
        dest = "XX"
    return f"{origin}→{dest}"


def build_lane_performance(
    rows: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    now = now or _now_utc()
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("classification") != "delivered":
            continue
        hours = row.get("total_elapsed_hours")
        if not isinstance(hours, (int, float)) or hours < 0:
            continue
        lid = _lane_id_for_row(row)
        buckets.setdefault(lid, []).append(row)

    out: List[Dict[str, Any]] = []
    cur_start = now - timedelta(days=30)
    prev_start = now - timedelta(days=60)
    for lid, members in sorted(buckets.items()):
        hours_all = [float(r["total_elapsed_hours"]) for r in members]
        stats = _cohort_stats(hours_all)
        target = targets.lane_target_hours(lid)
        hits = 0
        if target is not None:
            hits = sum(1 for h in hours_all if h <= target)
        target_hit_pct = round(100.0 * hits / len(hours_all), 1) if hours_all and target is not None else None

        exceptions = sum(
            1 for r in members
            if (r.get("attention_reasons") or r.get("data_quality"))
        )
        exception_rate = round(100.0 * exceptions / len(members), 1) if members else None

        cur = [
            float(r["total_elapsed_hours"])
            for r in members
            if (_parse_iso(r.get("delivered_at_utc")) or datetime.min.replace(tzinfo=timezone.utc)) >= cur_start
        ]
        prev = [
            float(r["total_elapsed_hours"])
            for r in members
            if prev_start
            <= (_parse_iso(r.get("delivered_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))
            < cur_start
        ]
        cur_t = _cohort_stats(cur).get("median") or _cohort_stats(cur).get("average")
        prev_t = _cohort_stats(prev).get("median") or _cohort_stats(prev).get("average")

        out.append({
            "lane_id": lid,
            "n": stats.get("n"),
            "median_transit_hours": stats.get("median"),
            "median_human": stats.get("median_human"),
            "p90_hours": stats.get("p90"),
            "p90_human": stats.get("p90_human"),
            "target_hours": target,
            "target_human": _fmt_duration(target),
            "target_hit_pct": target_hit_pct,
            "exception_rate_pct": exception_rate,
            "trend_delta_pct": _delta_pct(cur_t, prev_t),
            "current_30d_n": len(cur),
            "previous_30d_n": len(prev),
        })
    out.sort(key=lambda r: (-(r.get("n") or 0), r.get("lane_id") or ""))
    return out


# Stage names a manager can act on. The statistical id stays the authority and
# is still what the Analyst view shows; this is presentation, not a second
# vocabulary - every key here is a real transition id, none is invented, and a
# stage with no entry falls back to its engineering label rather than vanishing.
BUSINESS_STAGE_LABELS: Dict[str, str] = {
    # Inbound
    "origin_pickup_to_poland": "India to Warsaw flight leg",
    "poland_to_dhl_email": "Waiting for DHL to send clearance paperwork",
    "dhl_email_to_dsk": "Waiting for DHL clearance paperwork",
    "dsk_to_agency_sad": "Customs agent filing",
    "sad_to_customs_cleared": "Customs clearance confirmation",
    "customs_cleared_to_pz": "Goods booked into warehouse",
    "sad_to_pz": "Goods booked into warehouse",
    "origin_pickup_to_delivered": "Whole import, pickup to delivered",
    # Outbound
    "booking_to_acceptance": "Label printed, DHL took the parcel",
    "acceptance_to_departure": "Sitting at Warsaw depot",
    "departure_to_destination": "Flight to destination country",
    "destination_to_delivered": "Last mile in destination country",
    "booking_to_delivered": "Whole export, booking to delivered",
    "booking_to_first_movement": "Label printed, DHL actually collected",
    "pickup_to_delivery": "Collection to delivery",
    "departure_to_delivery": "Departure to delivery",
}

# Why a step is not being shown, said the way an operator would say it.
NOT_MEASURABLE_REASONS: Dict[str, str] = {
    "insufficient_samples": "Not enough shipments have finished this step to say anything yet",
    "contaminated_ordering": "The timestamps for this step are recorded out of order, so any average would be wrong",
    "insufficient_recent_samples": "Too few shipments in the last 30 days to judge",
    "meeting_target": "Running at or under target",
    "no_current_typical": "No shipment finished this step in the last 30 days",
}


def business_label(transition_id: str, fallback: Optional[str] = None) -> str:
    return BUSINESS_STAGE_LABELS.get(transition_id) or fallback or transition_id


def build_management_summary(
    rows: List[Dict[str, Any]],
    operations: List[Dict[str, Any]],
    intervention: List[Dict[str, Any]],
    bottlenecks: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    transition_kpis: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The four questions a manager opens this page to answer.

    What needs me today, what is fine, where are we losing days, and how fast
    are imports running. Every number is a projection of a figure computed
    above - nothing is recomputed here, and no threshold is introduced that the
    Analyst view cannot show the workings of.
    """
    now = now or _now_utc()
    active = [o for o in operations if o.get("classification") in ("active", "exception")]
    needs_action = [o for o in active if o.get("risk") in ("critical", "action_required")]
    moving_normally = [o for o in active if o.get("risk") not in ("critical", "action_required")]

    # Days lost this month: for every import delivered in the current calendar
    # month, how far past the end-to-end import target it ran. Only overruns
    # count. An import that beat target does not earn back somebody else's
    # delay, and netting them off would hide both.
    target = targets.target_hours("origin_pickup_to_delivered")
    lost_hours = 0.0
    counted = 0
    for r in rows:
        if r.get("direction") != "inbound" or r.get("classification") != "delivered":
            continue
        delivered = _parse_iso(r.get("delivered_at_utc"))
        elapsed = r.get("total_elapsed_hours")
        if delivered is None or not isinstance(elapsed, (int, float)):
            continue
        if (delivered.year, delivered.month) != (now.year, now.month):
            continue
        counted += 1
        if target is not None and elapsed > target:
            lost_hours += float(elapsed) - float(target)

    top = bottlenecks[0] if bottlenecks else None
    import_dto = (transition_kpis.get("inbound") or {}).get("origin_pickup_to_delivered") or {}
    import_now = (import_dto.get("current_30d") or {}).get("typical")
    n_action = len(needs_action)
    n_normal = len(moving_normally)
    days_lost = round(lost_hours / 24.0, 1)
    plural = lambda n: "" if n == 1 else "s"

    return {
        "needs_action_now": {
            "count": n_action,
            "headline": (
                "%d shipment%s need%s attention today"
                % (n_action, plural(n_action), "s" if n_action == 1 else "")
                if n_action else "Nothing needs attention today"
            ),
        },
        "moving_normally": {
            "count": n_normal,
            "headline": "%d shipment%s moving normally" % (n_normal, plural(n_normal)),
        },
        "where_we_lose_days": {
            "stage": business_label(top["id"], top.get("label")) if top else None,
            "excess_hours": top.get("excess_vs_target_hours") if top else None,
            "excess_human": top.get("excess_human") if top else None,
            "shipments": top.get("n_shipments") if top else None,
            "independent_observations": top.get("n_independent") if top else None,
            "observation_noun": top.get("observation_noun") if top else None,
            "headline": _top_headline(top),
            "steps_not_measurable": len([
                e for e in excluded
                if e.get("reason") in (
                    "insufficient_samples", "contaminated_ordering",
                    "insufficient_recent_samples", "no_current_typical",
                )
            ]),
        },
        "import_speed": {
            "typical_hours": import_now,
            "typical_human": _fmt_duration(import_now),
            "target_hours": target,
            "target_human": _fmt_duration(target),
            "shipments": (import_dto.get("current_30d") or {}).get("n"),
            "on_target": (
                None if import_now is None or target is None else float(import_now) <= float(target)
            ),
        },
        "days_lost_this_month": {
            "days": days_lost,
            "hours": round(lost_hours, 1),
            "imports_counted": counted,
            "target_human": _fmt_duration(target),
            "headline": (
                "%s days lost this month across %d completed import%s"
                % (days_lost, counted, plural(counted))
            ),
        },
        "intervention_queue_count": len(intervention),
        "window_days": 30,
    }


def _top_headline(top: Optional[Dict[str, Any]]) -> str:
    """The one sentence a manager reads. It must not quote a bare N.

    "on 13 recent shipments" was true and misleading: those thirteen parcels
    were six collections. The count is named by what the stage terminates on,
    and where the two differ the sentence carries both, so nobody reads the
    parcel count as evidence of that many observations.
    """
    if not top:
        return "No step is provably running slow right now"
    stage = business_label(top["id"], top.get("label"))
    longer = top.get("excess_human") or ("%sh" % top.get("excess_vs_target_hours"))
    independent = top.get("n_independent") or 0
    shipments = top.get("n_shipments") or 0
    noun = top.get("observation_noun") or "observations"
    if top.get("independence_basis") == "exact_event" or independent == shipments:
        return "%s is taking %s longer than target, on %d recent %s" % (
            stage, longer, independent or shipments, noun)
    return "%s is taking %s longer than target, on %d %s (%d shipment%s)" % (
        stage, longer, independent, noun, shipments,
        "" if shipments == 1 else "s")


def build_cost_intelligence(outbound_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Quoted-cost feasibility only. Actual DHL cost remains unavailable.

    No Rating warehouse / persistence is created here.
    """
    quoted_rows: List[Dict[str, Any]] = []
    currencies_seen = set()
    for row in outbound_rows:
        # Carrier shipment may expose weight / declared value — never invent quote.
        q = row.get("quoted_cost")
        currency = row.get("quoted_cost_currency") or row.get("currency")
        if q is not None and currency:
            currencies_seen.add(str(currency).upper())
            weight = row.get("weight_kg")
            value = row.get("declared_value") or row.get("shipment_value")
            per_kg = None
            freight_pct = None
            if isinstance(q, (int, float)) and isinstance(weight, (int, float)) and weight > 0:
                per_kg = round(float(q) / float(weight), 2)
            if isinstance(q, (int, float)) and isinstance(value, (int, float)) and value > 0:
                freight_pct = round(100.0 * float(q) / float(value), 2)
            quoted_rows.append({
                "awb": row.get("awb"),
                "party": row.get("party"),
                "quoted_cost": q,
                "currency": str(currency).upper(),
                "service_product": row.get("service_product"),
                "destination_country": row.get("destination_country"),
                "weight_kg": weight,
                "shipment_value": value,
                "quote_per_kg": per_kg,
                "freight_pct_of_value": freight_pct,
                "label": "Quoted Cost",
                "is_actual_cost": False,
            })

    # Never merge cross-currency totals.
    totals_by_currency: Dict[str, float] = {}
    for r in quoted_rows:
        ccy = r["currency"]
        totals_by_currency[ccy] = round(totals_by_currency.get(ccy, 0.0) + float(r["quoted_cost"]), 2)

    return {
        "quoted_cost_available": bool(quoted_rows),
        "actual_cost_available": False,
        "actual_cost_gap": (
            "Actual DHL Cost unavailable until a durable billing/invoice authority exists. "
            "Do not treat MyDHL rates or estimates as actual charges."
        ),
        "quoted_cost_gap": (
            None
            if quoted_rows
            else (
                "Quoted DHL cost is not durably stored on carrier_shipments today "
                "(rates may be queried at booking). Display only when a valid quote "
                "authority is present on the row — no Rating warehouse created."
            )
        ),
        "cross_currency_merge": False,
        "totals_by_currency": totals_by_currency,
        "rows": quoted_rows,
        "section_title": "Quoted Cost",
        "actual_section_title": "Actual DHL Cost",
        "actual_section_status": "unavailable",
    }


def build_intelligence(
    *,
    all_rows: List[Dict[str, Any]],
    analytics: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or _now_utc()
    analytics = analytics or {}
    inbound = [r for r in all_rows if r.get("direction") == "inbound"]
    outbound = [r for r in all_rows if r.get("direction") == "outbound"]

    operations = build_operations_now(all_rows, now=now)
    intervention = build_intervention_queue(operations)
    transition_kpis = build_transition_kpis(inbound, outbound, now=now, analytics=analytics)
    ranking = build_bottleneck_ranking(transition_kpis)
    bottlenecks = ranking["ranked"]
    bottlenecks_excluded = ranking["excluded"]
    lanes = build_lane_performance(all_rows, now=now)
    cost = build_cost_intelligence(outbound)
    management = build_management_summary(
        all_rows, operations, intervention, bottlenecks, bottlenecks_excluded,
        transition_kpis, now=now,
    )

    active_ops = [o for o in operations if o.get("classification") in ("active", "exception")]
    slowest = sorted(
        [o for o in active_ops if isinstance(o.get("time_in_stage_hours"), (int, float))],
        key=lambda o: -(o.get("time_in_stage_hours") or 0),
    )[:15]

    dq = analytics.get("data_quality_summary") or {}

    return {
        "authority": {
            "timing_universe": "PR#1185 corrected dhl_logistics_projector (frozen)",
            "carrier_terminal": "canonical tracking_cache / is_carrier_tracking_terminal",
            "attention": "deterministic attention_reasons + explicit enrichment rules",
            "party": "supplier/customer masters + source-document fields (never clearance agency)",
            "targets": targets.TARGETS_AUTHORITY,
            "actions": "suggested_action is advice only — never auto-executes",
        },
        "targets": targets.targets_payload(),
        "executive_summary": {
            "operational_active": len(active_ops),
            "intervention_queue": len(intervention),
            "critical": sum(1 for o in active_ops if o.get("risk") == "critical"),
            "action_required": sum(1 for o in active_ops if o.get("risk") == "action_required"),
            "watch": sum(1 for o in active_ops if o.get("risk") == "watch"),
            "top_bottleneck": (bottlenecks[0]["label"] if bottlenecks else None),
            "top_bottleneck_excess_hours": (bottlenecks[0]["excess_vs_target_hours"] if bottlenecks else None),
            "top_bottleneck_n": (bottlenecks[0]["n"] if bottlenecks else None),
            "top_bottleneck_window": (bottlenecks[0]["window"] if bottlenecks else None),
            "stages_excluded_from_ranking": len(bottlenecks_excluded),
        },
        "operations_now": operations,
        "intervention_queue": intervention,
        "transit_performance": transition_kpis,
        "management_summary": management,
        "business_stage_labels": dict(BUSINESS_STAGE_LABELS),
        "not_measurable_reasons": dict(NOT_MEASURABLE_REASONS),
        "bottlenecks": bottlenecks,
        "bottlenecks_excluded": bottlenecks_excluded,
        "lane_performance": lanes,
        "slowest_current_shipments": slowest,
        "data_quality_notes": dq,
        "cost_intelligence": cost,
        "generated_at_utc": now.isoformat(),
    }


def attach_intelligence_to_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Augment a project_logistics payload with the intelligence block.

    Uses the unfiltered row population from analytics when available; otherwise
    falls back to payload rows (view-filtered). Prefer calling via project_logistics
    which passes the full population.
    """
    rows = payload.get("_intelligence_source_rows") or payload.get("rows") or []
    intel = build_intelligence(
        all_rows=rows,
        analytics=payload.get("analytics") or {},
        now=_parse_iso(payload.get("generated_at_utc")) or _now_utc(),
    )
    out = dict(payload)
    out["intelligence"] = intel
    out.pop("_intelligence_source_rows", None)
    return out
