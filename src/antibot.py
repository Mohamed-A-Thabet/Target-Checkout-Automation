import time
import base64
import json
import collections.abc
import src.config as config

def deep_update_with_tracking(source, overrides, path=""):
    """
    Recursively updates a dict and returns a list of specific changes made.
    Change format: {"field": "headers->X-Score", "from": "old_val", "to": "new_val"}
    """
    changes = []
    for key, value in overrides.items():
        current_path = f"{path}->{key}" if path else key
        
        # 1. Handle Nested Dictionaries
        if isinstance(value, collections.abc.Mapping) and value:
            # Recursively update and collect changes from deeper levels
            sub_changes = deep_update_with_tracking(source.setdefault(key, {}), value, current_path)
            changes.extend(sub_changes)
            
        # 2. Handle Value Updates (Protect against empty overwrites)
        elif value is not None and value != "":
            old_val = source.get(key)
            if old_val != value:
                changes.append({
                    "field": current_path,
                    "from": old_val,
                    "to": value
                })
                source[key] = value
                
    return changes

def update(incoming_data):
    # incoming_data = request.json
    if not incoming_data: 
        return

    all_changes = []
    items = incoming_data if isinstance(incoming_data, list) else [incoming_data]
    
    for item in items:
        # --- Decode headers before tracking and saving ---
        if "headers" in item and isinstance(item["headers"], dict):
            for k, v in item["headers"].items():
                if isinstance(v, str):
                    try:
                        # Decode base64 to string
                        item["headers"][k] = base64.b64decode(v).decode("utf-8")
                    except Exception:
                        pass # Keep original if decoding fails for any reason
        # -----------------------------------------------------------

        item_changes = deep_update_with_tracking(config.latest_session, item)
        
        if item_changes:
            config.SESSION_VERSION += 1
            all_changes.append({
                "updates": item_changes
            })

    # ONLY touch the file inside the lock
    if all_changes:
        config.LAST_HANDSHAKE_TIME = time.time()
        
        # This block ensures only ONE request writes to the file at a time
        with config.log_lock: 
            try:
                with open("past_sessions.json", 'r') as f:
                    logs = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                logs = []

            log_entry = {
                "version": config.SESSION_VERSION,
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "total_keys_stored": len(config.latest_session),
                "diff": all_changes,
                "session_snapshot": config.latest_session.copy()
            }
            
            logs.append(log_entry)
            
            with open("past_sessions.json", 'w') as f:
                json.dump(logs, f, indent=4)

        print(f"[{time.strftime('%H:%M:%S')}] 📈 Session v{config.SESSION_VERSION} Logged Safely.")

def update_shape(session):
    if len(config.app_state["dataArray"]) == 0:
        print("No more shape headers. Refill")
        return

    last_item = config.app_state["dataArray"].pop()
    update(last_item)

    all_headers = config.latest_session.get('headers', {})
    
    keep_headers = {
        'x-gyjwza5z-a', 'x-gyjwza5z-a0', 'x-gyjwza5z-b', 'x-gyjwza5z-c',
        'x-gyjwza5z-d', 'x-gyjwza5z-e', 'x-gyjwza5z-f', 'x-gyjwza5z-z',
        'x-application-mouse-tool-key'
    }
    
    shape_headers = {}
    for k, v in all_headers.items():
        k_lower = k.lower()
        if k_lower in keep_headers or k_lower.startswith('x-gyjwza5z-') or k_lower.startswith('x-'):
            shape_headers[k] = v

    if shape_headers:
        session.headers.update(shape_headers)

    cookie_header = all_headers.get('cookie', '')
    if cookie_header and isinstance(cookie_header, str):
        try:
            new_cookies = {k.strip(): v for k, v in (item.split('=', 1) for item in cookie_header.split(';') if '=' in item)}
            critical_cookies = ['_px2', '_pxvid']
            for name, value in new_cookies.items():
                if name in critical_cookies:
                    session.cookies.set(name, value)
        except Exception as e:
            print(f"⚠️ Cookie parse error in shape update: {e}")
