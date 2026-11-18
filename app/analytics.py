"""Dashboard analytics with privacy rules built in.

Privacy rules (K_MIN = minimum group size, set in .env; agree the real number with the domain mentor)
1. A ward is shown on its own only if it has >= K_MIN released reports in the window; otherwise it is rolled
   up into its unit (department); if the unit is also too small it goes into "Other units (combined)".
2. A cluster (place + theme) is shown only if it has >= K_MIN reports; smaller ones are only counted.
3. Management sees raw text only for PATIENT reports (already masked). STAFF reports are shown as neutral
   AI summaries only, and with coarse dates (week), never exact day or time.
4. Staff reports can be held back by a random delay (STAFF_RELEASE_DELAY_HOURS) before they appear.
5. Room numbers are never stored; the ward is the smallest location.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import ai, config

OTHER_LABEL = "Other units (combined)"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def local_now():
    return datetime.now(timezone(timedelta(hours=5)))  # Asia/Tashkent


def time_bucket(dt=None) -> str:
    h = (dt or local_now()).hour
    if 6 <= h < 14:
        return "morning"
    if 14 <= h < 22:
        return "afternoon"
    return "night"


def week_start(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def load_wards(conn, clinic_id):
    return {r["code"]: {"name": r["name"], "unit": r["unit"]}
            for r in conn.execute("SELECT * FROM wards WHERE clinic_id=?", (clinic_id,))}


def window_reports(conn, clinic_id):
    """Released reports of ONE clinic in the dashboard window."""
    cutoff = (date.today() - timedelta(days=config.WINDOW_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT * FROM reports WHERE clinic_id = ? AND release_at <= ? AND created_day >= ? ORDER BY id DESC",
        (clinic_id, now_utc_iso(), cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


class Labeler:
    """Maps a ward to the label we are allowed to show (rule 1)."""

    def __init__(self, wards, reports):
        self.wards = wards
        self.ward_counts = Counter(r["ward_code"] for r in reports)
        self.unit_counts = Counter(wards[r["ward_code"]]["unit"] for r in reports if r["ward_code"] in wards)

    def label(self, ward_code):
        w = self.wards.get(ward_code)
        if not w:
            return OTHER_LABEL, "All"
        if self.ward_counts.get(ward_code, 0) >= config.K_MIN:
            return w["name"], w["unit"]
        if self.unit_counts.get(w["unit"], 0) >= config.K_MIN:
            return w["unit"], w["unit"]
        return OTHER_LABEL, "All"


def _public_text(r):
    """What management may see for a report (rule 3)."""
    if r["source"] == "patient":
        return r["text_masked"]
    return r["summary"]


def _public_day(r):
    if r["source"] == "patient":
        return r["created_day"]
    return "week of " + week_start(r["created_day"])


def build_dashboard(conn, clinic_id):
    wards = load_wards(conn, clinic_id)
    reports = window_reports(conn, clinic_id)
    lab = Labeler(wards, reports)

    # ---- clusters (place + theme) ------------------------------------------------------
    groups = defaultdict(list)
    for r in reports:
        label, unit = lab.label(r["ward_code"])
        groups[(label, unit, r["theme"])].append(r)

    clusters, hidden = [], 0
    for (label, unit, theme), rs in groups.items():
        if len(rs) < config.K_MIN:
            hidden += 1
            continue
        patients = [x for x in rs if x["source"] == "patient"]
        staff = [x for x in rs if x["source"] == "staff"]
        sev = [x["severity"] for x in rs]
        clusters.append({
            "key": f"{label}|{theme}",
            "label": label,
            "unit": unit,
            "theme": theme,
            "theme_name": ai.THEMES.get(theme, theme),
            "total": len(rs),
            "patient_count": len(patients),
            "staff_count": len(staff),
            "linked": bool(patients) and bool(staff),
            "max_severity": max(sev),
            "avg_severity": round(sum(sev) / len(sev), 1),
            "near_misses": sum(1 for x in rs if x["near_miss"]),
            "patient_examples": [x["text_masked"][:220] for x in patients[:3]],
            "staff_summaries": sorted({x["summary"] for x in staff})[:3],
            "categories": dict(Counter(ai.CATEGORIES[x["category"]][1] for x in rs).most_common(4)),
            "last_day": max(x["created_day"] for x in patients) if patients else None,
        })
    clusters.sort(key=lambda c: (not c["linked"], -c["total"], -c["max_severity"]))

    # ---- ward heat (rule 1) ------------------------------------------------------------
    heat = defaultdict(lambda: {"total": 0, "patient": 0, "staff": 0, "sev_sum": 0, "weeks": Counter()})
    for r in reports:
        label, _ = lab.label(r["ward_code"])
        h = heat[label]
        h["total"] += 1
        h[r["source"]] += 1
        h["sev_sum"] += r["severity"]
        h["weeks"][week_start(r["created_day"])] += 1
    this_week = date.today() - timedelta(days=date.today().weekday())
    week_keys = [(this_week - timedelta(weeks=i)).isoformat() for i in range(5, -1, -1)]
    heat_rows = [{
        "label": k,
        "total": v["total"],
        "patient": v["patient"],
        "staff": v["staff"],
        "avg_severity": round(v["sev_sum"] / v["total"], 1),
        "trend": [v["weeks"].get(w, 0) for w in week_keys],
    } for k, v in heat.items()]
    heat_rows.sort(key=lambda x: x["label"].lower())  # A-Z on purpose: never rank wards by report count

    # ---- early-warning radar: latest week above the ward's own usual level -----------------
    radar = []
    for row in heat_rows:
        past = row["trend"][:-1]
        recent = row["trend"][-1]
        base = sum(past) / max(1, len(past))
        if recent >= 3 and recent > 1.5 * max(base, 1):
            radar.append({"label": row["label"], "this_week": recent, "usual": round(base, 1)})

    # ---- urgent + feed -----------------------------------------------------------------
    def feed_item(r):
        label, _ = lab.label(r["ward_code"])
        return {
            "id": r["id"], "source": r["source"], "label": label,
            "category": ai.CATEGORIES[r["category"]][1], "theme": ai.THEMES.get(r["theme"], r["theme"]),
            "severity": r["severity"], "urgent": bool(r["urgent"]), "near_miss": bool(r["near_miss"]),
            "text": _public_text(r), "day": _public_day(r), "bucket": r["time_bucket"] if r["source"] == "patient" else None,
        }

    urgent = [feed_item(r) for r in reports if r["urgent"] and r["source"] == "patient"][:8]
    feed = [feed_item(r) for r in reports[:25]]

    # ---- actions -----------------------------------------------------------------------
    actions = [dict(a) for a in conn.execute(
        "SELECT * FROM actions WHERE clinic_id=? ORDER BY status ASC, id DESC", (clinic_id,))]

    return {
        "kpi": {
            "reports": len(reports),
            "patient": sum(1 for r in reports if r["source"] == "patient"),
            "staff": sum(1 for r in reports if r["source"] == "staff"),
            "urgent": len(urgent),
            "linked_clusters": sum(1 for c in clusters if c["linked"]),
            "open_actions": sum(1 for a in actions if a["status"] == "open"),
            "fixed": sum(1 for a in actions if a["status"] == "done"),  # headline: problems fixed, not reports
            "hidden_small_groups": hidden,
        },
        "clusters": clusters,
        "heat": heat_rows,
        "week_labels": week_keys,
        "radar": radar,
        "urgent": urgent,
        "feed": feed[:25],
        "actions": actions,
        "privacy": {"k_min": config.K_MIN, "window_days": config.WINDOW_DAYS,
                    "staff_delay_hours": config.STAFF_DELAY_HOURS},
        "ai_mode": "llm" if ai.llm_enabled() else "rules",
    }


def cluster_inputs(conn, clinic_id, key: str):
    """Texts of a cluster (masked patient texts, staff summaries) for root-cause help."""
    label, theme = key.rsplit("|", 1)
    wards = load_wards(conn, clinic_id)
    reports = window_reports(conn, clinic_id)
    lab = Labeler(wards, reports)
    mine = [r for r in reports if r["theme"] == theme and lab.label(r["ward_code"])[0] == label]
    patients = [r["text_masked"] for r in mine if r["source"] == "patient"]
    staff = sorted({r["summary"] for r in mine if r["source"] == "staff"})
    unit = next((lab.label(r["ward_code"])[1] for r in mine), "All")
    return label, unit, theme, patients, staff
