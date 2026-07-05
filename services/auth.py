from functools import wraps
from flask import session,redirect,url_for,abort

def login_required(view):
 @wraps(view)
 def wrapped(*a,**k):
  if not session.get("user_id"): return redirect(url_for("auth.customer_login"))
  return view(*a,**k)
 return wrapped

def role_required(*roles):
 def deco(view):
  @wraps(view)
  def wrapped(*a,**k):
   if not session.get("user_id"): return redirect(url_for("auth.customer_login"))
   if session.get("role") not in roles: abort(403)
   return view(*a,**k)
  return wrapped
 return deco
