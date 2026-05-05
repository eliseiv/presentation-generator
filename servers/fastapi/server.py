import argparse
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI server")
    parser.add_argument(
        "--port", type=int, required=True, help="Port number to run the server on"
    )
    parser.add_argument(
        "--reload", type=str, default="false", help="Reload the server on code changes"
    )
    args = parser.parse_args()
    reload = args.reload == "true"
    host = os.getenv("FASTAPI_HOST", "127.0.0.1")

    # PPTX-to-HTML export and other in-process callers resolve `/app_data` assets here.
    public_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    os.environ.setdefault("FASTAPI_PUBLIC_URL", f"http://{public_host}:{args.port}")

    uvicorn.run(
        "api.main:app",
        host=host,
        port=args.port,
        log_level="info",
        reload=reload,
    )
