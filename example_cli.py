"""
Пример использования автономного SinilinkClient в Python-скриптах.
Запуск:
    python example_cli.py
или:
    python example_cli.py AA:BB:CC:DD:EE:FF
"""

import asyncio
import sys
from sinilink_ble import SinilinkClient


async def main():
    # MAC-адрес можно передать аргументом: python example_cli.py AA:BB:CC:DD:EE:FF
    mac = sys.argv[1] if len(sys.argv) > 1 else None
    client = SinilinkClient(mac=mac)

    def on_change(state):
        print(f"[State Update] Vol={state['volume']}, Source={state['source']}, On={state['is_on']}, Playing={state['is_playing']}")

    client.register_callback(on_change)

    if not mac:
        print("MAC-адрес не указан. Поиск доступных усилителей Sinilink...")
        devices = await SinilinkClient.scan_devices(timeout=5.0)
        sinilink_devs = [d for d in devices if d["is_sinilink"]]
        if not sinilink_devs:
            print("Устройства Sinilink не найдены.")
            return
        mac = sinilink_devs[0]["mac"]
        print(f"Выбрано первое найденное устройство: {sinilink_devs[0]['name']} [{mac}]")

    print(f"Подключение к {mac}...")
    connected = await client.connect(mac=mac)
    if not connected:
        print("Не удалось подключиться")
        return

    print("Подключено! Текущее состояние:", client.get_state())

    print("Включение питания...")
    await client.turn_on()
    await asyncio.sleep(2)

    print("Установка громкости на 12...")
    await client.set_volume(12)
    await asyncio.sleep(2)

    print("Переключение на AUX...")
    await client.aux()
    await asyncio.sleep(2)

    print("Переключение на Bluetooth...")
    await client.bluetooth()
    await asyncio.sleep(2)

    print("Отключение...")
    await client.disconnect()
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
