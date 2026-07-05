"""Reports & Analytics — trip performance, route KPIs, fuel & maintenance.

Everything is derived on-the-fly from the existing tables (trips, schedules,
routes, bookings, payments, fuel_logs, maintenance_logs) so no schema change
is required. PDF export uses ReportLab (already in requirements.txt).
"""
from datetime import datetime, timedelta, timezone, date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

from services.database import db


def _parse_iso(v):
    if not v:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.combine(date.fromisoformat(str(v)[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _range(period):
    now = datetime.now(timezone.utc)
    if period == "weekly":
        start = now - timedelta(days=7)
    elif period == "monthly":
        start = now - timedelta(days=30)
    elif period == "yearly":
        start = now - timedelta(days=365)
    else:
        start = now - timedelta(days=30)
    return start, now


def _in_window(dt, start, end):
    return dt is not None and start <= dt <= end


def analytics(period="monthly"):
    start, end = _range(period)
    schedules = {s["id"]: s for s in db.all("schedules")}
    routes = {r["id"]: r for r in db.all("routes")}
    buses = {b["id"]: b for b in db.all("buses")}
    models = {m["id"]: m for m in db.all("bus_models")}

    trips = db.all("trips")
    fuel_logs = db.all("fuel_logs")
    maintenance = db.all("maintenance_logs")
    bookings = db.all("bookings")
    payments = db.all("payments")

    trips_in = [t for t in trips if _in_window(
        _parse_iso(t.get("started_at") or (schedules.get(t.get("schedule_id"), {}) or {}).get("departure_time")),
        start, end,
    )]
    total_trips = len(trips_in)
    completed = [t for t in trips_in if t.get("status") == "completed"]
    cancelled = [t for t in trips_in if t.get("status") in ("cancelled", "breakdown")]
    on_time = [t for t in completed if int(t.get("delay_minutes") or 0) <= 5]
    completion_rate = round(100 * len(completed) / total_trips, 1) if total_trips else 0
    on_time_rate = round(100 * len(on_time) / len(completed), 1) if completed else 0
    avg_delay = round(sum(int(t.get("delay_minutes") or 0) for t in trips_in) / total_trips, 1) if total_trips else 0

    # per-route performance
    route_perf = {}
    for t in trips_in:
        sched = schedules.get(t.get("schedule_id"))
        if not sched:
            continue
        r = routes.get(sched.get("route_id"))
        if not r:
            continue
        key = f'{r["origin"]} → {r["destination"]}'
        rp = route_perf.setdefault(key, {"route": key, "trips": 0, "completed": 0, "delay_total": 0, "distance_km": float(r.get("distance_km") or 0)})
        rp["trips"] += 1
        if t.get("status") == "completed":
            rp["completed"] += 1
        rp["delay_total"] += int(t.get("delay_minutes") or 0)
    for rp in route_perf.values():
        rp["completion_rate"] = round(100 * rp["completed"] / rp["trips"], 1) if rp["trips"] else 0
        rp["avg_delay"] = round(rp["delay_total"] / rp["trips"], 1) if rp["trips"] else 0

    # fuel trends per day
    fuel_by_day = {}
    fuel_by_bus = {}
    total_litres = 0.0
    total_fuel_cost = 0.0
    for f in fuel_logs:
        d = _parse_iso(f.get("logged_at"))
        if not _in_window(d, start, end):
            continue
        day = d.date().isoformat()
        litres = float(f.get("litres") or 0)
        cost = float(f.get("cost") or 0)
        total_litres += litres
        total_fuel_cost += cost
        fuel_by_day.setdefault(day, {"day": day, "litres": 0, "cost": 0})
        fuel_by_day[day]["litres"] += litres
        fuel_by_day[day]["cost"] += cost
        bus_id = f.get("bus_id")
        # Older auto-generated fuel logs only have trip_id — resolve to bus.
        if not bus_id and f.get("trip_id"):
            trip = db.one("trips", id=f.get("trip_id"))
            sched = schedules.get(trip.get("schedule_id")) if trip else None
            bus_id = sched.get("bus_id") if sched else None
        if not bus_id:
            continue
        bus = buses.get(bus_id)
        model = models.get(bus.get("model_id")) if bus else None
        row = fuel_by_bus.setdefault(bus_id, {
            "bus": (bus.get("display_name") if bus else "—"),
            "registration": (bus.get("registration_no") if bus else "—"),
            "km_per_litre": float(model.get("km_per_litre") or 0) if model else 0,
            "litres": 0, "cost": 0,
        })
        row["litres"] += litres
        row["cost"] += cost

    # maintenance summary
    maint_in = [m for m in maintenance if _in_window(_parse_iso(m.get("starts_at") or m.get("created_at")), start, end)]
    maint_by_bus = {}
    total_maint_cost = 0.0
    for m in maint_in:
        c = float(m.get("cost") or 0)
        total_maint_cost += c
        bus = buses.get(m.get("bus_id"))
        row = maint_by_bus.setdefault(m.get("bus_id") or "unknown", {
            "bus": (bus.get("display_name") if bus else "—"),
            "registration": (bus.get("registration_no") if bus else "—"),
            "events": 0, "cost": 0,
        })
        row["events"] += 1
        row["cost"] += c

    # revenue vs bookings in window
    bookings_in = [b for b in bookings if _in_window(_parse_iso(b.get("created_at")), start, end)]
    paid = [p for p in payments if p.get("status") == "paid" and _in_window(_parse_iso(p.get("paid_at")), start, end)]
    revenue = sum(float(p.get("amount") or 0) for p in paid)

    return {
        "period": period,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "kpis": {
            "total_trips": total_trips,
            "completed": len(completed),
            "cancelled": len(cancelled),
            "completion_rate": completion_rate,
            "on_time_rate": on_time_rate,
            "avg_delay_minutes": avg_delay,
            "bookings": len(bookings_in),
            "revenue": round(revenue, 2),
            "total_litres": round(total_litres, 2),
            "total_fuel_cost": round(total_fuel_cost, 2),
            "total_maintenance_cost": round(total_maint_cost, 2),
        },
        "route_performance": sorted(route_perf.values(), key=lambda r: r["trips"], reverse=True),
        "fuel_by_day": sorted(fuel_by_day.values(), key=lambda r: r["day"]),
        "fuel_by_bus": sorted(fuel_by_bus.values(), key=lambda r: r["cost"], reverse=True),
        "maintenance_by_bus": sorted(maint_by_bus.values(), key=lambda r: r["cost"], reverse=True),
    }


# ---- PDF builder ---------------------------------------------------------
def _label(period):
    return {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Annual"}.get(period, period.title())


def build_pdf(period="monthly", section="all"):
    data = analytics(period)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=22, textColor=colors.HexColor("#0f766e"), spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#0f172a"), spaceBefore=14)
    meta = ParagraphStyle("meta", parent=styles["Normal"], textColor=colors.grey, fontSize=9)
    story = []

    title_map = {
        "trips": f"{_label(period)} Trip & Route Performance Report",
        "fuel": f"{_label(period)} Fuel Consumption Report",
        "maintenance": f"{_label(period)} Maintenance Report",
        "all": f"SmartBus {_label(period)} Operations Report",
    }
    story.append(Paragraph(title_map.get(section, title_map["all"]), h1))
    story.append(Paragraph(
        f"Range: {data['range_start'][:10]} to {data['range_end'][:10]}  ·  Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        meta))
    story.append(Spacer(1, 10))

    k = data["kpis"]
    if section in ("all", "trips"):
        kpi_rows = [
            ["Total trips", k["total_trips"], "Completed", k["completed"]],
            ["Completion rate", f"{k['completion_rate']}%", "On-time rate", f"{k['on_time_rate']}%"],
            ["Average delay", f"{k['avg_delay_minutes']} min", "Cancelled / breakdown", k["cancelled"]],
            ["Bookings", k["bookings"], "Revenue (LKR)", f"{k['revenue']:,.2f}"],
        ]
        t = Table(kpi_rows, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#065f46")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#065f46")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#a7f3d0")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#14b8a6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)

        story.append(Paragraph("Route performance", h2))
        rp_rows = [["Route", "Trips", "Completed", "Completion %", "Avg delay (min)", "Distance (km)"]]
        for rp in data["route_performance"] or []:
            rp_rows.append([rp["route"], rp["trips"], rp["completed"], f"{rp['completion_rate']}%",
                            rp["avg_delay"], rp["distance_km"]])
        if len(rp_rows) == 1:
            rp_rows.append(["No trip data in this period", "", "", "", "", ""])
        story.append(_grid(rp_rows))

    if section in ("all", "fuel"):
        story.append(Paragraph("Fuel consumption per vehicle", h2))
        fb_rows = [["Bus", "Registration", "Litres", "Cost (LKR)", "Rated km/L"]]
        for row in data["fuel_by_bus"] or []:
            fb_rows.append([row["bus"], row["registration"], f'{row["litres"]:.2f}',
                            f'{row["cost"]:,.2f}', row["km_per_litre"]])
        if len(fb_rows) == 1:
            fb_rows.append(["No fuel logs in this period", "", "", "", ""])
        story.append(_grid(fb_rows))

        story.append(Paragraph("Daily fuel trend", h2))
        d_rows = [["Date", "Litres", "Cost (LKR)"]]
        for row in data["fuel_by_day"] or []:
            d_rows.append([row["day"], f'{row["litres"]:.2f}', f'{row["cost"]:,.2f}'])
        if len(d_rows) == 1:
            d_rows.append(["No fuel usage recorded", "", ""])
        story.append(_grid(d_rows))
        story.append(Paragraph(
            f"Total litres: {k['total_litres']:.2f}   |   Total cost: LKR {k['total_fuel_cost']:,.2f}",
            styles["Normal"]))

    if section in ("all", "maintenance"):
        story.append(Paragraph("Maintenance summary per vehicle", h2))
        m_rows = [["Bus", "Registration", "Service events", "Cost (LKR)"]]
        for row in data["maintenance_by_bus"] or []:
            m_rows.append([row["bus"], row["registration"], row["events"], f'{row["cost"]:,.2f}'])
        if len(m_rows) == 1:
            m_rows.append(["No maintenance in this period", "", "", ""])
        story.append(_grid(m_rows))
        story.append(Paragraph(
            f"Total maintenance cost: LKR {k['total_maintenance_cost']:,.2f}", styles["Normal"]))

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This report supports SmartBus sustainability and operational decision-making by "
        "surfacing trip completion, on-time performance, fuel usage trends and per-vehicle "
        "maintenance costs. Use it in monthly reviews to identify high-consumption routes, "
        "under-performing schedules and vehicles due for service.",
        ParagraphStyle("body", parent=styles["Normal"], textColor=colors.grey, fontSize=9, leading=13)))

    doc.build(story)
    buf.seek(0)
    return buf


def _grid(rows):
    t = Table(rows, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#a7f3d0")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t
