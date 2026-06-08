The due_diligence blueprint must be registered in app/__init__.py.

Add this import inside create_app with the other blueprint imports:
from app.due_diligence.routes import due_diligence_bp

Add this registration after the other app.register_blueprint(...) calls:
app.register_blueprint(due_diligence_bp)
