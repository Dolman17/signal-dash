from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.extensions import db
from app.models import User, LoginAudit

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()

    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        user = User.query.filter_by(username=username).first()

        if user and user.is_active and user.check_password(password):
            user.last_login_at = datetime.now(timezone.utc)

            audit = LoginAudit(
                user_id=user.id,
                event_type="login_success",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            db.session.add(audit)
            db.session.commit()

            login_user(user)
            flash("Signed in successfully.", "success")
            return redirect(url_for("dashboard.index"))

        audit = LoginAudit(
            user_id=user.id if user else None,
            event_type="login_failed",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
        db.session.add(audit)
        db.session.commit()

        flash("Invalid username or password.", "error")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit = LoginAudit(
        user_id=current_user.id,
        event_type="logout",
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(audit)
    db.session.commit()

    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))
