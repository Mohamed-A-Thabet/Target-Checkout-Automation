import os
import json
import httpx
from pathlib import Path
from datetime import datetime
import urllib.parse as urlparse

import src.config as config
from src.antibot import update, update_shape
from src.otp_listener import TargetOTPListener
from data_loader import load_previous_session

def refresh_session():
    previous_session = load_previous_session()

    if not previous_session:
        print("No previous session. Returning...")
        return False
    
    config.logged_in_headers = previous_session.get("logged_in_headers")
    config.logged_in_cookies = previous_session.get("logged_in_cookies")

    print("filled headers/cookies")

    session = httpx.Client(http2=True, headers=config.logged_in_headers, follow_redirects=True)
    for cookie in config.logged_in_cookies:
        session.cookies.set(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path"),
        )
    
    print("Getting auth code...")
    REQUEST_VERIFICATION_QUERY = "https://gsp.target.com/gsp/authentications/v1/auth_codes?client_id=ecom-web-1.0.0" 
    response = session.get(REQUEST_VERIFICATION_QUERY, timeout=10, follow_redirects=False)
    i = 0
    while i < 2 and (response.status_code != 302 or not response.headers.get('Location') or "code" not in response.headers.get('Location')):
        print(response.status_code, " error with getting verification query. retrying...")
        update_shape(session)
        response = session.get(REQUEST_VERIFICATION_QUERY, timeout=10, follow_redirects=False)
        i += 1
        
    location = response.headers.get('Location')
    if response.status_code != 302 or not location or "code" not in location:
        print(response.status_code, " error with getting verification query. Logging in...")
        listener = TargetOTPListener(os.environ.get("EMAIL"), os.environ.get("EMAIL_APP_PASSWORD"))
        listener.start()
        listener.arm()
        login(listener) 
        listener.stop()
        return False
    
    print(f"✅ Received auth code. Getting access token from {location}...")
    parsed_url = urlparse.urlparse(location)
    auth_code = urlparse.parse_qs(parsed_url.query).get('code', [None])[0]
    print(f"Extracted Auth Code: {auth_code}")
    payload = {
        'client_id': 'ecom-web-1.0.0', 
        'grant_type': 'authorization_code',
        'code': auth_code
    }
    TOKEN_ENDPOINT = "https://gsp.target.com/gsp/oauth_tokens/v2/client_tokens"
    response = session.post(TOKEN_ENDPOINT, json=payload, timeout=10)
    if response.status_code != 201:
        print(response.status_code, " error with getting access token. Loggin in...")
        listener = TargetOTPListener(os.environ.get("EMAIL"), os.environ.get("EMAIL_APP_PASSWORD"))
        listener.start()
        listener.arm()
        login(listener)  
        listener.stop()
        return False
    print(f"✅ {response.status_code} for tokens")

    save_session(session)
    return True

def save_session(session):
    cookie_data = []
    for cookie in session.cookies.jar:
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "expires": cookie.expires,
            "secure": cookie.secure,
        }
        
        if cookie.expires is not None:
            item["readable_timestamp"] = datetime.fromtimestamp(cookie.expires).strftime('%Y-%m-%d %H:%M:%S')
        
        cookie_data.append(item)

    config.logged_in_headers = dict(session.headers)
    config.logged_in_headers.pop("x-application-mouse-tool-key", None)
    config.logged_in_cookies = cookie_data
    print(f"Headers exported: {len(list(config.logged_in_headers.keys()))}")
    print(f"Cookies exported: {len(config.logged_in_cookies)}")

    session_data = {
        "logged_in_headers": config.logged_in_headers,
        "logged_in_cookies": config.logged_in_cookies
    }

    config.previous_session = session_data

    filename = Path(__file__).parent.parent / "data" / "previous_session.json"
    with open(filename, "w") as f:
        json.dump(session_data, f, indent=4)

def login(listener):
    update(config.app_state["dataArray"].pop())

    headers = config.latest_session.get("headers")
    cookie = {k.strip(): v for k, v in (item.split('=', 1) for item in headers.get('cookie').split(';') if '=' in item)}
    headers.pop('cookie', None)
    body = config.latest_session.get("body")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            print("⚠️  body is a string but not valid JSON. returning.")
            return False
   
    EMAIL = os.environ.get("EMAIL")
    body["username"] = EMAIL

    try:
        session = httpx.Client(http2=True)
        session.headers.update(headers)
        session.cookies.update(cookie)
        
        update_shape(session)
        print("Inputting email...")
        REQUEST_CODE = "https://gsp.target.com/gsp/authentications/v1/secure_codes_unidentified"
        payload = body.copy()
        payload["email_id"] = EMAIL
        payload["flow"] = "otp_signin"
        payload["keep_me_signed_in"] = True
        response = session.post(REQUEST_CODE, json=payload, timeout=10)
        while len(config.app_state["dataArray"]) > 0 and response.status_code != 202:
            print(response.status_code, " error with inputting email. retrying...")
            print(response.text)
            update_shape(session)
            response = session.post(REQUEST_CODE, json=payload, timeout=10)
        if response.status_code != 202:
            print(response.status_code, " error with input email. returning...")
            return False
        
        print("✅ Passed input email. Getting code...")
        update_shape(session)
        SUBMIT_CODE = "https://gsp.target.com/gsp/authentications/v1/secure_code_verifications"
        otp_code = listener.wait_for_code(timeout=60)
        print("OTP:", otp_code, " \n logging in...")
        payload = body.copy()
        payload["code"] = otp_code  
        response = session.post(SUBMIT_CODE, json=payload, timeout=15)
        while len(config.app_state["dataArray"]) > 0 and response.status_code != 200:
            print(response.status_code, " error with loggin in. retrying...")
            update_shape(session)
            response = session.post(SUBMIT_CODE, json=payload, timeout=15)
        if response.status_code not in [200, 201, 202]:
            print(response.status_code, " error with loggin in. scraped_data_index: ", config.scraped_data_index)
            return False
        
        print("✅ Passed input code. Getting verification query...")
        REQUEST_VERIFICATION_QUERY = "https://gsp.target.com/gsp/authentications/v1/auth_codes?client_id=ecom-web-1.0.0" 
        response = session.get(REQUEST_VERIFICATION_QUERY, timeout=10, follow_redirects=False)
        if response.status_code != 302:
            print(response.status_code, " error with getting verification query. returning...")
            return False
        
        print("✅ Received verification query. Getting access token...")
        location = response.headers.get('Location')
        parsed_url = urlparse.urlparse(location)
        auth_code = urlparse.parse_qs(parsed_url.query).get('code', [None])[0]
        print(f"Extracted Auth Code: {auth_code}")
        payload = {
            'client_id': 'ecom-web-1.0.0',
            'grant_type': 'authorization_code',
            'code': auth_code
        }
        TOKEN_ENDPOINT = "https://gsp.target.com/gsp/oauth_tokens/v2/client_tokens"
        response = session.post(TOKEN_ENDPOINT, json=payload, timeout=10)
        print(f"{response.status_code} for tokens")

        if response.status_code != 201:
            print("not 201 for token. Returning...")
            return True
        
        save_session(session)
        return True
    
    except Exception as e:
        print(f"⚠️ Login Exception: {str(e)}")
        return False
