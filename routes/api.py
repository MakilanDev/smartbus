from flask import Blueprint, request, jsonify, session, current_app
from datetime import datetime, timedelta, timezone, date
from uuid import uuid4
from services.database import db
from services.auth import role_required
from services.tickets import create_ticket
from services.notifications import (
    send_booking_confirmation,
    send_delay_alerts,
    send_trip_completed_alerts,
    send_trip_started_alerts,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def ok(data=None, **kw):
    return jsonify({"ok": True, "data": data, **kw})


def err(message, status=400):
    return jsonify({"ok": False, "message": message}), status


def _parse_day(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return None


@api_bp.get("/dashboard/stats")
@role_required("admin")
def stats():
    today = datetime.now(timezone.utc).date()
    gps_latest = {}
    for row in db.all("gps_logs"):
        if row.get("trip_id"):
            gps_latest[row["trip_id"]] = row
    fuel_today = sum(float(x.get("cost") or 0) for x in db.all("fuel_logs") if _parse_day(x.get("logged_at")) == today)
    delay_rows = [x for x in db.all("trips") if int(x.get("delay_minutes") or 0) > 0]
    avg_delay = round(sum(int(x.get("delay_minutes") or 0) for x in delay_rows) / len(delay_rows), 1) if delay_rows else 0
    active_trips = len([x for x in db.all("trips") if x.get("status") in ("started", "delayed")])
    bookings_today = [b for b in db.all("bookings") if _parse_day(b.get("created_at")) == today]
    return ok({
        "users": len(db.all("users")),
        "buses": len(db.all("buses")),
        "trips": len(db.all("trips")),
        "bookings": len(db.all("bookings")),
        "bookings_today": len(bookings_today),
        "revenue": sum(float(x.get("amount", 0)) for x in db.all("payments") if x.get("status") == "paid"),
        "active_gps_buses": len(gps_latest),
        "google_maps_status": "Configured" if current_app.config.get("GOOGLE_MAPS_API_KEY") else "Missing key",
        "average_delay_time": avg_delay,
        "fuel_cost_today": fuel_today,
        "active_trips": active_trips,
        "online_drivers": active_trips,
    })


@api_bp.get("/routes/search")
def routes_search():
    rows = db.all("routes")
    origin = request.args.get("from", "").lower()
    dest = request.args.get("to", "").lower()
    return ok([r for r in rows if (not origin or origin in r["origin"].lower()) and (not dest or dest in r["destination"].lower())])


@api_bp.get("/routes/<route_id>/stops")
def route_stops(route_id):
    """All stops for a route, in order, with running distance from the first
    stop — used by the booking page (pick any stop-to-stop leg) and by the
    admin allocation map."""
    return ok(db.route_stops_sorted(route_id))


@api_bp.get("/schedules/search")
def schedules_search():
    found = []
    for s in db.all("schedules"):
        r = db.one("routes", id=s["route_id"])
        if not r:
            continue
        if request.args.get("from", "").lower() not in r["origin"].lower() or request.args.get("to", "").lower() not in r["destination"].lower():
            continue
        found.append({**s, "route": r, "bus": db.one("buses", id=s["bus_id"]), "driver": db.one("drivers", id=s["driver_id"])})
    return ok(found)


@api_bp.get("/seats/<schedule_id>")
def seats(schedule_id):
    s = db.one("schedules", id=schedule_id)
    if not s:
        return err("Schedule not found", 404)
    sold = {x["seat_id"]: x["status"] for x in db.all("booking_seats")}
    out = []
    for x in db.all("seats", bus_id=s["bus_id"]):
        status = sold.get(x["id"], "available")
        seat_type = x.get("seat_type") or "normal"
        # A blocked seat (e.g. driver's-side/crew seat) is never sellable,
        # whatever the booking table says.
        if seat_type == "blocked":
            status = "blocked"
        out.append({**x, "status": status, "seat_type": seat_type})
    return ok(out)


@api_bp.get("/fare/<schedule_id>")
def fare_quote(schedule_id):
    """Quote the fare for a given stop-to-stop leg on a schedule, so the
    booking page can show the correct price live as the customer changes
    their boarding/alighting point (e.g. Vavuniya -> Colombo)."""
    s = db.one("schedules", id=schedule_id)
    if not s:
        return err("Schedule not found", 404)
    origin_stop = db.one("route_stops", id=request.args.get("origin_stop_id")) if request.args.get("origin_stop_id") else None
    dest_stop = db.one("route_stops", id=request.args.get("destination_stop_id")) if request.args.get("destination_stop_id") else None
    fare = db.fare_for_stops(s, origin_stop, dest_stop)
    return ok({"fare": fare, "full_fare": float(s.get("fare") or 0)})


@api_bp.post("/bookings/create")
@role_required("customer")
def create_booking():
    d = request.get_json() or {}
    s = db.one("schedules", id=d.get("schedule_id"))
    seat_ids = d.get("seat_ids", [])
    if not s or not seat_ids:
        return err("Choose a schedule and seats")
    sold = {x["seat_id"] for x in db.all("booking_seats") if x.get("status") in ("sold", "pending")}
    if sold.intersection(seat_ids):
        return err("One or more seats are unavailable", 409)
    blocked = {x["id"] for x in db.all("seats", bus_id=s["bus_id"]) if (x.get("seat_type") or "normal") == "blocked"}
    if blocked.intersection(seat_ids):
        return err("One or more selected seats are blocked and cannot be booked", 409)

    origin_stop = db.one("route_stops", id=d.get("origin_stop_id")) if d.get("origin_stop_id") else None
    dest_stop = db.one("route_stops", id=d.get("destination_stop_id")) if d.get("destination_stop_id") else None
    per_seat_fare = db.fare_for_stops(s, origin_stop, dest_stop)
    route = db.one("routes", id=s.get("route_id"))
    origin_label = origin_stop["stop_name"] if origin_stop else (route["origin"] if route else None)
    destination_label = dest_stop["stop_name"] if dest_stop else (route["destination"] if route else None)

    b = db.add("bookings", {
        "booking_code": "SB-" + uuid4().hex[:8].upper(),
        "user_id": session["user_id"],
        "schedule_id": s["id"],
        "origin_stop_id": origin_stop["id"] if origin_stop else None,
        "destination_stop_id": dest_stop["id"] if dest_stop else None,
        "origin_label": origin_label,
        "destination_label": destination_label,
        "status": "pending",
        "total_amount": per_seat_fare * len(seat_ids),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    for sid in seat_ids:
        db.add("booking_seats", {"booking_id": b["id"], "seat_id": sid, "status": "pending"})
    return ok(b)


@api_bp.post("/payment/test")
@role_required("customer")
def pay():
    d = request.get_json() or {}
    b = db.one("bookings", id=d.get("booking_id"))
    if not b or b["user_id"] != session["user_id"]:
        return err("Booking not found", 404)
    p = db.add("payments", {"booking_id": b["id"], "amount": b["total_amount"], "status": "paid", "test_reference": "TEST-" + uuid4().hex[:10].upper(), "paid_at": datetime.now(timezone.utc).isoformat()})
    db.update("bookings", b["id"], {"status": "confirmed"})
    for x in db.all("booking_seats", booking_id=b["id"]):
        db.update("booking_seats", x["id"], {"status": "sold"})
    u = db.one("users", id=b["user_id"])
    s = db.one("schedules", id=b["schedule_id"])
    r = db.one("routes", id=s["route_id"])
    driver_row = db.one("drivers", id=s.get("driver_id"))
    driver_user = db.one("users", id=driver_row.get("user_id")) if driver_row else None
    seat_names = [db.one("seats", id=x["seat_id"])["seat_no"] for x in db.all("booking_seats", booking_id=b["id"])]
    leg = f'{b.get("origin_label") or r["origin"]} -> {b.get("destination_label") or r["destination"]}'
    create_ticket(b, {
        "route": leg,
        "customer": u["full_name"],
        "datetime": s["departure_time"],
        "bus": db.one("buses", id=s["bus_id"])["display_name"],
        "driver": driver_user["full_name"] if driver_user else "SmartBus driver",
        "seats": ", ".join(seat_names),
        "amount": f'LKR {b["total_amount"]:,.2f}',
        "payment": "PAID (TEST)",
    })
    ticket_url = request.url_root.rstrip("/") + f'/customer/ticket/{b["booking_code"]}.pdf'
    trip = db.ensure_trip(s["id"])
    tracking_url = request.url_root.rstrip("/") + f'/live-tracking?trip_id={trip["id"]}' if trip else None
    send_booking_confirmation(u, b, {**r, "origin": b.get("origin_label") or r["origin"], "destination": b.get("destination_label") or r["destination"]}, s, seat_names, ticket_url, tracking_url)
    return ok({"payment": p, "ticket": f'/customer/ticket/{b["booking_code"]}.pdf', "tracking": f'/live-tracking?trip_id={trip["id"]}' if trip else None})


@api_bp.post("/driver/location/update")
@role_required("driver")
def location_update():
    d = request.get_json() or {}
    t = db.one("trips", id=d.get("trip_id"))
    if not t or t.get("status") not in ("started", "delayed"):
        # Mirrors real Uber/PickMe behaviour: once a trip is completed (or was
        # never started) its driver app should stop broadcasting, and the
        # backend refuses to record a ping outside of an active trip.
        return err("Location can only be reported while the trip is active", 409)
    now_iso = datetime.now(timezone.utc).isoformat()
    row = db.add("gps_logs", {"trip_id": d.get("trip_id"), "latitude": d.get("latitude"), "longitude": d.get("longitude"), "speed": d.get("speed", 0), "heading": d.get("heading", 0), "recorded_at": now_iso})
    db.update("trips", t["id"], {"last_location_at": now_iso})
    return ok(row)


def _customer_owns_trip(trip):
    """True if the logged-in customer has a confirmed booking on this trip's
    schedule -- the same rule the /live-tracking page uses, applied again
    here so the JSON feed can't be pulled by pasting a trip_id into a browser."""
    schedule = _schedule_for_trip(trip)
    if not schedule:
        return False
    return any(
        b.get("user_id") == session.get("user_id") and b.get("status") == "confirmed"
        for b in db.all("bookings", schedule_id=schedule["id"])
    )


@api_bp.get("/trip/location/<trip_id>")
@role_required("customer", "driver", "admin")
def trip_location(trip_id):
    t = db.one("trips", id=trip_id)
    if not t:
        return err("Trip not found", 404)
    if session.get("role") == "customer" and not _customer_owns_trip(t):
        return err("You can only track a trip you have booked", 403)
    rows = db.all("gps_logs", trip_id=trip_id)
    row = dict(rows[-1]) if rows else {"latitude": None, "longitude": None}
    row["status"] = t.get("status")
    row["has_position"] = bool(rows) and t.get("status") in ("started", "delayed")
    if not row["has_position"]:
        row["latitude"] = row["longitude"] = None
    return ok(row)


@api_bp.get("/trip/status/<trip_id>")
@role_required("customer", "driver", "admin")
def trip_status(trip_id):
    t = db.one("trips", id=trip_id)
    if not t:
        return err("Trip not found", 404)
    if session.get("role") == "customer" and not _customer_owns_trip(t):
        return err("You can only track a trip you have booked", 403)
    return ok({"status": t.get("status"), "started_at": t.get("started_at"), "ended_at": t.get("ended_at")})


@api_bp.get("/admin/all-bus-locations")
@role_required("admin")
def all_locations():
    """Only buses currently on an active trip appear on the fleet map — a
    bus with no trip running has nothing to show, same as Uber's dispatch
    map only plots drivers who are actually on a job."""
    active_trip_ids = {t["id"] for t in db.all("trips") if t.get("status") in ("started", "delayed")}
    latest_by_trip = {}
    for row in db.all("gps_logs"):
        tid = row.get("trip_id")
        if tid in active_trip_ids:
            latest_by_trip[tid] = row  # gps_logs is append-only, so the last one wins
    out = []
    for tid, row in latest_by_trip.items():
        trip = db.one("trips", id=tid)
        schedule = db.one("schedules", id=trip.get("schedule_id")) if trip else None
        route = db.one("routes", id=schedule.get("route_id")) if schedule else None
        bus = db.one("buses", id=schedule.get("bus_id")) if schedule else None
        out.append({**row, "trip_id": tid, "route_label": f'{route["origin"]} → {route["destination"]}' if route else "—", "bus": bus.get("display_name") if bus else "—"})
    return ok(out)


@api_bp.get("/admin/active-trips")
@role_required("admin")
def active_trips():
    """Trips currently in progress, for the fleet-map trip picker."""
    out = []
    for t in db.all("trips"):
        if t.get("status") not in ("started", "delayed"):
            continue
        schedule = db.one("schedules", id=t.get("schedule_id"))
        route = db.one("routes", id=schedule.get("route_id")) if schedule else None
        bus = db.one("buses", id=schedule.get("bus_id")) if schedule else None
        out.append({"trip_id": t["id"], "status": t.get("status"), "route_label": f'{route["origin"]} → {route["destination"]}' if route else "—", "bus": bus.get("display_name") if bus else "—"})
    return ok(out)


def _log_trip_fuel(trip):
    """Auto-calculate fuel used and cost for a completed trip using the bus
    model's km/litre rating, the route distance and today's fuel price."""
    schedule = db.one("schedules", id=trip.get("schedule_id"))
    if not schedule:
        return None
    route = db.one("routes", id=schedule.get("route_id"))
    bus = db.one("buses", id=schedule.get("bus_id"))
    model = db.one("bus_models", id=bus.get("model_id")) if bus else None
    if not route or not model:
        return None
    km_per_litre = float(model.get("km_per_litre") or 0)
    distance_km = float(route.get("distance_km") or 0)
    if km_per_litre <= 0 or distance_km <= 0:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    price_row = db.one("fuel_prices", price_date=today)
    if not price_row:
        prices = sorted(db.all("fuel_prices"), key=lambda x: x.get("price_date") or "", reverse=True)
        price_row = prices[0] if prices else None
    price_per_litre = float(price_row.get("price_per_litre")) if price_row else 0
    if price_per_litre <= 0:
        return None
    litres = round(distance_km / km_per_litre, 2)
    cost = round(litres * price_per_litre, 2)
    return db.add("fuel_logs", {
        "trip_id": trip["id"],
        "bus_id": bus["id"] if bus else None,
        "litres": litres,
        "cost": cost,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })




def _log_trip_maintenance(trip):
    """Auto-count every completed trip against a rolling maintenance counter.
    Adds trip distance to the bus odometer; when it crosses the service
    threshold (default 5000 km) a maintenance_log 'Scheduled service due'
    entry is created automatically so admin sees it in Maintenance Log."""
    schedule = db.one("schedules", id=trip.get("schedule_id"))
    if not schedule: return None
    route = db.one("routes", id=schedule.get("route_id"))
    bus = db.one("buses", id=schedule.get("bus_id"))
    if not bus or not route: return None
    distance_km = float(route.get("distance_km") or 0)
    prev_km = float(bus.get("total_km") or 0)
    trips_count = int(bus.get("trips_count") or 0) + 1
    new_km = prev_km + distance_km
    db.update("buses", bus["id"], {"total_km": new_km, "trips_count": trips_count, "last_trip_at": datetime.now(timezone.utc).isoformat()})
    SERVICE_EVERY_KM = 5000
    # If crossed a 5000km boundary, raise a maintenance ticket
    if int(prev_km // SERVICE_EVERY_KM) < int(new_km // SERVICE_EVERY_KM):
        db.add("maintenance_logs", {
            "bus_id": bus["id"],
            "title": f"Scheduled service due ({int(new_km)} km)",
            "details": f"Auto-generated after trip {trip['id'][:8]}. Bus has covered {int(new_km)} km across {trips_count} trips.",
            "starts_at": datetime.now(timezone.utc).date().isoformat(),
            "cost": 0,
            "status": "scheduled",
        })
    return {"total_km": new_km, "trips_count": trips_count}

def _schedule_for_trip(trip):
    return db.one("schedules", id=trip.get("schedule_id")) if trip else None


def _is_allocated_driver(schedule):
    """True if the logged-in driver is the one this schedule's trip was
    allocated to. Admins may always act; any other driver may not — only the
    allocated bus driver can start (or otherwise control) their own trip."""
    if session.get("role") == "admin":
        return True
    if session.get("role") != "driver" or not schedule:
        return False
    driver_row = db.one("drivers", user_id=session.get("user_id"))
    return bool(driver_row) and driver_row["id"] == schedule.get("driver_id")


START_WINDOW_BEFORE_MIN = 720  # 12h before allowed
START_WINDOW_AFTER_MIN = 1440  # 24h after allowed


def _start_window(schedule):
    dep = _parse_iso(schedule.get("departure_time")) if schedule else None
    if not dep:
        return None, None
    return dep - timedelta(minutes=START_WINDOW_BEFORE_MIN), dep + timedelta(minutes=START_WINDOW_AFTER_MIN)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def trip_action(status):
    d = request.get_json() or {}
    t = db.one("trips", id=d.get("trip_id"))
    if not t:
        return err("Trip not found", 404)
    schedule = _schedule_for_trip(t)
    if not _is_allocated_driver(schedule):
        return err("Only the driver allocated to this trip can update it", 403)
    if status == "started" and session.get("role") != "admin":
        opens_at, closes_at = _start_window(schedule)
        now = datetime.now(timezone.utc)
        if opens_at and now < opens_at:
            return err(f"You can start this trip from {opens_at.strftime('%I:%M %p')} onward (scheduled departure {_parse_iso(schedule['departure_time']).strftime('%I:%M %p')}).", 403)
        if closes_at and now > closes_at:
            return err("This trip's start window has passed — contact dispatch to reschedule.", 403)
    fields = {"status": status}
    fields["started_at" if status == "started" else "ended_at" if status == "completed" else "breakdown_notes" if status == "breakdown" else "delay_reason"] = datetime.now(timezone.utc).isoformat() if status in ("started", "completed") else d.get("reason", "Traffic delay" if status == "delayed" else "Breakdown reported")
    if status == "delayed":
        fields["delay_minutes"] = int(d.get("minutes", 15))
    updated = db.update("trips", t["id"], fields)
    tracking_url = request.url_root.rstrip("/") + f'/live-tracking?trip_id={t["id"]}'
    if status == "delayed":
        send_delay_alerts(t["id"], fields["delay_reason"], fields["delay_minutes"], tracking_url)
    if status == "started":
        send_trip_started_alerts(t["id"], tracking_url)
    if status == "completed":
        _log_trip_fuel(updated)
        _log_trip_maintenance(updated)
        send_trip_completed_alerts(t["id"])
    return ok(updated)


@api_bp.post("/trip/start")
@role_required("driver", "admin")
def start():
    return trip_action("started")


@api_bp.post("/trip/mark-delay")
@role_required("driver", "admin")
def delay():
    return trip_action("delayed")


@api_bp.post("/trip/complete")
@role_required("driver", "admin")
def complete():
    return trip_action("completed")


@api_bp.post("/trip/breakdown")
@role_required("driver")
def breakdown():
    return trip_action("breakdown")


@api_bp.get("/admin/fuel-price/today")
@role_required("admin")
def fuel_price_today():
    today = datetime.now(timezone.utc).date().isoformat()
    row = db.one("fuel_prices", price_date=today)
    if not row:
        prices = sorted(db.all("fuel_prices"), key=lambda x: x.get("price_date") or "", reverse=True)
        row = prices[0] if prices else None
    return ok({"price_per_litre": float(row["price_per_litre"]) if row else 0, "price_date": row["price_date"] if row else None})


@api_bp.post("/admin/fuel-price/set")
@role_required("admin")
def fuel_price_set():
    d = request.get_json() or {}
    today = datetime.now(timezone.utc).date().isoformat()
    price = float(d.get("price_per_litre") or 0)
    if price <= 0:
        return err("Enter a valid price")
    existing = db.one("fuel_prices", price_date=today)
    if existing:
        row = db.update("fuel_prices", existing["id"], {"price_per_litre": price})
    else:
        row = db.add("fuel_prices", {"price_date": today, "price_per_litre": price})
    return ok(row)
