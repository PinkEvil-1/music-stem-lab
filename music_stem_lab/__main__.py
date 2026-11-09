import argparse
import uvicorn
from .app import create_app
from .domain import Settings

def main():
    parser = argparse.ArgumentParser(description="Music Stem Lab local coordinator")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--enable-download", action="store_true",
                        help="Enable real source downloading for download_audio jobs")
    args = parser.parse_args()
    uvicorn.run(create_app(Settings(enable_download=args.enable_download)),
                host="127.0.0.1", port=args.port, access_log=False)

if __name__ == "__main__":
    main()
