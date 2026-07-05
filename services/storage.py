import os
import uuid
from flask import current_app
from services.database import db

def upload(file, bucket="bus-assets", folder="uploads"):
    if not file or not getattr(file, "filename", ""):
        return ""
    client = db.connect()
    if client:
        name = f"{folder}/{file.filename}"
        client.storage.from_(bucket).upload(name, file.read(), {"content-type": file.mimetype, "upsert": "true"})
        return client.storage.from_(bucket).get_public_url(name)
    # Local fallback so photo uploads still work without Supabase configured.
    safe_ext = os.path.splitext(file.filename)[1][:10] or ".jpg"
    filename = f"{uuid.uuid4().hex}{safe_ext}"
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", folder)
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return f"/static/uploads/{folder}/{filename}"
