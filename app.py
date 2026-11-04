import asyncio
import json
import logging
import os
from aiohttp import web, WSMsgType
from sinilink_ble import SinilinkClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Sinilink-App")

DEVICES_FILE = "devices.json"


def load_devices_config():
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Error reading devices.json: %s", e)
    return {
        "active_mac": None,
        "devices": []
    }


def save_devices_config(cfg):
    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Error saving devices.json: %s", e)


devices_cfg = load_devices_config()
active_mac = devices_cfg.get("active_mac")
if not active_mac and devices_cfg.get("devices"):
    active_mac = devices_cfg["devices"][0].get("mac")

amp = SinilinkClient(mac=active_mac)
ws_clients = set()


def broadcast_state(state: dict):
    """Notify all connected WebSockets about state changes."""
    msg = json.dumps({"type": "state", "data": state})
    for ws in list(ws_clients):
        if not ws.closed:
            asyncio.create_task(ws.send_str(msg))


amp.register_callback(broadcast_state)


# ---------------- HTTP Endpoints ----------------

async def handle_index(request):
    return web.FileResponse("index.html")


async def handle_status(request):
    return web.json_response(amp.get_state())


async def handle_get_devices(request):
    cfg = load_devices_config()
    return web.json_response({
        "active_mac": amp.mac or cfg.get("active_mac"),
        "devices": cfg.get("devices", []),
        "state": amp.get_state()
    })


async def handle_save_device(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    mac = (data.get("mac") or "").strip().upper()
    name = (data.get("name") or "").strip()
    if not mac:
        return web.json_response({"error": "MAC is required"}, status=400)

    if not name:
        name = f"Усилитель {mac[-5:]}"

    cfg = load_devices_config()
    devices = cfg.get("devices", [])
    
    # Update existing or add new
    existing = next((d for d in devices if d["mac"].upper() == mac), None)
    if existing:
        existing["name"] = name
    else:
        devices.append({"mac": mac, "name": name})

    cfg["devices"] = devices
    save_devices_config(cfg)
    logger.info("Saved device: %s [%s]", name, mac)

    return web.json_response({
        "status": "ok",
        "active_mac": amp.mac or cfg.get("active_mac"),
        "devices": devices
    })


async def handle_delete_device(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    mac = (data.get("mac") or "").strip().upper()
    if not mac:
        return web.json_response({"error": "MAC is required"}, status=400)

    cfg = load_devices_config()
    cfg["devices"] = [d for d in cfg.get("devices", []) if d["mac"].upper() != mac]

    # If deleting currently active device, disconnect
    if amp.mac and amp.mac.upper() == mac:
        await amp.disconnect()
        if cfg["devices"]:
            cfg["active_mac"] = cfg["devices"][0]["mac"]
            amp.mac = cfg["active_mac"]
        else:
            cfg["active_mac"] = None
            amp.mac = None

    save_devices_config(cfg)
    logger.info("Deleted device: %s", mac)

    return web.json_response({
        "status": "ok",
        "active_mac": amp.mac,
        "devices": cfg["devices"],
        "state": amp.get_state()
    })


async def handle_select_device(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    mac = (data.get("mac") or "").strip().upper()
    if not mac:
        return web.json_response({"error": "MAC is required"}, status=400)

    logger.info("Switching to device: %s", mac)
    cfg = load_devices_config()
    cfg["active_mac"] = mac
    save_devices_config(cfg)

    # Reconnect to new device
    success = await amp.connect(mac=mac)
    return web.json_response({
        "status": "ok" if success else "failed",
        "active_mac": mac,
        "connected": success,
        "state": amp.get_state()
    })


async def handle_scan(request):
    logger.info("Scan request received from web client...")
    try:
        results = await SinilinkClient.scan_devices(timeout=5.0)
        return web.json_response({"status": "ok", "devices": results})
    except Exception as e:
        logger.error("Scan error: %s", e)
        return web.json_response({"error": str(e)}, status=500)


async def handle_connect(request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    mac = data.get("mac") or amp.mac
    if not mac:
        return web.json_response({
            "error": "MAC-адрес не указан. Выберите устройство из списка или выполните поиск."
        }, status=400)

    logger.info("Connection requested for MAC: %s", mac)
    
    success = await amp.connect(mac=mac)
    if success:
        cfg = load_devices_config()
        cfg["active_mac"] = amp.mac
        save_devices_config(cfg)

        return web.json_response({
            "status": "ok",
            "message": f"Подключено к {amp.mac}",
            "state": amp.get_state()
        })
    else:
        return web.json_response({
            "error": "Не удалось подключиться к усилителю. Проверьте питание и Bluetooth."
        }, status=503)


async def handle_disconnect(request):
    await amp.disconnect()
    return web.json_response({"status": "ok", "message": "Отключено", "state": amp.get_state()})


async def handle_power(request):
    data = await request.json()
    action = data.get("action", "toggle")
    logger.info("Power requested: action=%s", action)
    
    if action == "on":
        await amp.turn_on()
    elif action == "off":
        await amp.turn_off()
    else:
        await amp.toggle_power()
        
    return web.json_response({"status": "ok", "state": amp.get_state()})


async def handle_volume(request):
    data = await request.json()
    logger.info("Volume requested: %s", data)
    if "volume" in data:
        vol = int(data["volume"])
        await amp.set_volume(vol)
    elif "step" in data:
        step = int(data["step"])
        if step > 0:
            await amp.volume_up(step)
        else:
            await amp.volume_down(abs(step))
    return web.json_response({"status": "ok", "state": amp.get_state()})


async def handle_source(request):
    data = await request.json()
    src = data.get("source")
    logger.info("Source requested: %s", src)
    if not src:
        return web.json_response({"error": "source is required"}, status=400)
    
    success = await amp.set_source(src)
    return web.json_response({"status": "ok" if success else "failed", "state": amp.get_state()})


async def handle_playback(request):
    data = await request.json()
    cmd = data.get("command")
    logger.info("Playback requested: cmd=%s", cmd)
    
    if cmd == "play":
        await amp.play()
    elif cmd == "pause":
        await amp.pause()
    elif cmd == "play_pause":
        await amp.play_pause()
    elif cmd == "next":
        await amp.next_track()
    elif cmd == "prev":
        await amp.previous_track()
    else:
        return web.json_response({"error": "Unknown command"}, status=400)
        
    return web.json_response({"status": "ok", "state": amp.get_state()})


async def handle_eq(request):
    data = await request.json()
    mode = data.get("mode")
    logger.info("EQ requested: %s", mode)
    if not mode:
        return web.json_response({"error": "mode is required"}, status=400)
    
    success = await amp.set_eq_mode(mode)
    return web.json_response({"status": "ok" if success else "failed", "state": amp.get_state()})


async def handle_prompt_tone(request):
    logger.info("Toggle prompt tone requested")
    await amp.toggle_prompt_tone()
    return web.json_response({"status": "ok", "state": amp.get_state()})


async def handle_legacy_command(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    cmd = data.get("command")
    logger.info("Legacy command received: %s", cmd)

    legacy_map = {
        "power_toggle": amp.toggle_power,
        "vol_up": lambda: amp.volume_up(1),
        "vol_down": lambda: amp.volume_down(1),
        "mute": amp.turn_off,
        "play_pause": amp.play_pause,
        "next_track": amp.next_track,
        "prev_track": amp.previous_track,
        "source_bt": amp.bluetooth,
        "source_aux": amp.aux,
        "source_usb": amp.usb,
        "source_tf": amp.tf_card,
        "source_pc": amp.pc_audio,
    }

    action_func = legacy_map.get(cmd)
    if not action_func:
        return web.json_response({"error": f"Unknown command: {cmd}"}, status=400)

    try:
        res = action_func()
        if asyncio.iscoroutine(res):
            await res
        return web.json_response({"status": "ok", "command": cmd, "state": amp.get_state()})
    except Exception as e:
        logger.error("Error executing command %s: %s", cmd, e)
        return web.json_response({"error": str(e)}, status=500)


async def handle_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    logger.info("WebSocket client connected. Total clients: %d", len(ws_clients))

    # Send current state immediately on connect
    await ws.send_str(json.dumps({"type": "state", "data": amp.get_state()}))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    action = payload.get("action")
                    if action == "get_state":
                        await ws.send_str(json.dumps({"type": "state", "data": amp.get_state()}))
                except Exception as e:
                    logger.warning("WebSocket JSON error: %s", e)
            elif msg.type == WSMsgType.ERROR:
                logger.warning("WebSocket error: %s", ws.exception())
    finally:
        ws_clients.discard(ws)
        logger.info("WebSocket client disconnected. Total clients: %d", len(ws_clients))

    return ws


async def on_cleanup(app):
    logger.info("Cleaning up BLE connection...")
    await amp.disconnect()


def create_app():
    app = web.Application()
    app.on_cleanup.append(on_cleanup)
    app.add_routes([
        web.get("/", handle_index),
        web.get("/ws", handle_websocket),
        web.get("/api/status", handle_status),
        web.get("/api/devices", handle_get_devices),
        web.post("/api/devices", handle_save_device),
        web.delete("/api/devices", handle_delete_device),
        web.post("/api/devices/select", handle_select_device),
        web.post("/api/scan", handle_scan),
        web.post("/api/connect", handle_connect),
        web.post("/api/disconnect", handle_disconnect),
        web.post("/api/power", handle_power),
        web.post("/api/volume", handle_volume),
        web.post("/api/source", handle_source),
        web.post("/api/playback", handle_playback),
        web.post("/api/eq", handle_eq),
        web.post("/api/prompt_tone", handle_prompt_tone),
        web.post("/api/command", handle_legacy_command),
    ])
    return app


if __name__ == "__main__":
    logger.info("Starting Sinilink Standalone Server at http://127.0.0.1:8080")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
