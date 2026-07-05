from flask import Blueprint,render_template,session,send_from_directory,current_app
from services.auth import role_required
from services.database import db
customer_bp=Blueprint("customer",__name__,url_prefix="/customer")
@customer_bp.get("/dashboard")
@role_required("customer")
def dashboard(): return render_template("customer/dashboard.html",bookings=db.all("bookings",user_id=session["user_id"]))
@customer_bp.get("/history")
@role_required("customer")
def history(): return render_template("customer/history.html",bookings=db.all("bookings",user_id=session["user_id"]))
@customer_bp.get("/ticket/<name>")
@role_required("customer","admin")
def ticket(name): return send_from_directory(current_app.config["TICKET_DIR"],name,as_attachment=True)
