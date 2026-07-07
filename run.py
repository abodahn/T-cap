"""T-CAP — T-Group Enterprise Control Suite. Development entry point.

Local:   python run.py       (http://127.0.0.1:8080)
Prod:    gunicorn "app:create_app()"  /  waitress-serve --call app:create_app
"""
from app import create_app
from config import Config

app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
