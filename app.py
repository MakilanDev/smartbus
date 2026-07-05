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
    return app

app=create_app()
if __name__=="__main__": app.run(debug=True,host="0.0.0.0",port=5000)
