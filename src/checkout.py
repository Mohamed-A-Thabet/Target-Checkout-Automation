import os
import json
import time
import httpx
import random
import urllib.parse

import src.config as config
from src.antibot import update_shape
from src.otp_listener import TargetOTPListener
from src.session_manager import refresh_session, login
from data_loader import load_previous_session

def save_log(data):
    """Appends a new log entry to the JSON file."""
    logs = []
    try:
        with open(config.LOG_FILE, 'r') as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
            
    logs.append(data)
    
    with open(config.LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=4)

def trigger(tcin):
    if config.IS_BUSY: 
        print(f"currently busy, skipping {tcin}")
        return
    config.IS_BUSY = True

    start_trigger_time = time.perf_counter()
    
    refresh_session()
    previous_session = load_previous_session()
    logged_in_headers = previous_session.get("logged_in_headers")
    logged_in_cookies = previous_session.get("logged_in_cookies")

    session_hash = hex(random.randint(0xaaaac8, 0x1fffffffffffe0))[2:] + str(int(time.time() * 1000))
            
    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in logged_in_cookies])
    log_entry = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "token_diagnostics(cookie now)": cookie_string,
        "tcin": tcin,
        "attempts": [],
        "checkout_result": [],
        "timing_ms": {}
    }

    try:
        proxy_url = f"http://customer-{os.environ.get('OXY_USER')}-cc-US-city-new_york:{os.environ.get('OXY_PASS')}@{os.environ.get('PROXY_HOST')}:{os.environ.get('PROXY_PORT')}"
        session = httpx.Client(http2=True, headers=logged_in_headers, proxy=proxy_url)
        for cookie in logged_in_cookies:
            session.cookies.set(
                name=cookie["name"],
                value=cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path"),
            )

        ffsession = {
            "sessionHash": session_hash,
            "prevPageName": "home page",
            "prevPageType": "home page",
            "prevPageUrl": "https://www.target.com/",
            "sessionHit": 4
        }
        session.cookies['ffsession'] = urllib.parse.quote(json.dumps(ffsession, separators=(',', ':')))
        session.headers['referer'] = f"https://www.target.com/p/-/A-{tcin}"
        
        payload = {
            "cart_item": {"item_channel_id": "10", "tcin": tcin, "quantity": 1},
            "cart_type": "REGULAR", "channel_id": "10", "shopping_context": "DIGITAL"
        }
        update_shape(session)
        response = add_to_cart(session, payload, log_entry)
        i = 0
        # [401 Unauthorized/Expired token] [429 Rate_Limited]
        while i < 20 and response.status_code in [401, 429]:
            if response.status_code == 401:
                update_shape(session)
            if response.status_code == 429:
                time.sleep(random.uniform(0.3, 0.7))
            response = add_to_cart(session, payload, log_entry)
            i += 1
        if response.status_code not in [201, 206, 400]:
            print(f"❌ Add To Cart Fail: {response.status_code}")
            refresh_session()
            return
        print(f"✅ ATC SUCCESS: {response.status_code}")
        cart_id = response.json().get('cart_item_id') or ""
        
        ffsession = {
            "sessionHash": session_hash,
            "prevPageName": "toys product detail",
            "prevPageType": "product detail",
            "prevPageUrl": f"https://www.target.com/p/-/A-{tcin}",
            "sessionHit": 5
        }
        session.cookies['ffsession'] = urllib.parse.quote(json.dumps(ffsession, separators=(',', ':')))
        session.headers['referer'] = "https://www.target.com/cart"

        payload = {
            "cart_type": "REGULAR",
            "cart_subchannel": "DIGITAL",
            "channel_id": "10",
            "shopping_context": "DIGITAL"
        }
        update_shape(session)
        response = atc_put(session, payload, log_entry)
        i = 0
        while i < 20 and response.status_code in [401, 429]:
            if response.status_code == 401:
                update_shape(session)
            if response.status_code == 429:
                time.sleep(random.uniform(0.3, 0.7))
            response = atc_put(session, payload, log_entry)
            i += 1
        if response.status_code not in [200, 204]:
            print(f"❌ Finalize Fail: {response.status_code}")
            delete_order(session, cart_id, log_entry) 
            return
        print(f"✅ ATC Put SUCCESS: {response.status_code}")

        session.headers['referer'] = "https://www.target.com/checkout/start"

        payload = {"cart_type": "REGULAR", "channel_id": "10", "cart_subchannel": "DIGITAL"}
        update_shape(session)
        response = pre_checkout(session, payload, log_entry) 
        i = 0
        while i < 20 and response.status_code in [401, 429]:
            if response.status_code == 401:
                update_shape(session)
            if response.status_code == 429:
                time.sleep(random.uniform(0.3, 0.7))
            response = pre_checkout(session, payload, log_entry)  
            i += 1 
        if response.status_code not in [201, 204]:
            print(f"❌ Pre-Checkout Fail: {response.status_code}")
            if response.status_code == 400:
                return
            if response.status_code == 403:
                listener = TargetOTPListener(os.environ.get("EMAIL"), os.environ.get("EMAIL_APP_PASSWORD"))
                listener.start()
                listener.arm()
                login(listener) 
                listener.stop()
                return
            delete_order(session, cart_id, log_entry) 
            return
        print(f"✅ Pre-Checkout SUCCESS {response.status_code}")

        ffsession = {
            "sessionHash": session_hash,
            "prevPageName": "checkout order review",
            "prevPageType": "checkout",
            "prevPageUrl": "https://www.target.com/checkout",
            "sessionHit": 8
        }
        session.cookies['ffsession'] = urllib.parse.quote(json.dumps(ffsession, separators=(',', ':')))
        session.headers['referer'] = "https://www.target.com/checkout"

        payload = {
            "cart_subchannel": "DIGITAL",
            "cart_type": "REGULAR",
            "channel_id": "10"
        }
        update_shape(session)
        response = place_order(session, payload, log_entry)
        i = 0
        while i < 20 and response.status_code in [401, 429]:
            if response.status_code == 401:
                update_shape(session)
            if response.status_code == 429:
                time.sleep(random.uniform(0.3, 0.7))
            response = place_order(session, payload, log_entry)
            i += 1
        if response.status_code not in [200, 204]:
            print(f"❌ Place Order Fail: {response.status_code}")
            if response.status_code in [401, 403]:
                listener = TargetOTPListener(os.environ.get("EMAIL"), os.environ.get("EMAIL_APP_PASSWORD"))
                listener.start()
                listener.arm()
                login(listener) 
                listener.stop()
                return
            delete_order(session, cart_id, log_entry) 
            return
        print("✅ Order placed")

    except Exception as e:
        print(f"error: {str(e)}")
        log_entry["error"] = str(e)
    
    finally:
        log_entry["timing_ms"]["total_execution"] = round((time.perf_counter() - start_trigger_time) * 1000)
        save_log(log_entry)
        config.IS_BUSY = False

def add_to_cart(session, payload, log_entry):
    print("⚡ STEP 1: Executing Add To Cart...")
    ATC_URL = "https://carts.target.com/web_checkouts/v1/cart_items?field_groups=CART%2CCART_ITEMS%2CSUMMARY&key=9f36aeafbe60771e321a7cc95a78140772ab3e96"

    start_time = time.perf_counter()
    response = session.post(ATC_URL, json=payload, timeout=20)
    reponse_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["atc_latency"] = reponse_time
    log_entry["attempts"].append({
        "method": "ATC",
        "status_code": response.status_code,
        "response": response.text
    })
    return response

def atc_put(session, payload, log_entry):
    print("⚡ STEP 2: Executing ATC Put...")
    start_time = time.perf_counter()
    FINALIZE_URL = "https://carts.target.com/web_checkouts/v1/cart?cart_type=REGULAR&field_groups=ADDRESSES,CART,CART_ITEMS,FINANCE_PROVIDERS,PROMOTION_CODES,SUMMARY&key=e59ce3b531b2c39afb2e2b8a71ff10113aac2a14"
    response = session.put(FINALIZE_URL, json=payload, timeout=20)
    response_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["checkout_latency"] = response_time
    log_entry["checkout_result"].append({
        "method": "ATC_PUT",
        "status_code": response.status_code,
        "response": response.text
    })
    return response

def pre_checkout(session, payload, log_entry):
    print("🛡️  STEP 3: Pre-Checkout...")
    PRE_CHECKOUT_URL = "https://carts.target.com/web_checkouts/v1/pre_checkout?cart_type=REGULAR&key=e59ce3b531b2c39afb2e2b8a71ff10113aac2a14"

    start_time = time.perf_counter()
    response = session.post(PRE_CHECKOUT_URL, json=payload, timeout=20)
    response_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["pre_checkout_latency"] = response_time
    log_entry["checkout_result"].append({
        "method": "Pre_Checkout",
        "status_code": response.status_code,
        "response": response.text
    })
    return response

def place_order(session, payload, log_entry):
    print("🚀 STEP 5: Placing Order...")
    PLACE_ORDER_URL = "https://carts.target.com/web_checkouts/v1/checkout?cart_type=REGULAR&field_groups=ADDRESSES,CART,CART_ITEMS,PAYMENT_INSTRUCTIONS,PICKUP_INSTRUCTIONS,PROMOTION_CODES,SUMMARY,DELIVERY_WINDOWS,FINANCE_PROVIDERS&key=e59ce3b531b2c39afb2e2b8a71ff10113aac2a14"

    start_time = time.perf_counter()
    response = session.post(PLACE_ORDER_URL, json=payload, timeout=20)
    reponse_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["place_order_latency"] = reponse_time
    log_entry["checkout_result"].append({
        "step": "place_order",
        "status_code": response.status_code,
        "response_preview": response.text if response.text else ""
    })
    return response

def delete_order(session, cart_id, log_entry):
    print("Deleting order...")
    DELETE_ORDER_URL = f"https://carts.target.com/web_checkouts/v1/cart_items/{cart_id}?cart_type=REGULAR&field_groups=ADDRESSES,CART,CART_ITEMS,PAYMENT_INSTRUCTIONS,PICKUP_INSTRUCTIONS,PROMOTION_CODES,SUMMARY,DELIVERY_WINDOWS,FINANCE_PROVIDERS&key=e59ce3b531b2c39afb2e2b8a71ff10113aac2a14"

    start_time = time.perf_counter()
    response = session.delete(DELETE_ORDER_URL, timeout=20)
    reponse_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["delete_order_latency"] = reponse_time
    log_entry["checkout_result"].append({
        "step": "delete_order",
        "status_code": response.status_code,
        "response_preview": response.text if response.text else ""
    })

    i = 0
    while i < 2 and response.status_code != 200:
        print(f"❌ Delete Order Fail: {response.status_code}")
        update_shape(session)

        start_time = time.perf_counter()
        response = session.delete(DELETE_ORDER_URL, timeout=15)
        reponse_time = round((time.perf_counter() - start_time) * 1000)
        
        log_entry["timing_ms"]["delete_order_latency"] = reponse_time
        log_entry["checkout_result"].append({
            "step": "delete_order",
            "status_code": response.status_code,
            "response_preview": response.text if response.text else ""
        })
        i += 1
    if response.status_code != 200:
        print(f"❌ Delete Order Fail: {response.status_code}")
        refresh_session()
        return
    print("✅ Order deleted")  

def clear_cart(session, log_entry):    
    print("Deleting cart...")
    DELETE_ORDER_URL = "https://carts.target.com/web_checkouts/v1/cart_clears?cart_type=REGULAR&field_groups=ADDRESSES,CART,CART_ITEMS,PAYMENT_INSTRUCTIONS,PICKUP_INSTRUCTIONS,PROMOTION_CODES,SUMMARY,DELIVERY_WINDOWS,FINANCE_PROVIDERS&key=e59ce3b531b2c39afb2e2b8a71ff10113aac2a14"

    start_time = time.perf_counter()
    response = session.delete(DELETE_ORDER_URL, timeout=15)
    reponse_time = round((time.perf_counter() - start_time) * 1000)
    
    log_entry["timing_ms"]["delete_cart_latency"] = reponse_time
    log_entry["checkout_result"].append({
        "step": "delete_cart",
        "status_code": response.status_code,
        "response_preview": response.text if response.text else ""
    })

    i = 0
    while i < 2 and response.status_code != 200:
        print(f"❌ Delete Cart Fail: {response.status_code}")
        update_shape(session)

        start_time = time.perf_counter()
        response = session.delete(DELETE_ORDER_URL, timeout=15)
        reponse_time = round((time.perf_counter() - start_time) * 1000)
        
        log_entry["timing_ms"]["delete_cart_latency"] = reponse_time
        log_entry["checkout_result"].append({
            "step": "delete_cart",
            "status_code": response.status_code,
            "response_preview": response.text if response.text else ""
        })
    if response.status_code != 200:
        print(f"❌ Delete Cart Fail: {response.status_code}")
        return
    print("✅ Order deleted")  
