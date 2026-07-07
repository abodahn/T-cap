"""WSGI entry point for production servers (Render/gunicorn: `gunicorn wsgi:app`)."""
from app import create_app

app = create_app()
