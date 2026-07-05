from datetime import datetime, timezone

from services.database import db


def _now():
    return datetime.now(timezone.utc).isoformat()


def _format_departure(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d"), parsed.strftime("%I:%M %p")
    except (TypeError, ValueError):
        return str(value), str(value)


def _system_notify(user, booking_id, subject, message):
    """SmartBus only uses in-app notifications — no SMS, no email. Every
    alert (booking confirmed, delay, trip started/completed) is logged here
    and shown in the customer's/driver's notification centre."""
    if not user:
        return "skipped"
    db.add("notifications", {
        "user_id": user.get("id"),
        "booking_id": booking_id,
        "channel": "system",
        "provider": "smartbus",
        "subject": subject,
        "message": message,
        "status": "sent",
        "created_at": _now(),
    })
    return "sent"


def notify(user, subject, message, booking_id=None):
    return {"system": _system_notify(user, booking_id, subject, message)}


def send_booking_confirmation(user, booking, route, schedule, seat_numbers, ticket_url, tracking_url=None):
    travel_date, departure_time = _format_departure(schedule["departure_time"])
    seats = ", ".join(str(seat) for seat in seat_numbers)
    message = (
        "SmartBus Booking Confirmed\n"
        f"Booking ID: {booking['booking_code']}\n"
        f"Route: {route['origin']} -> {route['destination']}\n"
        f"Date: {travel_date}\n"
        f"Departure: {departure_time}\n"
        f"Seat: {seats}\n"
        f"Bill (PDF): {ticket_url}"
    )
    if tracking_url:
        message += f"\nTrack your bus: {tracking_url}"
    return {"system": _system_notify(user, booking["id"], "SmartBus booking confirmed", message)}


def _confirmed_trip_passengers(trip_id):
    trip = db.one("trips", id=trip_id)
    if not trip:
        return []
    schedule = db.one("schedules", id=trip["schedule_id"])
    if not schedule:
        return []
    route = db.one("routes", id=schedule["route_id"])
    passengers = []
    for booking in db.all("bookings", schedule_id=schedule["id"]):
        if booking.get("status") != "confirmed":
            continue
        user = db.one("users", id=booking["user_id"])
        if user:
            passengers.append((user, booking, route))
    return passengers


def send_delay_alerts(trip_id, reason, delay_minutes, tracking_url):
    results = []
    for user, booking, route in _confirmed_trip_passengers(trip_id):
        route_name = f"{route['origin']} -> {route['destination']}" if route else "SmartBus route"
        message = (
            "SmartBus Alert:\n"
            f"Route {route_name}\n"
            f"Bus delayed by {delay_minutes} minutes.\n"
            f"Reason: {reason}\n"
            f"Track: {tracking_url}"
        )
        results.append(_system_notify(user, booking["id"], "SmartBus: your bus is delayed", message))
    return results


def send_trip_started_alerts(trip_id, tracking_url):
    results = []
    for user, booking, _route in _confirmed_trip_passengers(trip_id):
        message = f"SmartBus:\nYour bus has departed.\nTrack live:\n{tracking_url}"
        results.append(_system_notify(user, booking["id"], "SmartBus: your trip has started", message))
    return results


def send_trip_completed_alerts(trip_id):
    results = []
    for user, booking, _route in _confirmed_trip_passengers(trip_id):
        message = "SmartBus:\nThank you for travelling with us.\nTrip completed successfully."
        results.append(_system_notify(user, booking["id"], "SmartBus: trip completed", message))
    return results
