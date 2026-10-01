import os
from flask import Flask, render_template


def create_app():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, instance_path=os.path.join(base, "instance"))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "insightiq-dev-secret-change-me"),
        DATABASE=os.path.join(base, "instance", "insightiq.db"),
        UPLOAD_FOLDER=os.path.join(base, "uploads"),
        SAMPLE_DIR=os.path.join(base, "sample_data"),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    )
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import db
    db.init_app(app)

    from .routes import bp, seed_demo
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="That page doesn't exist."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="File is too large (25 MB limit)."), 413

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500, message="Something went wrong on our side."), 500

    with app.app_context():
        db.init_db()
        seed_demo()
    return app
