"""Route groups registered by the desk composition root."""


def register(app):
    from ops.routes.pages import bp as pages_bp
    from ops.routes.paper_api import bp as paper_bp
    from ops.routes.research_api import bp as research_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(paper_bp)
    app.register_blueprint(research_bp)
