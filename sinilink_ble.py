import asyncio
import datetime
import logging
import random
from typing import Callable, Optional, Dict, Any, List
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

_LOGGER = logging.getLogger("SinilinkBLE")

WRITE_UUID = "0000ae10-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ae04-0000-1000-8000-00805f9b34fb"

EQ_MAP = {
    "Normal": 0x09,
    "Rock": 0x0A,
    "Pop": 0x0B,
    "Classic": 0x0C,
    "Jazz": 0x0D,
    "Country": 0x0E,
}
EQ_REV_MAP = {v: k for k, v in EQ_MAP.items()}

SOURCE_MAP = {
    0x14: "Bluetooth",
    0x16: "AUX",
    0x04: "USB",
    0x03: "TF Card",
    0x15: "PC Audio",
}

class SinilinkClient:
    """Standalone client to control Sinilink BLE audio amplifiers."""

    def __init__(self, mac: Optional[str] = None) -> None:
        self._mac = mac
        self._device: Optional[BleakClient] = None
        
        # Device state
        self._is_on: bool = False
        self._volume: int = 0
        self._saved_volume: int = 7
        self._source: str = "AUX"
        self._is_playing: bool = False
        self._prompt_tone: bool = True
        self._eq_mode: str = "Normal"
        self._last_seen: Optional[datetime.datetime] = None
        
        # Internal synchronizations and buffers
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._buffer = bytearray()
        self._should_reconnect = True

    # ---------------- State Properties ----------------

    @property
    def mac(self) -> Optional[str]:
        return self._mac

    @mac.setter
    def mac(self, address: str) -> None:
        self._mac = address

    @property
    def is_connected(self) -> bool:
        return self._device is not None and self._device.is_connected

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def source(self) -> str:
        return self._source

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def prompt_tone(self) -> bool:
        return self._prompt_tone

    @property
    def eq_mode(self) -> str:
        return self._eq_mode

    @property
    def last_seen(self) -> Optional[datetime.datetime]:
        return self._last_seen

    def get_state(self) -> Dict[str, Any]:
        """Return dict representation of current amplifier state."""
        return {
            "mac": self._mac,
            "connected": self.is_connected,
            "is_on": self._is_on,
            "volume": self._volume,
            "source": self._source,
            "is_playing": self._is_playing,
            "prompt_tone": self._prompt_tone,
            "eq_mode": self._eq_mode,
            "last_seen": self._last_seen.isoformat() if self._last_seen else None,
        }

    # ---------------- Callbacks ----------------

    def register_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback to be called on state change."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Unregister a previously registered callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self) -> None:
        state = self.get_state()
        for cb in list(self._callbacks):
            try:
                cb(state)
            except Exception as e:
                _LOGGER.error("Error in state callback: %s", e)

    # ---------------- BLE Connection & Scanning ----------------

    @staticmethod
    async def scan_devices(timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Scan for nearby BLE devices and return list of potential amplifiers."""
        _LOGGER.info("Starting BLE scan for amplifiers (timeout=%.1fs)...", timeout)
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        results = []
        for d, adv in discovered.values():
            name = (d.name or adv.local_name or "").strip()
            # Recognize known prefix markers
            is_sinilink = any(k in name.upper() for k in ("SINILINK", "XY-", "APP", "XIN-LIAN", "SHANHAI", "AUDIO", "BT-"))
            results.append({
                "name": name if name else "Неизвестное устройство",
                "mac": d.address,
                "rssi": adv.rssi if adv.rssi is not None else -99,
                "is_sinilink": is_sinilink,
            })

        # Sort Sinilink candidates first, then by signal strength (RSSI)
        results.sort(key=lambda x: (x["is_sinilink"], x["rssi"]), reverse=True)
        _LOGGER.info("Scan completed. Found %d devices (%d Sinilink candidates).", len(results), sum(1 for r in results if r["is_sinilink"]))
        return results

    async def scan_and_find(self, timeout: float = 6.0) -> Optional[str]:
        """Scan for nearby Sinilink BLE devices and save the MAC address."""
        devices = await self.scan_devices(timeout=timeout)
        for d in devices:
            if d["is_sinilink"]:
                _LOGGER.info("Auto-selected Sinilink device: %s [%s]", d["name"], d["mac"])
                self._mac = d["mac"]
                return d["mac"]
        _LOGGER.warning("No Sinilink device found during scan.")
        return None

    async def connect(self, mac: Optional[str] = None, max_attempts: int = 3) -> bool:
        """Connect to the amplifier and initialize notifications."""
        if mac:
            if self._mac and self._mac.upper() != mac.upper() and self.is_connected:
                _LOGGER.info("Switching device: disconnecting from %s before connecting to %s", self._mac, mac)
                await self.disconnect()
            self._mac = mac

        if not self._mac:
            found = await self.scan_and_find()
            if not found:
                _LOGGER.error("Cannot connect: MAC address is not specified and scan found nothing.")
                return False

        async with self._connect_lock:
            if self.is_connected:
                return True

            for attempt in range(1, max_attempts + 1):
                try:
                    _LOGGER.info("Connecting to %s (attempt %d/%d)...", self._mac, attempt, max_attempts)
                    client = BleakClient(
                        self._mac,
                        disconnected_callback=self._on_disconnected
                    )
                    await client.connect()

                    if client.is_connected:
                        self._device = client
                        _LOGGER.info("Connected to %s! Setting up notifications...", self._mac)
                        
                        # Log discovered services & characteristics for debugging
                        for s in client.services:
                            _LOGGER.info("GATT Service: %s", s.uuid)
                            for c in s.characteristics:
                                _LOGGER.info("  Char: %s, Props: %s", c.uuid, c.properties)

                        try:
                            await client.start_notify(NOTIFY_UUID, self._notification_handler)
                            # Wait for CCCD subscription to settle (2.0s as in ha-sinilink)
                            await asyncio.sleep(2.0)
                            # Request initial device states & handshake
                            asyncio.create_task(self.request_system_settings())
                        except Exception as ne:
                            _LOGGER.warning("start_notify issue: %s", ne)

                        self._notify_callbacks()
                        return True
                except Exception as e:
                    _LOGGER.warning("Connection attempt %d failed: %s", attempt, e)
                    await asyncio.sleep(1.0)

            _LOGGER.error("Failed to connect to %s after %d attempts", self._mac, max_attempts)
            return False

    async def disconnect(self) -> None:
        """Gracefully disconnect from device."""
        self._should_reconnect = False
        if self._device and self._device.is_connected:
            try:
                await self._device.disconnect()
            except Exception as e:
                _LOGGER.warning("Error during disconnect: %s", e)
        self._device = None
        self._is_on = False
        self._volume = 0
        self._is_playing = False
        self._notify_callbacks()

    def _on_disconnected(self, client: BleakClient) -> None:
        _LOGGER.info("Disconnected from %s", self._mac)
        self._device = None
        self._is_on = False
        self._volume = 0
        self._is_playing = False
        self._notify_callbacks()

    # ---------------- Packet Sending ----------------

    async def _send_raw(self, payload: bytearray) -> bool:
        """Send raw data to WRITE_UUID."""
        if not self.is_connected or not self._device:
            _LOGGER.warning("Device not connected, attempting reconnect before sending...")
            if not await self.connect():
                _LOGGER.error("Failed to reconnect. Drop payload.")
                return False

        async with self._write_lock:
            _LOGGER.info(">>> BLE WRITE [%s]: %s", WRITE_UUID, payload.hex())
            try:
                # 1. First attempt: standard write (matching ha-sinilink behavior)
                await self._device.write_gatt_char(WRITE_UUID, payload)
                await asyncio.sleep(0.08)
                return True
            except BleakError as e:
                _LOGGER.warning("Standard write failed (%s). Retrying with response=False...", e)
                try:
                    await self._device.write_gatt_char(WRITE_UUID, payload, response=False)
                    await asyncio.sleep(0.08)
                    return True
                except Exception as e_retry:
                    _LOGGER.error("Both write methods failed: %s", e_retry)
                    return False
            except Exception as e:
                _LOGGER.error("Unexpected error during write: %s", e)
                return False

    async def _send(self, data: bytes | bytearray) -> bool:
        """Send data with single-byte checksum appended."""
        checksum = sum(data) & 0xFF
        payload = bytearray(data)
        payload.append(checksum)
        return await self._send_raw(payload)

    # ---------------- Packet Reception & Notification ----------------

    async def _notification_handler(self, sender: Any, data: bytearray) -> None:
        """Process incoming raw notification data from NOTIFY_UUID."""
        self._last_seen = datetime.datetime.now(datetime.timezone.utc)
        _LOGGER.debug("Notification received: %s", data.hex())
        self._buffer.extend(data)

        while len(self._buffer) >= 8:
            if self._buffer[0] != 0x7E:
                idx = self._buffer.find(0x7E)
                if idx == -1:
                    self._buffer.clear()
                    break
                self._buffer = self._buffer[idx:]
                if len(self._buffer) < 8:
                    break

            packet_len = self._buffer[1]
            if len(self._buffer) < packet_len:
                # Need more bytes to complete packet
                break

            packet = self._buffer[:packet_len]
            self._buffer = self._buffer[packet_len:]
            self._process_packet(packet)

    def _process_packet(self, data: bytearray) -> None:
        """Decode a valid, unfragmented frame."""
        packet_type = data[1]
        changed = False

        if packet_type == 0x10:
            if len(data) >= 6 and data[2] == 0x1F:
                tone = data[3]
                new_tone = (tone == 0x01)
                if self._prompt_tone != new_tone:
                    self._prompt_tone = new_tone
                    changed = True

                volume = data[5]
                if volume > 0:
                    self._saved_volume = volume
                if self._volume != volume:
                    self._volume = volume
                    self._is_on = (volume > 0)
                    changed = True

        elif packet_type == 0x0F:
            if len(data) > 4:
                source_byte = data[4]
                if source_byte in SOURCE_MAP:
                    new_src = SOURCE_MAP[source_byte]
                    if self._source != new_src:
                        self._source = new_src
                        changed = True

            if len(data) > 5:
                status_byte = data[5]
                if status_byte == 0x01 and self._is_playing:
                    self._is_playing = False
                    changed = True
                elif status_byte == 0x02 and not self._is_playing:
                    self._is_playing = True
                    changed = True

            if len(data) > 6:
                volume = data[6]
                if volume > 0:
                    self._saved_volume = volume
                if self._volume != volume:
                    self._volume = volume
                    changed = True

            if len(data) > 8:
                eq_byte = data[8]
                if eq_byte in EQ_REV_MAP:
                    new_eq = EQ_REV_MAP[eq_byte]
                    if self._eq_mode != new_eq:
                        self._eq_mode = new_eq
                        changed = True

        if changed:
            self._notify_callbacks()

    # ---------------- Amplifier Controls ----------------

    async def request_system_settings(self) -> None:
        """Query amplifier for status, prompt tone, and volume."""
        _LOGGER.info("Starting handshake (token challenge) & requesting system settings...")
        token1 = 0x03
        token2 = random.randint(1, 255)
        data = bytearray([0x7E, 0x07, 0xAA, token1, token2])
        total = sum(data)
        data.append((total >> 8) & 0xFF)
        data.append(total & 0xFF)
        await self._send_raw(data)

        await asyncio.sleep(0.6)
        try:
            if self._device:
                val = await self._device.read_gatt_char(WRITE_UUID)
                _LOGGER.info("Read after AA handshake: %s", val.hex() if val else "None")
        except Exception as e:
            _LOGGER.debug("Read after AA failed: %s", e)

        await asyncio.sleep(0.6)
        await self._send(bytes.fromhex("7e051e00"))
        await asyncio.sleep(1.2)
        await self._send(bytes.fromhex("7e051f00"))
        await asyncio.sleep(1.2)
        await self._send(bytes.fromhex("7e052000"))
        _LOGGER.info("Handshake and system settings sequence completed.")

    async def set_volume(self, volume: int) -> bool:
        """Set volume (0..30)."""
        volume = max(0, min(30, int(volume)))
        header = bytes.fromhex("7e0f1d")
        command = volume.to_bytes(1, "big")
        params = bytes.fromhex("00000000000000000000")
        success = await self._send(header + command + params)
        if success:
            self._volume = volume
            if volume > 0:
                self._saved_volume = volume
                self._is_on = True
            else:
                self._is_on = False
            self._notify_callbacks()
        return success

    async def volume_up(self, step: int = 1) -> bool:
        return await self.set_volume(self._volume + step)

    async def volume_down(self, step: int = 1) -> bool:
        return await self.set_volume(self._volume - step)

    async def turn_on(self) -> bool:
        """Turn on the amplifier (restore saved volume)."""
        vol = self._saved_volume if self._saved_volume > 0 else 7
        return await self.set_volume(vol)

    async def turn_off(self) -> bool:
        """Turn off the amplifier (mute to 0)."""
        return await self.set_volume(0)

    async def toggle_power(self) -> bool:
        if self._is_on and self._volume > 0:
            return await self.turn_off()
        else:
            return await self.turn_on()

    async def bluetooth(self) -> bool:
        return await self._send(bytes.fromhex("7e051400"))

    async def aux(self) -> bool:
        return await self._send(bytes.fromhex("7e051600"))

    async def usb(self) -> bool:
        return await self._send(bytes.fromhex("7e050400"))

    async def tf_card(self) -> bool:
        return await self._send(bytes.fromhex("7e050300"))

    async def pc_audio(self) -> bool:
        return await self._send(bytes.fromhex("7e051500"))

    async def set_source(self, source_name: str) -> bool:
        mapping = {
            "Bluetooth": self.bluetooth,
            "AUX": self.aux,
            "USB": self.usb,
            "TF Card": self.tf_card,
            "PC Audio": self.pc_audio,
        }
        fn = mapping.get(source_name)
        if fn:
            return await fn()
        return False

    async def set_eq_mode(self, mode: str) -> bool:
        if mode in EQ_MAP:
            cmd = bytearray([0x7E, 0x05, EQ_MAP[mode], 0x00])
            return await self._send(cmd)
        return False

    async def play_pause(self) -> bool:
        return await self._send(bytes.fromhex("7e050100"))

    async def play(self) -> bool:
        if not self._is_playing:
            return await self.play_pause()
        return True

    async def pause(self) -> bool:
        if self._is_playing:
            return await self.play_pause()
        return True

    async def next_track(self) -> bool:
        return await self._send(bytes.fromhex("7e050800"))

    async def previous_track(self) -> bool:
        return await self._send(bytes.fromhex("7e050700"))

    async def toggle_prompt_tone(self) -> bool:
        return await self._send(bytes.fromhex("7e051800"))
