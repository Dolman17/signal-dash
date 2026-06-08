def register_due_diligence(app):
    from app.due_diligence.routes import due_diligence_bp

    app.register_blueprint(due_diligence_bp)
