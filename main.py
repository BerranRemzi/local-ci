import os

from app.routes import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("LOCAL_CI_HOST", "0.0.0.0")
    port = int(os.environ.get("LOCAL_CI_PORT", "5000"))
    debug = os.environ.get("LOCAL_CI_DEBUG", "").lower() in ("1", "true", "yes")

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve
        print(f"Local CI running on http://{host}:{port}")
        serve(app, host=host, port=port)
