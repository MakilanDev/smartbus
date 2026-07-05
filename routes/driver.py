from datetime import datetime
from flask import Blueprint, render_template, session, abort
from services.auth import role_required
from services.database import db

driver_bp = Blueprint("driver", __name__, url_prefix="/driver")


def _fmt_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%I:%M %p")
    except Exception:
        return "—"


def _enrich_schedule(s):
    route = db.one("routes", id=s.get("route_id"))
    bus = db.one("buses", id=s.get("bus_id"))
    trip = db.ensure_trip(s["id"])
    return {**s, "route": route, "bus": bus, "trip_id": trip["id"] if trip else None, "departure_label": _fmt_time(s.get("departure_time"))}


@driver_bp.get("/dashboard")
@role_required("driver")
def dashboard():
    d = db.one("drivers", user_id=session["user_id"])
    schedules = [_enrich_schedule(s) for s in db.all("schedules", driver_id=d["id"])] if d else []
    return render_template("driver/dashboard.html", schedules=schedules)


@driver_bp.get("/trip/<trip_id>")
@role_required("driver")
def trip(trip_id):
    t = db.one("trips", id=trip_id) or {"id": trip_id, "status": "scheduled"}
    schedule = db.one("schedules", id=t.get("schedule_id")) if t.get("schedule_id") else None

    # A trip page only ever belongs to the driver it was allocated to — any
    # other logged-in driver is refused, not just quietly shown the page.
    driver_row = db.one("drivers", user_id=session["user_id"])
    is_owner = bool(schedule) and bool(driver_row) and schedule.get("driver_id") == driver_row["id"]
    if schedule and not is_owner:
        abort(403)

    route = db.one("routes", id=schedule.get("route_id")) if schedule else None
    bus = db.one("buses", id=schedule.get("bus_id")) if schedule else None
    driver_user = db.one("users", id=driver_row.get("user_id")) if driver_row else None
    stops = db.route_stops_sorted(route["id"]) if route else []
    return render_template(
        "driver/trip.html",
        trip=t,
        schedule=schedule,
        route=route,
        bus=bus,
        stops=stops,
        driver_name=driver_user.get("full_name") if driver_user else "Driver",
        departure_label=_fmt_time(schedule.get("departure_time")) if schedule else "—",
        started_label=_fmt_time(t.get("started_at")) if t.get("started_at") else None,
        is_owner=is_owner,
    )
