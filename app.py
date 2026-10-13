"""AeroPulse Application Root Entrypoint."""
import os, sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from main import app
__all__ = ['app']
if __name__ == '__main__':
    import uvicorn
    host = os.getenv('AEROPULSE_HOST', '0.0.0.0')
    port = int(os.getenv('AEROPULSE_PORT', '8000'))
    uvicorn.run('main:app', host=host, port=port, reload=False)
