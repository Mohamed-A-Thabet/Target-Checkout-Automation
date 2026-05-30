import os
import sys
# Make sure project directory is in import search path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
import websockets
from datetime import datetime

import src.config as config
from src.session_manager import refresh_session, login
from src.checkout import trigger
from src.otp_listener import TargetOTPListener

async def send_reply(websocket, msg_id, data_payload):
    """Formats and sends a standard reply back to the extension."""
    await websocket.send(json.dumps({
        "id": msg_id,
        "data": data_payload
    }))

async def send_error(websocket, msg_id, error_msg):
    """Sends an error if the extension asks for something weird."""
    await websocket.send(json.dumps({
        "id": msg_id,
        "error": error_msg
    }))

async def broadcast_push_event(event_type, event_data):
    """Pushes unprompted events (like live count updates) to all connected tabs."""
    if config.connected_clients:
        payload = json.dumps({"type": event_type, "data": event_data})
        # Send to all connected clients concurrently
        await asyncio.gather(*(client.send(payload) for client in config.connected_clients))

async def handler(websocket):
    config.connected_clients.add(websocket)
    print("✅ Chrome Extension connected!")
    
    try:
        async for message_str in websocket:
            parsed_message = json.loads(message_str)
            msg_id = parsed_message.get("id")
            msg_type = parsed_message.get("type")
            msg_data = parsed_message.get("data", {})

            print(f"[RCV] Type: {msg_type} | ID: {msg_id}")

            # Message Routing
            if msg_type == "init":
                await send_reply(websocket, msg_id, {
                    "numHarvested": config.app_state["numHarvested"],
                    "config": config.app_state["config"],
                    "proxyLists": config.app_state["proxyLists"]
                })

            elif msg_type == "triggerATC":
                print("triggering checkout...")
                # Run the blocking checkout sequence in a worker thread so it doesn't freeze the event loop!
                asyncio.create_task(asyncio.to_thread(trigger, msg_data['tcin']))

            elif msg_type == "refreshSession":
                print(f"Refreshing session at {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
                # Run the blocking session refresh in a worker thread
                asyncio.create_task(asyncio.to_thread(refresh_session))

            elif msg_type == "getAntiBotMouseAndStatus":
                # Static human movement path simulation
                await send_reply(websocket, msg_id, {
                    "needsMoreData": True, 
                    "mousePath": [
                        {"x": 150, "y": 600}, {"x": 162, "y": 598}, {"x": 178, "y": 593},
                        {"x": 195, "y": 585}, {"x": 215, "y": 572}, {"x": 238, "y": 555},
                        {"x": 265, "y": 535}, {"x": 295, "y": 512}, {"x": 328, "y": 487},
                        {"x": 363, "y": 460}, {"x": 400, "y": 432}, {"x": 438, "y": 405},
                        {"x": 475, "y": 380}, {"x": 512, "y": 357}, {"x": 548, "y": 337},
                        {"x": 582, "y": 320}, {"x": 614, "y": 307}, {"x": 643, "y": 298},
                        {"x": 670, "y": 293}, {"x": 695, "y": 292}, {"x": 718, "y": 295},
                        {"x": 739, "y": 302}, {"x": 758, "y": 313}, {"x": 775, "y": 328},
                        {"x": 790, "y": 347}, {"x": 803, "y": 369}, {"x": 814, "y": 393},
                        {"x": 822, "y": 418}, {"x": 828, "y": 444}, {"x": 832, "y": 470},
                        {"x": 835, "y": 495}, {"x": 836, "y": 520}, {"x": 835, "y": 543},
                        {"x": 832, "y": 564}, {"x": 827, "y": 582}, {"x": 820, "y": 597},
                        {"x": 810, "y": 608}, {"x": 798, "y": 615}, {"x": 785, "y": 618},
                        {"x": 770, "y": 617}, {"x": 755, "y": 612}, {"x": 742, "y": 603},
                        {"x": 732, "y": 590}, {"x": 725, "y": 573}, {"x": 722, "y": 553},
                        {"x": 725, "y": 530}, {"x": 735, "y": 505}, {"x": 750, "y": 480},
                        {"x": 770, "y": 455}, {"x": 795, "y": 432}, {"x": 820, "y": 412},
                        {"x": 845, "y": 397}, {"x": 870, "y": 387}, {"x": 890, "y": 382},
                        {"x": 905, "y": 385}, {"x": 915, "y": 395}, {"x": 922, "y": 410},
                        {"x": 925, "y": 430}, {"x": 923, "y": 452}, {"x": 915, "y": 475},
                        {"x": 900, "y": 498}, {"x": 880, "y": 518}, {"x": 855, "y": 535},
                        {"x": 825, "y": 547}, {"x": 800, "y": 552}, {"x": 775, "y": 550},
                        {"x": 755, "y": 542}, {"x": 740, "y": 528}, {"x": 732, "y": 510}, {"x": 735, "y": 488},
                        {"x": 750, "y": 465}, {"x": 775, "y": 442}, {"x": 800, "y": 420}, {"x": 825, "y": 400}
                    ]
                })

            elif msg_type == "sendAntiBotData":
                if len(config.app_state["dataArray"]) >= 250:
                    config.app_state["dataArray"].pop(0)  # remove first (oldest)
                config.app_state["dataArray"].append(msg_data)

                config.app_state["numHarvested"] += 1

                print(f"🍪 Harvested new data! Total: {len(config.app_state['dataArray'])}")

                # Automatically trigger initial OTP login after 3 harvests if not authenticated
                if config.app_state["numHarvested"] == 3 and not config.logged_in_headers:
                    listener = TargetOTPListener(os.environ.get("EMAIL"), os.environ.get("EMAIL_APP_PASSWORD"))
                    listener.start()
                    listener.arm()
                    # Run the blocking login process in a separate thread to prevent freezing
                    asyncio.create_task(asyncio.to_thread(lambda: (login(listener), listener.stop())))

                await send_reply(websocket, msg_id, {
                    "numHarvested": config.app_state["numHarvested"],
                    "nextUserAgent": config.USER_AGENT
                })

                # Push the new count to the extension UI
                await broadcast_push_event("updateAntiBotDataCount", {"numHarvested": config.app_state["numHarvested"]})

            elif msg_type == "updateAntiBotConfig":
                config.app_state["config"].update(msg_data)
                print(f"⚙️ Config updated: {config.app_state['config']}")
                await send_reply(websocket, msg_id, config.app_state["config"])

            elif msg_type == "clearAntiBotData":
                config.app_state["numHarvested"] = 0
                config.app_state["dataArray"] = []
                print("🗑️ Harvested data cleared.")
                await send_reply(websocket, msg_id, {"cleared": True, "numHarvested": 0})
                await broadcast_push_event("updateAntiBotDataCount", {"numHarvested": 0})

            else:
                print(f"⚠️ Unknown message type: {msg_type}")
                await send_error(websocket, msg_id, "Unknown message type")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        config.connected_clients.remove(websocket)
        print("❌ Chrome Extension disconnected.")

async def main():
    async with websockets.serve(handler, "localhost", 1909, ping_interval=None):
        print("🤖 Refract Python Backend listening on ws://localhost:1909")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
