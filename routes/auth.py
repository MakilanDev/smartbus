from flask import Blueprint,render_template,request,redirect,url_for,session,flash
from werkzeug.security import generate_password_hash,check_password_hash
from services.database import db
from services.auth import login_required
from services.notifications import notify
auth_bp=Blueprint("auth",__name__)
def verify(stored,password): return stored=="dev:"+password or (not stored.startswith("dev:") and check_password_hash(stored,password))
def do_login(role,hidden=False):
 if request.method=="POST":
  user=db.one("users",email=request.form.get("email","").strip().lower())
  if user and user.get("role")==role and verify(user["password_hash"],request.form.get("password","")):
   session.clear(); session.update(user_id=user["id"],name=user["full_name"],role=user["role"])
   return redirect(url_for("admin.dashboard" if role=="admin" else "driver.dashboard" if role=="driver" else "customer.dashboard"))
  flash("Invalid login details","danger")
 return render_template("auth.html",role=role,hidden=hidden)
@auth_bp.route("/customer-login",methods=["GET","POST"])
def customer_login(): return do_login("customer")
@auth_bp.route("/driver-login",methods=["GET","POST"])
def driver_login(): return do_login("driver")
@auth_bp.route("/admin-secure-login",methods=["GET","POST"])
def admin_login(): return do_login("admin",True)
@auth_bp.route("/customer-signup",methods=["GET","POST"])
def signup():
 if request.method=="POST":
  if db.one("users",email=request.form["email"].lower()): flash("Email already registered","warning")
  else:
   u=db.add("users",{"full_name":request.form["full_name"],"email":request.form["email"].lower(),"phone":request.form.get("phone"),"password_hash":generate_password_hash(request.form["password"]),"role":"customer","active":True}); session.update(user_id=u["id"],name=u["full_name"],role="customer")
   notify(u,"Welcome to SmartBus!",f"Hi {u['full_name']}, welcome to SmartBus! Your account ({u['email']}) is ready. Search routes and book your next trip anytime.")
   return redirect(url_for("customer.dashboard"))
 return render_template("signup.html")
@auth_bp.get("/logout")
def logout(): session.clear(); return redirect(url_for("main.home"))
