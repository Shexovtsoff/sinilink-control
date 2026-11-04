# 🔊 Sinilink BLE Master

Автономный Web-интерфейс, REST API и Python-библиотека для управления Bluetooth-аудиоусилителями **Sinilink** (платы серий **XY-AP100L**, **XY-AP50L**, **XY-S100L**, **XY-C50L** и других на базе чипов JieLi/AC69xx). 

Проект полностью **отвязан от Home Assistant** и работает на чистом Python с использованием библиотеки `bleak`.

---

## ✨ Возможности

- **🎛️ Полный контроль звука:**
  - Включение / выключение питания (Mute / Restore volume).
  - Регулировка громкости от 0 до 30 (ползунок + кнопки точного шага).
  - Управление воспроизведением: Play, Pause, Next track, Previous track (в режимах BT / USB).
  - Выбор источника входа: **Bluetooth**, **AUX**, **USB**, **TF Card**, **PC Audio**.
  - 6 пресетов эквалайзера (EQ): **Normal**, **Rock**, **Pop**, **Classic**, **Jazz**, **Country**.
  - Переключение **сигнала подключения по Bluetooth** (Prompt Tone).

- **⚡ Двусторонняя обратная связь в реальном времени (WebSocket):**
  - При вращении физической ручки громкости на плате усилителя или нажатии кнопок на пульте состояние в Web-интерфейсе обновляется мгновенно без перезагрузки страницы.

- **🔍 Поиск и мульти-устройства:**
  - Встроенный сканер Bluetooth эфира для поиска плат Sinilink рядом с отображением уровня сигнала (RSSI).
  - Сохранение списка усилителей с пользовательскими именами (например: *«Гостиная»*, *«Спальня»*, *«Мастерская»*).
  - Мгновенное переключение между усилителями прямо из выпадающего списка в шапке.
  - Редактирование, переименование и удаление сохранённых устройств.

- **🎨 Современный интерфейс:**
  - Выбор темы оформления: **Тёмная (Dark)** и **Светлая (Light)**.
  - Поддержка двух языков: **Русский (RU)** и **English (EN)**.
  - Адаптивный дизайн для компьютеров и смартфонов.

- **🐍 Python SDK:**
  - Модуль `sinilink_ble.py` можно импортировать в любые собственные скрипты автоматизации без веб-сервера.

---

## 🚀 Быстрый старт

### 1. Требования
- **Python 3.10+**
- Компьютер со встроенным Bluetooth или внешним USB BLE-адаптером (Windows, Linux, macOS)

### 2. Установка

```bash
# Клонируйте репозиторий
git clone https://github.com/YOUR_USERNAME/sinilink-ble-master.git
cd sinilink-ble-master

# Создайте и активируйте виртуальное окружение
python -m venv venv

# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Установите зависимости
pip install -r requirements.txt
```

### 3. Запуск

Запустите сервер командой:
```bash
python app.py
```
*На Windows также можно просто запустить файл **`run.bat`** двойным кликом.*

После запуска откройте в браузере:
👉 **http://127.0.0.1:8080** (или `http://IP_ВАШЕГО_ПК:8080` с телефона в локальной сети).

---

## 📖 Использование Web-интерфейса

1. Нажмите иконку **🔍 (Поиск)** в строке выбора усилителя.
2. В открывшемся окне нажмите **«Начать сканирование эфира»**.
3. Найденная плата будет отмечена значком `Sinilink`. Нажмите **«Добавить»**, задайте удобное имя, и усилитель сразу подключится.
4. В меню **⚙️ (Настройки)** можно:
   - Переключить язык (**RU** / **EN**).
   - Выбрать тему (**Тёмная** / **Светлая**).
   - Переименовать или удалить усилители.
   - Добавить устройство вручную по MAC-адресу.

---

## 🐍 Использование в Python-скриптах (CLI / Automation)

Вы можете использовать драйвер `sinilink_ble.py` напрямую в своих программах:

```python
import asyncio
from sinilink_ble import SinilinkClient

async def main():
    # Создаем клиента (передайте MAC или оставьте пустым для автопоиска)
    client = SinilinkClient(mac="AA:BB:CC:DD:EE:FF")

    # Обработка событий в реальном времени (например, поворот ручки громкости)
    client.register_callback(lambda state: print("Новое состояние:", state))

    # Подключение
    if await client.connect():
        # Включение и установка громкости
        await client.turn_on()
        await client.set_volume(15)

        # Переключение на AUX или Bluetooth
        await client.aux()
        await asyncio.sleep(2)
        await client.bluetooth()

        # Эквалайзер
        await client.set_eq_mode("Rock")

        # Отключение
        await client.disconnect()

asyncio.run(main())
```

Пример готового скрипта доступен в файле [`example_cli.py`](example_cli.py):
```bash
python example_cli.py AA:BB:CC:DD:EE:FF
```

---

## 🔌 REST API & WebSocket

Сервер предоставляет HTTP REST API для интеграции с другими системами:

| Метод | Эндпоинт | Описание |
|---|---|---|
| `GET` | `/api/status` | Получить текущее состояние активного усилителя |
| `GET` | `/api/devices` | Список сохранённых устройств и активный MAC |
| `POST` | `/api/devices` | Сохранить/обновить усилитель `{"mac": "...", "name": "..."}` |
| `DELETE` | `/api/devices` | Удалить усилитель из списка `{"mac": "..."}` |
| `POST` | `/api/devices/select` | Переключиться на устройство `{"mac": "..."}` |
| `POST` | `/api/scan` | Запустить BLE-сканирование окружающих устройств |
| `POST` | `/api/connect` | Подключиться к устройству `{"mac": "..."}` |
| `POST` | `/api/disconnect` | Отключиться от устройства |
| `POST` | `/api/power` | Управление питанием `{"action": "on"|"off"|"toggle"}` |
| `POST` | `/api/volume` | Громкость `{"volume": 0..30}` или `{"step": 1|-1}` |
| `POST` | `/api/source` | Источник `{"source": "Bluetooth"|"AUX"|"USB"|"TF Card"|"PC Audio"}` |
| `POST` | `/api/playback` | Плеер `{"command": "play"|"pause"|"play_pause"|"next"|"prev"}` |
| `POST` | `/api/eq` | Эквалайзер `{"mode": "Normal"|"Rock"|"Pop"|"Classic"|"Jazz"|"Country"}` |
| `POST` | `/api/prompt_tone`| Переключить сигнал подключения по Bluetooth |
| `WS` | `/ws` | WebSocket для получения живых событий (`{"type": "state", "data": {...}}`) |

---

## 📁 Структура проекта

```text
├── app.py                # Web-сервер aiohttp с REST API и WebSockets
├── sinilink_ble.py       # Автономный BLE драйвер усилителей Sinilink
├── index.html            # Web-панель управления (Dark/Light темы, RU/EN)
├── example_cli.py        # Пример работы через Python-консоль
├── devices.json.example  # Пример шаблона сохранённых устройств
├── requirements.txt      # Зависимости проекта (bleak, aiohttp)
├── run.bat               # Скрипт быстрого запуска для Windows
├── .gitignore            # Исключения для Git
└── README.md             # Документация проекта
```

---

## 💡 Благодарности

Особая благодарность автору репозитория [KaroADA/ha-sinilink](https://github.com/KaroADA/ha-sinilink) за исследование и реверс-инжиниринг протокола характеристик Sinilink GATT (`0000ae10` / `0000ae04`).

---

## 📄 Лицензия

MIT License. Свободно для использования, модификации и распространения.
