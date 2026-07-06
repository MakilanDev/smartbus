import os
from flask import Flask
from config import Config
from services.database import db

def create_app():
    app=Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config["TICKET_DIR"],exist_ok=True)
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.customer import customer_bp
    from routes.driver import driver_bp
    from routes.api import api_bp
    for bp in (main_bp,auth_bp,admin_bp,customer_bp,driver_bp,api_bp): app.register_blueprint(bp)
    @app.context_processor
    def globals(): return {"maps_key":app.config["GOOGLE_MAPS_API_KEY"]}
    @app.errorhandler(404)
    def not_found(e): return ("Page not found",404)

    # --- Startup persistence check -----------------------------------
    # Runs once when the server boots, so Render's logs immediately show
    # whether data will actually be saved permanently (Supabase) or only
    # temporarily (in-memory / local disk, wiped on every restart/redeploy/
    # free-tier spin-down). Check this in the Render "Logs" tab right after
    # a deploy or a wake-up from sleep.
    with app.app_context():
        print("=" * 60)
        if app.config.get("SUPABASE_URL") and app.config.get("SUPABASE_KEY"):
            if db.connect():
                print("[STARTUP] Supabase connected — data WILL persist.")
            else:
                print("[STARTUP] Supabase keys present but connection FAILED.")
                print("[STARTUP] Data will be LOST on next restart/redeploy/sleep.")
        else:
            print("[STARTUP] No SUPABASE_URL/SUPABASE_KEY configured.")
            print("[STARTUP] Running on TEMPORARY in-memory data only.")
            print("[STARTUP] Data will be LOST on next restart/redeploy/sleep.")
        print("=" * 60)

    return app

app=create_app()
if __name__=="__main__": app.run(debug=True,host="0.0.0.0",port=5000)
