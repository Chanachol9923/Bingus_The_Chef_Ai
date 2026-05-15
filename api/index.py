import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BINGUS_DB_PATH", "/tmp/kitchen.db")
os.environ.setdefault("BINGUS_UPLOAD_DIR", "/tmp/uploads")

from main import app
