from flask import Flask, redirect, url_for
from flask_login import current_user

from app.config import Config
from app.extensions import db, migrate, login_manager, csrf
from app.models import User


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    config_class.ensure_local_directories(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.upload.routes import upload_bp
    from app.documents.routes import documents_bp
    from app.actions.routes import actions_bp
    from app.risks.routes import risks_bp
    from app.insights.routes import insights_bp
    from app.briefings.routes import briefings_bp
    from app.settings.routes import settings_bp
    from app.ingest.routes import ingest_bp
    from app.due_diligence.registration import register_due_diligence

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(risks_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(briefings_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(ingest_bp)
    register_due_diligence(app)

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    return app
