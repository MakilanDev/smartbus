import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from flask import current_app
try: from supabase import create_client
except Exception: create_client = None


def haversine_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return 0
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


class Database:
    def __init__(self):
        self.client = None
        self.mem = self._seed()

    def _seed(self):
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        # ---- users: 1 admin, 1 demo customer, 10 real drivers -------------
        users = [
            {"id": "u-admin", "full_name": "System Admin", "email": "admin@smartbus.lk", "phone": "0770000001", "password_hash": "dev:SmartBus123!", "role": "admin"},
            {"id": "u-customer", "full_name": "Ayesha Silva", "email": "customer@smartbus.lk", "phone": "0770000003", "password_hash": "dev:SmartBus123!", "role": "customer"},
        ]
        driver_names = [
            "Tony stark", "peter parker", "bruce banner", "john wick", "thurai singam",
            "ben tennison", "arvinthan keerthanan", "thevarasa makilan", "steve harrington", "steve rogers",
        ]
        drivers = []
        for i, name in enumerate(driver_names, start=1):
            uid = f"u-driver{i}"
            email = f"driver{i}@smartbus.lk"
            users.append({"id": uid, "full_name": name, "email": email, "phone": f"07711{i:05d}", "password_hash": "dev:SmartBus123!", "role": "driver"})
            drivers.append({"id": f"d{i}", "user_id": uid, "license_no": f"B{1000000+i}", "license_expiry": "2030-12-31", "photo_url": ""})

        # ---- 3 bus models + 10 buses --------------------------------------
        bus_models = [
            {"id": "m1", "name": "Luxury AC Coach", "seat_capacity": 40, "layout": "2+1", "km_per_litre": 4.5, "ac_type": "Full AC"},
            {"id": "m2", "name": "Semi-Luxury Coach", "seat_capacity": 49, "layout": "2+2", "km_per_litre": 5.2, "ac_type": "Semi AC"},
            {"id": "m3", "name": "Super Express Coach", "seat_capacity": 36, "layout": "2+1", "km_per_litre": 4.0, "ac_type": "Full AC"},
        ]
        bus_defs = [
            ("NC-4581", "Purple Express", "m1"), ("NC-4582", "Northern Star", "m1"),
            ("NB-2210", "City Comfort", "m2"), ("NB-2211", "City Comfort II", "m2"),
            ("NA-7734", "Super Rider", "m3"), ("NA-7735", "Super Rider II", "m3"),
            ("NC-4590", "Jaffna Queen", "m1"), ("NB-2299", "Kandy Flyer", "m2"),
            ("NA-7799", "Colombo Express", "m3"), ("NC-4600", "Golden Arrow", "m1"),
        ]
        buses = [{"id": f"b{i}", "model_id": model_id, "registration_no": reg, "display_name": name, "photo_url": ""}
                  for i, (reg, name, model_id) in enumerate(bus_defs, start=1)]

        # ---- seats for every bus, sized to its model's layout --------------
        seats = []
        for bus in buses:
            model = next(m for m in bus_models if m["id"] == bus["model_id"])
            cols = sum(int(p) for p in model["layout"].split("+"))
            female_demo_seats = {"11", "17"} if bus["id"] == "b1" else set()
            for i in range(1, model["seat_capacity"] + 1):
                seats.append({
                    "id": f"seat-{bus['id']}-{i}", "bus_id": bus["id"], "seat_no": str(i),
                    "row_no": (i - 1) // cols + 1, "column_no": (i - 1) % cols + 1,
                    "seat_type": "female" if str(i) in female_demo_seats else "normal",
                })

        # ---- 4 routes: Jaffna<->Colombo and Jaffna<->Kandy ------------------
        routes = [
            {"id": "r1", "name": "Northern Express", "origin": "Jaffna", "destination": "Colombo", "distance_km": 396, "duration_minutes": 420},
            {"id": "r2", "name": "Northern Return", "origin": "Colombo", "destination": "Jaffna", "distance_km": 396, "duration_minutes": 420},
            {"id": "r3", "name": "Hill Country", "origin": "Jaffna", "destination": "Kandy", "distance_km": 300, "duration_minutes": 360},
            {"id": "r4", "name": "Hill Country Return", "origin": "Kandy", "destination": "Jaffna", "distance_km": 300, "duration_minutes": 360},
        ]
        # Demo stops (fed straight to the Google Map on the admin allocation
        # page and the customer's stop-to-stop booking picker) even without Supabase.
        raw_stops = {
            "r1": [("Jaffna", 9.6615, 80.0255), ("Vavuniya", 8.7542, 80.4982), ("Kurunegala", 7.4863, 80.3623), ("Colombo", 6.9271, 79.8612)],
            "r2": [("Colombo", 6.9271, 79.8612), ("Kurunegala", 7.4863, 80.3623), ("Vavuniya", 8.7542, 80.4982), ("Jaffna", 9.6615, 80.0255)],
            "r3": [("Jaffna", 9.6615, 80.0255), ("Vavuniya", 8.7542, 80.4982), ("Dambulla", 7.8731, 80.6511), ("Kandy", 7.2906, 80.6337)],
            "r4": [("Kandy", 7.2906, 80.6337), ("Dambulla", 7.8731, 80.6511), ("Vavuniya", 8.7542, 80.4982), ("Jaffna", 9.6615, 80.0255)],
        }
        route_stops = []
        for route_id, stops in raw_stops.items():
            origin_lat, origin_lng = stops[0][1], stops[0][2]
            for order, (name, lat, lng) in enumerate(stops, start=1):
                route_stops.append({
                    "id": f"{route_id}-stop-{order}",
                    "route_id": route_id,
                    "stop_name": name,
                    "stop_order": order,
                    "latitude": lat,
                    "longitude": lng,
                    "distance_from_origin_km": haversine_km(origin_lat, origin_lng, lat, lng),
                })

        # ---- sample daily schedule: morning + night on the Colombo legs, --
        # ---- night only on the Kandy legs, spread across the 10 buses -----
        # This is deliberately just a starting sample (as requested) — every
        # row is editable/deletable from /admin/module/schedules afterwards.
        schedule_plan = [
            ("r1", 6, 0, 1), ("r2", 6, 30, 2),      # morning: Jaffna->Colombo, Colombo->Jaffna
            ("r1", 20, 0, 3), ("r2", 20, 30, 4),    # night: Jaffna->Colombo, Colombo->Jaffna
            ("r3", 21, 0, 5), ("r4", 21, 30, 6),    # night: Jaffna->Kandy, Kandy->Jaffna
            ("r1", 7, 0, 7), ("r2", 7, 30, 8),      # extra morning departures
        ]
        schedules = []
        for idx, (route_id, hour, minute, bus_no) in enumerate(schedule_plan, start=1):
            route = next(r for r in routes if r["id"] == route_id)
            dep = today.replace(hour=hour, minute=minute)
            arr = dep + timedelta(minutes=route["duration_minutes"])
            schedules.append({
                "id": f"s{idx}", "route_id": route_id, "bus_id": f"b{bus_no}", "driver_id": f"d{bus_no}",
                "departure_time": dep.isoformat(), "arrival_time": arr.isoformat(),
                "fare": 2800 if route["distance_km"] > 350 else 2200,
            })
        trips = [{"id": f"t{idx}", "schedule_id": s["id"], "status": "scheduled", "passenger_count": 0} for idx, s in enumerate(schedules, start=1)]

        return {
            "users": users,
            "drivers": drivers,
            "bus_models": bus_models,
            "buses": buses,
            "routes": routes,
            "route_stops": route_stops,
            "schedules": schedules,
            "trips": trips,
            "seats": seats,
            "bookings": [],
            "booking_seats": [],
            "payments": [],
            "fuel_prices": [{"price_date": now.date().isoformat(), "price_per_litre": 344}],
            "fuel_logs": [],
            "maintenance_logs": [],
            "gps_logs": [],
            "notifications": [],
            "audit_logs": [],
        }

    def connect(self):
        if self.client is None and create_client:
            u = current_app.config.get("SUPABASE_URL")
            k = current_app.config.get("SUPABASE_KEY")
            if not u or not k:
                print("[SmartBus DB] WARNING: SUPABASE_URL/SUPABASE_KEY missing — using in-memory demo data (data will NOT persist).")
            else:
                try:
                    self.client = create_client(u, k)
                    print("[SmartBus DB] Connected to Supabase successfully.")
                except Exception as e:
                    print(f"[SmartBus DB] ERROR: Supabase connection failed ({e}) — falling back to in-memory demo data (data will NOT persist).")
        return self.client

    def all(self, table, **eq):
        c = self.connect()
        if c:
            q = c.table(table).select("*")
            for k, v in eq.items():
                q = q.eq(k, v)
            return q.execute().data or []
        return [x.copy() for x in self.mem.get(table, []) if all(str(x.get(k)) == str(v) for k, v in eq.items())]

    def one(self, table, **eq):
        rows = self.all(table, **eq)
        return rows[0] if rows else None

    def add(self, table, data):
        data = dict(data)
        data.setdefault("id", str(uuid4()))
        c = self.connect()
        if c:
            return c.table(table).insert(data).execute().data[0]
        self.mem.setdefault(table, []).append(data)
        return data.copy()

    def update(self, table, id, data):
        c = self.connect()
        if c:
            return c.table(table).update(data).eq("id", id).execute().data[0]
        row = self.one_ref(table, id)
        if row:
            row.update(data)
        return row.copy() if row else None

    def delete(self, table, id):
        """Remove a record by id. Used by the admin 'Delete' action on every
        editable module (users, drivers, buses, routes, stops, schedules...)."""
        c = self.connect()
        if c:
            c.table(table).delete().eq("id", id).execute()
            return True
        lst = self.mem.get(table, [])
        before = len(lst)
        self.mem[table] = [x for x in lst if str(x.get("id")) != str(id)]
        return len(self.mem[table]) != before

    def one_ref(self, table, id):
        return next((x for x in self.mem.get(table, []) if str(x.get("id")) == str(id)), None)

    def ensure_trip(self, schedule_id):
        """Return the trip linked to a schedule, creating it if missing. Without this,
        a newly-created schedule has no trip row, so drivers/customers/admins have
        nothing to attach GPS pings or live-tracking to."""
        if not schedule_id:
            return None
        trip = self.one("trips", schedule_id=schedule_id)
        if trip:
            return trip
        return self.add("trips", {"schedule_id": schedule_id, "status": "scheduled", "passenger_count": 0})

    def route_stops_sorted(self, route_id):
        stops = self.all("route_stops", route_id=route_id)
        return sorted(stops, key=lambda s: s.get("stop_order") or 0)

    def fare_for_stops(self, schedule, origin_stop, destination_stop):
        """Pro-rate the schedule's full fare by distance between two stops on
        the same route, so a customer travelling Vavuniya -> Colombo pays less
        than the full Jaffna -> Colombo fare."""
        full_fare = float(schedule.get("fare") or 0)
        if not origin_stop or not destination_stop:
            return full_fare
        route = self.one("routes", id=schedule.get("route_id"))
        total_km = float(route.get("distance_km") or 0) if route else 0
        d_from = float(origin_stop.get("distance_from_origin_km") or 0)
        d_to = float(destination_stop.get("distance_from_origin_km") or 0)
        if total_km <= 0 or d_to <= d_from:
            return full_fare
        return round(full_fare * ((d_to - d_from) / total_km), 2)


db = Database()
