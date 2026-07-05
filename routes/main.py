from datetime import datetime
from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from services.auth import login_required
from services.database import db

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def home():
    return render_template("home.html")


@main_bp.get("/route-search")
def search():
    return render_template("search.html", routes=db.all("routes"))


def _format_departure(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%A, %d %b"), parsed.strftime("%I:%M %p")
    except Exception:
        return "Travel date", "Departure time"


@main_bp.get("/booking")
def booking():
    schedule_id = request.args.get("schedule_id", "s1")
    s = db.one("schedules", id=schedule_id)
    route = bus = model = None
    fare = 0
    route_label = "Choose a route"
    travel_date = departure_time = "—"
    stops = []
    if s:
        route = db.one("routes", id=s.get("route_id"))
        bus = db.one("buses", id=s.get("bus_id"))
        model = db.one("bus_models", id=bus.get("model_id")) if bus else None
        fare = float(s.get("fare") or 0)
        travel_date, departure_time = _format_departure(s.get("departure_time"))
        if route:
            route_label = f'{route["origin"]} → {route["destination"]}'
        stops = db.route_stops_sorted(route["id"]) if route else []
    layout = (model.get("layout") if model else "2+2") or "2+2"
    try:
        cols_per_row = sum(int(p) for p in layout.split("+"))
    except ValueError:
        cols_per_row = 4
    left_cols = int(layout.split("+")[0]) if "+" in layout else cols_per_row
    return render_template(
        "customer/booking.html",
        schedule_id=schedule_id,
        route=route,
        bus=bus,
        model=model,
        fare=fare,
        route_label=route_label,
        travel_date=travel_date,
        departure_time=departure_time,
        cols_per_row=cols_per_row,
        left_cols=left_cols,
        stops=stops,
    )


def _customer_confirmed_booking(schedule_id):
    return next(
        (b for b in db.all("bookings", schedule_id=schedule_id)
         if b.get("user_id") == session.get("user_id") and b.get("status") == "confirmed"),
        None,
    )


@main_bp.get("/live-tracking")
@login_required
def tracking():
    """Like Uber/PickMe: nobody sees a bus's live position unless they're
    allowed to — the allocated driver, an admin, or a customer with a
    confirmed booking on that exact trip. No trip_id at all means "show me
    something to track", which is only meaningful for an admin (fleet map)
    or a customer being sent to their own active booking."""
    trip_id = request.args.get("trip_id")
    role = session.get("role")

    if not trip_id:
        if role == "admin":
            return render_template("tracking.html", trip_id=None, admin_mode=True, route=None, bus=None, driver_name=None, stops=[], trip_status=None)
        if role == "customer":
            active = [b for b in db.all("bookings", user_id=session["user_id"]) if b.get("status") == "confirmed"]
            active.sort(key=lambda b: b.get("created_at") or "", reverse=True)
            if active:
                trip = db.ensure_trip(active[0]["schedule_id"])
                if trip:
                    return redirect(url_for("main.tracking", trip_id=trip["id"]))
            return render_template("tracking.html", trip_id=None, admin_mode=False, route=None, bus=None, driver_name=None, stops=[], trip_status=None, no_active_trip=True)
        abort(403)

    t = db.one("trips", id=trip_id)
    if not t:
        abort(404)
    schedule = db.one("schedules", id=t.get("schedule_id")) if t else None

    if role == "driver":
        driver_row = db.one("drivers", user_id=session["user_id"])
        is_owner = bool(schedule) and bool(driver_row) and schedule.get("driver_id") == driver_row["id"]
        if not is_owner:
            abort(403)
    elif role == "customer":
        if not schedule or not _customer_confirmed_booking(schedule["id"]):
            abort(403)
    # admins may view any trip

    route = db.one("routes", id=schedule.get("route_id")) if schedule else None
    bus = db.one("buses", id=schedule.get("bus_id")) if schedule else None
    driver_row = db.one("drivers", id=schedule.get("driver_id")) if schedule else None
    driver_user = db.one("users", id=driver_row.get("user_id")) if driver_row else None
    stops = db.route_stops_sorted(route["id"]) if route else []
    return render_template(
        "tracking.html",
        trip_id=trip_id,
        route=route,
        bus=bus,
        driver_name=driver_user.get("full_name") if driver_user else "Driver",
        stops=stops,
        trip_status=t.get("status"),
        admin_mode=(role == "admin"),
    )
