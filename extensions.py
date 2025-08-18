# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# Inicia as extensões sem vincular a uma aplicação ainda
db = SQLAlchemy()
login_manager = LoginManager()