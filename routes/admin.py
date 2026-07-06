from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from services.auth import role_required
from services.database import db
from services.storage import upload

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
MODULES = {
    "users": "users",
    "drivers": "drivers",
    "bus-models": "bus_models",
    "buses": "buses",
    "routes": "routes",
    "stops": "route_stops",
    "schedules": "schedules",
    "trips": "trips",
    "bookings": "bookings",
    "payments": "payments",
    "fuel": "fuel_logs",
    "maintenance": "maintenance_logs",
    "notifications": "notifications",
    "reports": "audit_logs",
    "settings": "fuel_prices",
}

# (field_name, label, type, *extra) — extra holds select options or the
# referenced table name (+ optional label field) for select_table fields.
MODULE_FIELDS = {
    "users": [
        ("full_name", "Full name", "text"),
        ("email", "Email", "text"),
        ("phone", "Phone", "text"),
        ("role", "Role", "select", "admin,driver,customer"),
        ("password", "Password", "password"),
    ],
    "drivers": [
        ("full_name", "Driver full name", "text"),
        ("email", "Login email", "text"),
        ("phone", "Phone", "text"),
        ("password", "Login password", "password"),
        ("license_no", "License number", "text"),
        ("license_expiry", "License expiry", "date"),
        ("photo", "Driver photo", "file"),
    ],
    "bus-models": [
        ("name", "Model name", "text"),
        ("seat_capacity", "Seating capacity", "number"),
        ("layout", "Seat layout", "select", "2+1,2+2"),
        ("km_per_litre", "Fuel efficiency (km per litre)", "number"),
        ("ac_type", "AC type", "select", "Full AC,Semi AC,Non AC"),
    ],
    "buses": [
        ("registration_no", "Registration number", "text"),
        ("display_name", "Display name", "text"),
        ("model_id", "Bus model", "select_table", "bus_models", "name"),
        ("photo", "Bus photo", "file"),
    ],
    "routes": [
        ("name", "Route name", "text"),
        ("origin", "Origin", "text"),
        ("destination", "Destination", "text"),
        ("distance_km", "Distance (km)", "number"),
        ("duration_minutes", "Duration (minutes)", "number"),
    ],
    "stops": [
        ("route_id", "Route", "select_table", "routes", "name"),
        ("stop_name", "Stop name", "text"),
        ("stop_order", "Stop order", "number"),
        ("latitude", "Latitude", "number"),
        ("longitude", "Longitude", "number"),
    ],
    "schedules": [
        ("route_id", "Route", "select_table", "routes", "name"),
        ("bus_id", "Bus", "select_table", "buses", "display_name"),
        ("driver_id", "Driver", "select_table", "drivers", "license_no"),
        ("departure_time", "Departure", "datetime-local"),
        ("arrival_time", "Arrival", "datetime-local"),
        ("fare", "Fare (LKR)", "number"),
    ],
    "maintenance": [
        ("bus_id", "Bus", "select_table", "buses", "display_name"),
        ("title", "Title", "text"),
        ("details", "Details", "text"),
        ("starts_at", "Serviced on", "date"),
        ("cost", "Cost (LKR)", "number"),
        ("status", "Status", "select", "scheduled,in_progress,completed"),
    ],
    "fuel": [
        ("bus_id", "Bus", "select_table", "buses", "display_name"),
        ("trip_id", "Trip (optional)", "select_table", "trips", "id"),
        ("litres", "Litres filled", "number"),
        ("cost", "Cost (LKR)", "number"),
        ("odometer_km", "Odometer (km)", "number"),
        ("logged_at", "Logged at", "date"),
        ("notes", "Notes", "text"),
    ],
    "settings": [
        ("price_date", "Date", "date"),
        ("price_per_litre", "Fuel price per litre (LKR)", "number"),
    ],
    # trips, bookings, payments, notifications and reports are system-generated
    # and shown read-only in the admin table.

}


def _bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _status(value):
    return "ONLINE" if value else "OFFLINE"


def _recent_orders(limit=8):
    bookings = sorted(db.all("bookings"), key=lambda b: b.get("created_at") or "", reverse=True)
    rows = []
    for b in bookings[:limit]:
        user = db.one("users", id=b.get("user_id"))
        rows.append({**b, "customer_name": user.get("full_name") if user else "—"})
    return rows


@admin_bp.get("/dashboard")
@role_required("admin")
def dashboard():
    return render_template("admin/dashboard.html", recent_orders=_recent_orders())


@admin_bp.get("/system-integrations")
@role_required("admin")
def system_integrations():
    return render_template(
        "admin/system_integrations.html",
        maps_configured=bool(current_app.config.get("GOOGLE_MAPS_API_KEY")),
    )


@admin_bp.get("/system-health")
@role_required("admin")
def system_health():
    health = [
        {"name": "Google Maps API", "status": _status(bool(current_app.config.get("GOOGLE_MAPS_API_KEY")))},
        {"name": "Supabase Database", "status": _status(bool(current_app.config.get("SUPABASE_URL") and current_app.config.get("SUPABASE_KEY"))) if db.connect() else "ONLINE"},
        {"name": "GPS Tracking", "status": "ONLINE"},
        {"name": "PDF Generator", "status": "ONLINE"},
        {"name": "File Storage", "status": "ONLINE"},
    ]
    return render_template("admin/system_health.html", health=health)


@admin_bp.post("/test-map")
@role_required("admin")
def test_map():
    if current_app.config.get("GOOGLE_MAPS_API_KEY"):
        flash("Google Maps key is configured. Open the Route Allocation map to verify live rendering.", "success")
    else:
        flash("Google Maps key is missing in .env.", "warning")
    return redirect(request.referrer or url_for("admin.system_integrations"))


def _generate_seats_for_bus(bus):
    """Create the seat map for a bus automatically, sized and laid out
    according to its bus model (e.g. 40 seats in a 2+1 layout)."""
    model = db.one("bus_models", id=bus.get("model_id")) if bus.get("model_id") else None
    capacity = int(model.get("seat_capacity") or 40) if model else 40
    layout = (model.get("layout") if model else "2+1") or "2+1"
    try:
        cols_per_row = sum(int(p) for p in layout.split("+"))
    except ValueError:
        cols_per_row = 3
    cols_per_row = max(cols_per_row, 1)
    for i in range(1, capacity + 1):
        db.add("seats", {
            "bus_id": bus["id"],
            "seat_no": str(i),
            "row_no": (i - 1) // cols_per_row + 1,
            "column_no": (i - 1) % cols_per_row + 1,
            "seat_type": "normal",
        })


@admin_bp.get("/seats/<bus_id>")
@role_required("admin")
def seat_map(bus_id):
    """Per-bus seat editor: every bus model can have its own real layout,
    including ladies-only and blocked seats (e.g. crew seats), instead of one
    generic grid shared by the whole fleet."""
    bus = db.one("buses", id=bus_id)
    if not bus:
        return ("Bus not found", 404)
    model = db.one("bus_models", id=bus.get("model_id")) if bus.get("model_id") else None
    layout = (model.get("layout") if model else "2+2") or "2+2"
    try:
        cols_per_row = sum(int(p) for p in layout.split("+"))
    except ValueError:
        cols_per_row = 4
    seats = sorted(db.all("seats", bus_id=bus_id), key=lambda s: (s.get("row_no") or 0, s.get("column_no") or 0))
    return render_template("admin/seat_map.html", bus=bus, model=model, seats=seats, cols_per_row=cols_per_row)


@admin_bp.post("/seats/<seat_id>/type")
@role_required("admin")
def update_seat_type(seat_id):
    seat_type = request.form.get("seat_type") or "normal"
    if seat_type not in ("normal", "female", "blocked"):
        seat_type = "normal"
    db.update("seats", seat_id, {"seat_type": seat_type})
    flash("Seat updated.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


def _build_options(fields):
    options = {}
    for name, label, ftype, *rest in fields:
        if ftype == "select_table" and rest:
            ref_table = rest[0]
            label_field = rest[1] if len(rest) > 1 else "name"
            options[name] = [(row["id"], row.get(label_field) or row.get("name") or row.get("full_name") or row["id"]) for row in db.all(ref_table)]
        elif ftype == "select" and rest:
            options[name] = [(v, v) for v in rest[0].split(",")]
    return options


DRIVER_USER_FIELDS = {"full_name", "email", "phone", "password"}


def _collect_form_data(table, fields, editing_id=None):
    """Build the insert/update dict for a module form submission.

    Special-cases 'drivers': the admin fills one signup-style form (name,
    email, phone, password, license) instead of first creating a user record
    and then linking it — this creates/updates the linked login too."""
    data = {}
    for name, label, ftype, *rest in fields:
        if table == "drivers" and name in DRIVER_USER_FIELDS:
            continue  # handled below
        if ftype == "file":
            file = request.files.get(name)
            if file and file.filename:
                data[f"{name}_url"] = upload(file, folder=table)
            continue
        value = request.form.get(name)
        if value in (None, ""):
            continue
        if ftype == "password":
            data["password_hash"] = generate_password_hash(value)
            continue
        if ftype == "number":
            try:
                value = float(value)
                if value.is_integer():
                    value = int(value)
            except ValueError:
                pass
        data[name] = value

    if table == "drivers":
        full_name = request.form.get("full_name")
        email = (request.form.get("email") or "").strip().lower()
        phone = request.form.get("phone")
        password = request.form.get("password")
        if editing_id:
            driver = db.one("drivers", id=editing_id)
            user_id = driver.get("user_id") if driver else None
            user_data = {}
            if full_name:
                user_data["full_name"] = full_name
            if email:
                user_data["email"] = email
            if phone:
                user_data["phone"] = phone
            if password:
                user_data["password_hash"] = generate_password_hash(password)
            if user_id and user_data:
                db.update("users", user_id, user_data)
        else:
            user = db.add("users", {
                "full_name": full_name or "New Driver",
                "email": email or f"driver-{uuid4().hex[:6]}@smartbus.lk",
                "phone": phone,
                "password_hash": generate_password_hash(password or "SmartBus123!"),
                "role": "driver",
                "active": True,
            })
            data["user_id"] = user["id"]
    return data


def _display_rows(module, table):
    rows = db.all(table)
    if module == "users":
        # The Users module is for customers only — drivers and admins have
        # their own dedicated modules/login flows.
        rows = [r for r in rows if r.get("role") == "customer"]
    if table == "drivers":
        for row in rows:
            u = db.one("users", id=row.get("user_id"))
            row["driver_name"] = u.get("full_name") if u else "—"
            row["email"] = u.get("email") if u else "—"
            row["phone"] = u.get("phone") if u else "—"
    if not rows:
        return rows
    # Normalize every row to the SAME set of columns, in the SAME order.
    # Without this, a manually-added record whose fields were built in a
    # different order (or skipped optional/blank fields, e.g. no photo
    # uploaded) renders its values under the wrong headers — which is why
    # a manually added driver looked "different" from the seeded ones.
    columns, seen = [], set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                columns.append(k)
    return [{col: row.get(col, "") for col in columns} for row in rows]


@admin_bp.route("/module/<module>", methods=["GET", "POST"])
@role_required("admin")
def module(module):
    table = MODULES.get(module)
    if not table:
        return ("Unknown module", 404)
    fields = MODULE_FIELDS.get(module, [])
    if request.method == "POST" and fields:
        data = _collect_form_data(table, fields)
        record = db.add(table, data)
        if table == "buses":
            _generate_seats_for_bus(record)
        if table == "schedules":
            # Every schedule needs a trip row or the driver/customer tracking
            # pages have nothing to show — create it immediately.
            db.ensure_trip(record["id"])
        flash("Record saved", "success")
        return redirect(url_for("admin.module", module=module))
    if module == "schedules":
        # Backfill trips for any schedule created before trip auto-creation
        # existed, so old schedules become trackable too.
        for sched in db.all("schedules"):
            db.ensure_trip(sched["id"])
    return render_template(
        "admin/module.html",
        module=module.replace("-", " ").title(),
        slug=module,
        rows=_display_rows(module, table),
        fields=fields,
        options=_build_options(fields),
        readonly=not fields,
    )


@admin_bp.route("/module/<module>/<record_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def module_edit(module, record_id):
    """Edit any existing record — buses, schedules, routes, drivers, users,
    etc — all editable in place instead of only being add-only."""
    table = MODULES.get(module)
    if not table:
        return ("Unknown module", 404)
    fields = MODULE_FIELDS.get(module, [])
    if not fields:
        return ("This module is read-only", 400)
    row = db.one(table, id=record_id)
    if not row:
        return ("Record not found", 404)
    if request.method == "POST":
        data = _collect_form_data(table, fields, editing_id=record_id)
        db.update(table, record_id, data)
        flash("Record updated", "success")
        return redirect(url_for("admin.module", module=module))
    if table == "drivers":
        u = db.one("users", id=row.get("user_id"))
        row = {**row, "full_name": u.get("full_name") if u else "", "email": u.get("email") if u else "", "phone": u.get("phone") if u else ""}
    return render_template(
        "admin/module_edit.html",
        module=module.replace("-", " ").title(),
        slug=module,
        row=row,
        fields=fields,
        options=_build_options(fields),
    )


@admin_bp.post("/module/<module>/<record_id>/delete")
@role_required("admin")
def module_delete(module, record_id):
    """Delete a record — e.g. remove a user, a driver, a bus, a route, a stop
    or a schedule. Cleans up dependent rows so the fleet stays consistent."""
    table = MODULES.get(module)
    if not table:
        return ("Unknown module", 404)
    if table == "drivers":
        driver = db.one("drivers", id=record_id)
        if driver and driver.get("user_id"):
            db.delete("users", driver["user_id"])  # remove the linked login too
    if table == "buses":
        for seat in db.all("seats", bus_id=record_id):
            db.delete("seats", seat["id"])
    if table == "routes":
        for stop in db.all("route_stops", route_id=record_id):
            db.delete("route_stops", stop["id"])
    db.delete(table, record_id)
    flash("Record deleted", "success")
    return redirect(request.referrer or url_for("admin.module", module=module))


@admin_bp.get("/allocations")
@role_required("admin")
def allocations():
    """Clear view of exactly which driver + route is allocated to each bus,
    built from the schedules table (the actual source of truth), plus a
    Google Map so a route's stops can be reviewed and new ones added by
    clicking directly on the map."""
    rows = []
    for s in db.all("schedules"):
        route = db.one("routes", id=s.get("route_id"))
        bus = db.one("buses", id=s.get("bus_id"))
        driver = db.one("drivers", id=s.get("driver_id"))
        driver_user = db.one("users", id=driver.get("user_id")) if driver else None
        trip = db.one("trips", schedule_id=s["id"])
        rows.append({
            "schedule_id": s["id"],
            "route_id": s.get("route_id"),
            "bus": bus.get("display_name") if bus else "— unassigned —",
            "bus_reg": bus.get("registration_no") if bus else "",
            "route": f"{route['origin']} → {route['destination']}" if route else "— unassigned —",
            "driver": driver_user.get("full_name") if driver_user else "— unassigned —",
            "license_no": driver.get("license_no") if driver else "",
            "departure_time": s.get("departure_time"),
            "trip_status": trip.get("status") if trip else "no trip",
        })
    rows.sort(key=lambda r: r.get("departure_time") or "")
    # Flag any bus double-booked with overlapping schedules — the thing admins
    # actually need surfaced instead of digging through raw SQL.
    by_bus = {}
    for r in rows:
        by_bus.setdefault(r["bus"], []).append(r)
    conflicts = {bus for bus, items in by_bus.items() if bus != "— unassigned —" and len(items) != len({i["departure_time"] for i in items})}
    routes = db.all("routes")
    return render_template("admin/allocations.html", rows=rows, conflicts=conflicts, routes=routes)


@admin_bp.post("/allocations/add-stop")
@role_required("admin")
def add_stop():
    """Add a stop to a route by clicking a point on the admin map — the
    browser reverse-geocodes the click into a place name via the Google Maps
    JS SDK and posts the coordinates + name here."""
    route_id = request.form.get("route_id")
    stop_name = request.form.get("stop_name") or "New stop"
    lat = request.form.get("latitude")
    lng = request.form.get("longitude")
    if not route_id or lat is None or lng is None:
        flash("Pick a route and a point on the map first.", "warning")
        return redirect(url_for("admin.allocations"))
    existing = db.all("route_stops", route_id=route_id)
    next_order = (max((s.get("stop_order") or 0) for s in existing) + 1) if existing else 1
    db.add("route_stops", {
        "route_id": route_id,
        "stop_name": stop_name,
        "stop_order": next_order,
        "latitude": float(lat),
        "longitude": float(lng),
    })
    flash(f'Stop "{stop_name}" allocated to the route.', "success")
    return redirect(url_for("admin.allocations", route_id=route_id))


@admin_bp.get("/gps-map")
@role_required("admin")
def gps_map():
    """Send the admin into the same live-tracking page drivers/customers use,
    in fleet mode -- every bus currently on an active trip, not one
    hardcoded trip id."""
    return redirect(url_for("main.tracking"))


def _order_detail(booking_id):
    b = db.one("bookings", id=booking_id)
    if not b:
        return None
    user = db.one("users", id=b.get("user_id"))
    schedule = db.one("schedules", id=b.get("schedule_id"))
    route = db.one("routes", id=schedule.get("route_id")) if schedule else None
    bus = db.one("buses", id=schedule.get("bus_id")) if schedule else None
    driver_row = db.one("drivers", id=schedule.get("driver_id")) if schedule else None
    driver_user = db.one("users", id=driver_row.get("user_id")) if driver_row else None
    payment = db.one("payments", booking_id=b["id"])
    seat_rows = db.all("booking_seats", booking_id=b["id"])
    seat_names = [db.one("seats", id=x["seat_id"]).get("seat_no") for x in seat_rows if db.one("seats", id=x["seat_id"])]
    return {
        "booking": b,
        "customer": user,
        "schedule": schedule,
        "route": route,
        "bus": bus,
        "driver": driver_user,
        "payment": payment,
        "seat_names": seat_names,
        "origin_label": b.get("origin_label") or (route.get("origin") if route else "—"),
        "destination_label": b.get("destination_label") or (route.get("destination") if route else "—"),
    }


@admin_bp.get("/orders")
@role_required("admin")
def orders():
    """Every booking with the customer's name/contact and the trip it belongs
    to, in one place — the admin 'order management' screen."""
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status", "all")
    rows = []
    for b in sorted(db.all("bookings"), key=lambda x: x.get("created_at") or "", reverse=True):
        user = db.one("users", id=b.get("user_id"))
        schedule = db.one("schedules", id=b.get("schedule_id"))
        route = db.one("routes", id=schedule.get("route_id")) if schedule else None
        row = {
            **b,
            "customer_name": user.get("full_name") if user else "—",
            "customer_email": user.get("email") if user else "—",
            "customer_phone": user.get("phone") if user else "—",
            "route_label": f'{b.get("origin_label") or (route["origin"] if route else "—")} → {b.get("destination_label") or (route["destination"] if route else "—")}',
        }
        if status != "all" and row.get("status") != status:
            continue
        if q and q not in (row["customer_name"] or "").lower() and q not in (row.get("booking_code") or "").lower():
            continue
        rows.append(row)
    return render_template("admin/orders.html", rows=rows, q=q, status=status)


@admin_bp.get("/orders/<booking_id>")
@role_required("admin")
def order_detail(booking_id):
    detail = _order_detail(booking_id)
    if not detail:
        return ("Order not found", 404)
    return render_template("admin/order_detail.html", **detail)


# --- Reports & Analytics --------------------------------------------------
from flask import send_file, jsonify  # noqa: E402
from services import reports as reports_service  # noqa: E402


@admin_bp.get("/reports")
@role_required("admin")
def reports():
    period = request.args.get("period", "monthly")
    if period not in ("weekly", "monthly", "yearly"):
        period = "monthly"
    data = reports_service.analytics(period)
    return render_template("admin/reports.html", data=data, period=period)


@admin_bp.get("/reports/data")
@role_required("admin")
def reports_data():
    period = request.args.get("period", "monthly")
    if period not in ("weekly", "monthly", "yearly"):
        period = "monthly"
    return jsonify({"ok": True, "data": reports_service.analytics(period)})


@admin_bp.get("/reports/pdf")
@role_required("admin")
def reports_pdf():
    period = request.args.get("period", "monthly")
    section = request.args.get("section", "all")
    if period not in ("weekly", "monthly", "yearly"):
        period = "monthly"
    if section not in ("all", "trips", "fuel", "maintenance"):
        section = "all"
    pdf = reports_service.build_pdf(period, section)
    filename = f"smartbus-{section}-{period}-report.pdf"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=filename)
