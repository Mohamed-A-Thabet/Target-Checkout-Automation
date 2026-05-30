import os
import threading
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIG & GLOBALS ---
latest_session = {}
LOG_FILE = 'atc_monitor_log.json'
IS_BUSY = False
LAST_HANDSHAKE_TIME = 0
CURRENT_IAT = 0
cookie_index_removed = 0
needed_cookies = []
log_lock = threading.Lock()
SESSION_VERSION = 0
logged_in_headers = {}
logged_in_cookies = {}
scraped_data_index = 0
connected_clients = set()
login_body = {}

# Standard user agent for the session
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

# Load Oxylabs variables
OXY_USER = os.environ.get("OXY_USER")
OXY_PASS = os.environ.get("OXY_PASS")
PROXY_HOST = os.environ.get("PROXY_HOST")
PROXY_PORT = os.environ.get("PROXY_PORT")

def get_proxy_url():
    """Generates the full proxy URL based on environment configuration."""
    if all([OXY_USER, OXY_PASS, PROXY_HOST, PROXY_PORT]):
        return f"http://customer-{OXY_USER}-cc-US-city-new_york:{OXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    return None

# Build proxy list for the frontend app_state
proxy_proxies = []
proxy_url = get_proxy_url()
if proxy_url:
    proxy_proxies.append(proxy_url)

app_state = {
    "numHarvested": 0,
    "config": {
        "harvestsPerPageLoad": 1,
        "dontStopHarvesting": False,
        "expirationMinutes": 5,
        "removalOrder": "fifo",
        "proxyListId": "proxy_list_none"
    },
    "proxyLists": [
        {
            "id": "proxy_list_none",
            "name": "Local (No Proxy)",
            "proxies": []
        },
        {
            "id": "proxy_list_oxylabs_ny",
            "name": "Oxylabs New York",
            "proxies": proxy_proxies
        }
    ],
    "dataArray": []
}
