import os
import sys
# Ensure imports work regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
import hashlib
import requests
import websocket
import winsound
from datetime import datetime
from dotenv import load_dotenv

from data_loader import load_items, load_stores

# Load environment variables
load_dotenv()
last_hash = None

class TargetMonitor:
    BASE_URL = "https://redsky.target.com/redsky_aggregations/v1/web/product_summary_with_fulfillment_v1"
    API_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
    
    OXY_USER = os.environ.get("OXY_USER")
    OXY_PASS = os.environ.get("OXY_PASS")
    PROXY_HOST = os.environ.get("PROXY_HOST")
    PROXY_PORT = os.environ.get("PROXY_PORT")
    CITY = "new_york" 
    
    # Check if proxy details are configured
    if all([OXY_USER, OXY_PASS, PROXY_HOST, PROXY_PORT]):
        entry = f"http://customer-{OXY_USER}-cc-US-city-{CITY}:{OXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
        proxy = {"http": entry, "https": entry}
    else:
        proxy = None

    store = {"name": "Brooklyn Bay Parkway", "id": "3356", "zipcode": "11214"}

    def __init__(self):
        self.items = load_items()
        self.all_items = []
        self.in_stock_items = []
        self.error = ""
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if self.proxy:
            self.session.proxies = self.proxy

    def check_all(self):            
        tcins_string = ",".join(self.items)
        params = {
            "key": self.API_KEY,
            "tcins": tcins_string,
            "store_id": self.store['id'],
            "zip": self.store['zipcode'],
            "has_required_fulfillment": "true"
        }
        
        print(f"Checking {len(self.items)} items")

        try: 
            response = self.session.get(self.BASE_URL, params=params, timeout=5)
            if response.status_code != 200:
                print(f"❌ Error {response.status_code}")
                self.error = f"{response.status_code} - {response.text[:500]}"
                return
        except requests.exceptions.RequestException as e:
            print(f"❌ Connection/Proxy Error: {e}")
            self.error = f"Connection error: {e}"
            return

        data = response.json().get('data', {})
        summaries = data.get('product_summaries', [])
        print(f"    ✓ Received {len(summaries)} results")

        for summary in summaries:
            tcin = summary['tcin']
            product_name = summary["item"]["product_description"]["title"]
            url = summary["item"]["enrichment"]["buy_url"]
            is_out_of_stock_in_all_store_locations = summary["fulfillment"]["is_out_of_stock_in_all_store_locations"]
            sold_out = summary["fulfillment"]["sold_out"]
            delivery_status = summary["fulfillment"]["shipping_options"]["availability_status"]
            pickup_status = summary["fulfillment"]["store_options"][0]["order_pickup"]["availability_status"]
            instore_status = summary["fulfillment"]["store_options"][0]["in_store_only"]["availability_status"]
            
            # Stock checks
            out_stock = ((delivery_status == 'PRE_ORDER_UNSELLABLE' or
                        delivery_status == 'OUT_OF_STOCK') and
                        pickup_status == 'UNAVAILABLE' and
                        (instore_status == 'NOT_SOLD_IN_STORE' or
                        instore_status == 'OUT_OF_STOCK'))

            result = {
                "product_name": product_name,
                "is_out_of_stock_in_all_store_locations": is_out_of_stock_in_all_store_locations,
                "sold_out": sold_out,
                "url": url,
                "tcin": tcin,
                "store_name": self.store['name'],
                "store_id": self.store['id'],
                "delivery_status": delivery_status,
                "pickup_status": pickup_status,
                "instore_status": instore_status,
            }

            self.all_items.append(result)
            if not out_stock:
                self.in_stock_items.append(result)

def run_monitor():
    target = TargetMonitor()
    target.check_all()
    return target.all_items, target.in_stock_items, target.error

def save_unique_output(output_file='target_monitor_log.json'):
    global ws, last_hash
    
    # Try to load last hash from existing log file if it exists
    if os.path.exists(output_file):
        with open(output_file, 'r') as f:
            last_line = None
            for line in f:
                if line.strip():
                    last_line = line
            
            if last_line:
                try:
                    last_entry = json.loads(last_line)
                    last_hash = last_entry.get('hash')
                    print(f"Loaded existing log. Previous state hash: {last_hash if last_hash else 'None'}")
                except json.JSONDecodeError:
                    print("Warning: Could not decode the last line of the log file.")
            
    print(f"Starting monitor... Logging to {output_file}")

    try:
        while True:
            readable_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            print(f"[{readable_timestamp}]")

            # Check if we are at the top of the hour (hourly session refresh)
            if datetime.now().minute == 0:
                print("Minute is 0. Refreshing session and sleeping for 60s...")
                try:
                    ws.send(json.dumps({"id": "", "type": "refreshSession", "data": {}}))
                except Exception as e:
                    print(f"Could not request session refresh: {e}")
                time.sleep(61) 
                continue 
            
            all_items, in_stock_items, error = run_monitor() 

            if error:
                last_hash = "error"
                entry = {
                    'hash': 'error',
                    'readable_timestamp': readable_timestamp,
                    'error': error,
                }                
                with open(output_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
                print("Sleeping 1 second until next check...\n")
                time.sleep(1)
                continue

            current_hash = hashlib.md5(json.dumps(all_items, sort_keys=True).encode()).hexdigest()
        
            if current_hash != last_hash:
                print("→ State change detected!")
                print(f"Items: {len(all_items)}, In stock: {len(in_stock_items)}")
        
                if len(in_stock_items) > 0: 
                    winsound.Beep(440, 500)
                    item = in_stock_items[0]
                    tcin = item.get('tcin')
                    print(f"!!! IN STOCK: {item.get('product_name')} ({tcin}) !!!")
                    
                    try:
                        ws.send(json.dumps({"id": "", "type": "triggerATC", "data": {"tcin": tcin, "url": item.get('url')}}))
                        print("Called receiver.py Webserver successfully")
                    except Exception as e:
                        print(f"Could not reach receiver.py Webserver: {e}. Is it running?")

                last_hash = current_hash
                
                entry = {
                    'in_stock_count': len(in_stock_items),
                    'readable_timestamp': readable_timestamp,
                    'hash': current_hash,
                    'all_items': all_items,
                    'in_stock_items': in_stock_items,
                    'total_items': len(all_items),
                }                
                with open(output_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
            else:
                print("→ No change since last check.")     
            
            sleep_time = 1
            print(f"Sleeping {sleep_time} second until next check...\n")
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print(f"\nStopped monitoring. Results saved to {output_file}")

if __name__ == "__main__":
    try:
        ws = websocket.create_connection("ws://localhost:1909")
        save_unique_output()
    except Exception as e:
        print(f"❌ Error connecting to WebSocket server: {e}")
        print("Please make sure 'python src/main.py' is running before starting the monitor.")
