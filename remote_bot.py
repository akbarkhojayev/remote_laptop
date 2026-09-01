import os
import re
import asyncio
import subprocess
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
import psutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# O'z ma'lumotlaringizni kiriting
BOT_TOKEN = "SIZNING_BOT_TOKENINGIZ"
ADMIN_ID = 123456789  # Telegram ID raqamingiz

UZ_TZ = ZoneInfo("Asia/Tashkent")
TRACK_INTERVAL_SECONDS = 60  # Har 1 daqiqada faol dasturni hisoblaydi

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ---------- HOLATLAR (FSM) ----------
class NotifyState(StatesGroup):
    waiting_text = State()


class ClipboardState(StatesGroup):
    waiting_text = State()


# ---------- KUNLIK STATISTIKA ----------
daily_stats = {}

IGNORE_APPS = {
    "org.gnome.shell", "gnome-shell", "desktop", "mutter", "", "unknown"
}


def reset_daily_stats():
    daily_stats["date"] = datetime.now(UZ_TZ).strftime("%Y-%m-%d")
    daily_stats["app_minutes"] = Counter()
    daily_stats["battery_samples"] = []


# ---------- KLAVIATURA ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Holat"), KeyboardButton(text="📸 Kamera")],
        [KeyboardButton(text="🔊 Ovoz"), KeyboardButton(text="🔒 Qulflash")],
        [KeyboardButton(text="📋 Clipboard"), KeyboardButton(text="📅 Kunlik hisobot")],
        [KeyboardButton(text="🔔 Xabar yuborish")],
        [KeyboardButton(text="🔄 Qayta yoqish"), KeyboardButton(text="🛑 O'chirish")],
    ],
    resize_keyboard=True,
)

volume_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🔉 -10%", callback_data="vol_down"),
            InlineKeyboardButton(text="🔇 Mute", callback_data="vol_mute"),
            InlineKeyboardButton(text="🔊 +10%", callback_data="vol_up"),
        ]
    ]
)

clipboard_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 O'qish", callback_data="clip_get"),
            InlineKeyboardButton(text="📤 Yozish", callback_data="clip_set"),
        ]
    ]
)


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"confirm_{action}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"),
            ]
        ]
    )


# ---------- WAYLAND MUHITI VA FUNKSIYALAR ----------
def get_wayland_env():
    uid = os.getuid()
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
    return env


def get_wifi_name() -> str:
    try:
        output = subprocess.check_output(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], timeout=3).decode()
        for line in output.splitlines():
            if line.startswith("yes:"):
                ssid = line.split("yes:")[-1].strip()
                return ssid if ssid else "Ulangan"
    except Exception:
        pass
    return "Ulanmagan"


def get_current_volume_percent() -> str:
    env = get_wayland_env()
    try:
        output = subprocess.check_output(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], env=env, timeout=3
        ).decode()
        match = re.search(r"(\d+)%", output)
        return f"{match.group(1)}%" if match else "N/A"
    except Exception:
        return "N/A"


def is_muted() -> bool:
    env = get_wayland_env()
    try:
        output = subprocess.check_output(
            ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], env=env, timeout=3
        ).decode()
        return "yes" in output.lower()
    except Exception:
        return False


def run_volume_action(arg: str) -> str:
    env = get_wayland_env()
    if arg == "up":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], env=env, timeout=3)
    elif arg == "down":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], env=env, timeout=3)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], env=env, timeout=3)

    volume = get_current_volume_percent()
    text = f"🔊 Joriy ovoz: <b>{volume}</b>"
    if is_muted():
        text += " (O'chirilgan 🔇)"
    return text


def get_active_window_name() -> str:
    """Wayland / GNOME Shell muhitida ayni paytda ochiq va faol dasturni aniqlaydi."""
    env = get_wayland_env()
    app_name = ""

    # 1. GNOME Shell Introspect DBus orqali ochiq oynalarni o'qish (Wayland standarti)
    try:
        res = subprocess.check_output([
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell.Introspect",
            "--object-path", "/org/gnome/Shell/Introspect",
            "--method", "org.gnome.Shell.Introspect.GetWindows"
        ], env=env, timeout=2).decode()

        # JSON strukturasini ajratib olish
        match = re.search(r'(\{.*\})', res)
        if match:
            data = json.loads(match.group(1))
            for win_id, props in data.items():
                if props.get("has-focus") is True:
                    app_name = props.get("wm-class", "") or props.get("title", "")
                    break
    except Exception:
        pass

    # 2. Zaxira: Agar yuqoridagi usul bermasa, foydalanuvchi GUI jarayonlari orqali
    if not app_name:
        current_uid = os.getuid()
        for p in psutil.process_iter(["name", "uids", "cmdline"]):
            try:
                info = p.info
                if info.get("uids") and info["uids"].real == current_uid:
                    cmd = " ".join(info.get("cmdline") or []).lower()
                    if "chrome" in cmd:
                        app_name = "google-chrome"
                        break
                    elif "telegram" in cmd:
                        app_name = "telegram-desktop"
                        break
                    elif "pycharm" in cmd:
                        app_name = "pycharm"
                        break
                    elif "code" in cmd:
                        app_name = "code"
                        break
            except Exception:
                continue

    name_map = {
        "google-chrome": "Google Chrome",
        "google-chrome-stable": "Google Chrome",
        "telegramdesktop": "Telegram",
        "org.telegram.desktop": "Telegram",
        "telegram-desktop": "Telegram",
        "code": "VS Code",
        "pycharm": "PyCharm",
        "pycharm-community": "PyCharm",
        "gnome-terminal-server": "Terminal",
        "org.gnome.terminal": "Terminal",
        "org.gnome.nautilus": "Fayllar (Nautilus)",
        "firefox": "Firefox",
        "vlc": "VLC Player",
    }

    clean = app_name.lower().strip()
    return name_map.get(clean, app_name.replace("-", " ").capitalize() if app_name else "Bosh ekran")


def build_status_text() -> str:
    cpu = round(psutil.cpu_percent(interval=None))
    ram = round(psutil.virtual_memory().percent)
    
    disk = psutil.disk_usage("/")
    free_gb = disk.free / (1024 ** 3)
    disk_text = f"<b>{round(disk.percent)}%</b> ({free_gb:.1f} GB bo'sh)"

    battery = psutil.sensors_battery()
    if battery:
        bat_state = "Zaryadlanmoqda ⚡️" if battery.power_plugged else "Batareyada 🔋"
        bat_text = f"<b>{round(battery.percent)}%</b> — {bat_state}"
    else:
        bat_text = "Mavjud emas"

    wifi_name = get_wifi_name()
    volume = get_current_volume_percent()
    volume_text = f"<b>{volume}</b>" + (" (🔇)" if is_muted() else "")
    current_app = get_active_window_name()

    return (
        "💻 <b>SURFACE MONITORING</b>\n"
        "────────────────────\n"
        f"⚡️ <b>CPU:</b> <b>{cpu}%</b>\n"
        f"🧠 <b>RAM:</b> <b>{ram}%</b>\n"
        f"🔋 <b>Batareya:</b> {bat_text}\n"
        f"💽 <b>Disk:</b> {disk_text}\n"
        f"📶 <b>Wi-Fi:</b> <code>{wifi_name}</code>\n"
        f"🔊 <b>Ovoz:</b> {volume_text}\n"
        f"📱 <b>Hozir ochiq:</b> <b>{current_app}</b>\n"
        "────────────────────"
    )


def build_daily_report_text() -> str:
    stats = daily_stats
    date_str = stats.get("date", datetime.now(UZ_TZ).strftime("%Y-%m-%d"))
    battery_samples = stats.get("battery_samples", [])

    if battery_samples:
        start_percent = battery_samples[0]["percent"]
        current_percent = battery_samples[-1]["percent"]
        min_percent = min(s["percent"] for s in battery_samples)
        max_percent = max(s["percent"] for s in battery_samples)
    else:
        battery = psutil.sensors_battery()
        cur = round(battery.percent) if battery else 0
        start_percent = current_percent = min_percent = max_percent = cur

    total_minutes = sum(stats.get("app_minutes", {}).values())
    hours = total_minutes // 60
    minutes = total_minutes % 60

    top_apps = stats.get("app_minutes", Counter()).most_common(6)
    apps_lines = []
    for i, (name, count) in enumerate(top_apps):
        if name in ("Bosh ekran", ""):
            continue
        h = count // 60
        m = count % 60
        time_str = f"{h} soat {m} daqiqa" if h > 0 else f"{m} daqiqa"
        apps_lines.append(f"<b>{i + 1}. {name}</b> — {time_str}")

    apps_text = "\n".join(apps_lines) if apps_lines else "Ilovalar faolligi aniqlanmadi"

    return (
        f"📅 <b>Kunlik hisobot</b> — {date_str}\n"
        "────────────────────\n"
        f"⏱ <b>Umumiy ishlangan vaqt:</b> {hours} soat {minutes} daqiqa\n"
        f"🔋 <b>Batareya:</b> {start_percent}% ➔ {current_percent}% "
        f"(min: {min_percent}%, max: {max_percent}%)\n\n"
        f"📱 <b>Eng ko'p ishlatilgan ilovalar:</b>\n"
        f"{apps_text}\n"
        "────────────────────"
    )


# ---------- WAYLAND CLIPBOARD (wl-paste va wl-copy) ----------
def get_clipboard_text():
    env = get_wayland_env()
    try:
        output = subprocess.check_output(["wl-paste", "--no-newline"], env=env, timeout=3).decode()
        return output if output else None
    except Exception:
        return None


def set_clipboard_text(text: str):
    env = get_wayland_env()
    subprocess.run(["wl-copy", text], env=env, timeout=3, check=True)


# ---------- XAVFSIZLIK ----------
@dp.message(F.from_user.id != ADMIN_ID)
async def unauthorized(message: types.Message):
    await message.reply("⛔️ Ruxsat berilmagan!")


@dp.callback_query(F.from_user.id != ADMIN_ID)
async def unauthorized_callback(callback: CallbackQuery):
    await callback.answer("⛔️ Ruxsat berilmagan!", show_alert=True)


# ---------- ASOSIY BUYRUQLAR ----------
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 <b>Masofaviy Boshqaruv Markazi</b>\nQuyidagi menyudan foydalaning 👇", parse_mode="HTML", reply_markup=main_menu)


@dp.message(Command("status"))
@dp.message(F.text == "📊 Holat")
async def cmd_status(message: types.Message):
    await message.answer(build_status_text(), parse_mode="HTML")


@dp.message(F.text == "📅 Kunlik hisobot")
async def cmd_report(message: types.Message):
    await message.answer(build_daily_report_text(), parse_mode="HTML")


@dp.message(Command("photo"))
@dp.message(F.text == "📸 Kamera")
async def cmd_photo(message: types.Message):
    msg = await message.answer("📸 Surat olinmoqda (fokus sozlanmoqda)...")
    cam_file = "/tmp/cam_shot.jpg"

    if os.path.exists(cam_file):
        os.remove(cam_file)

    try:
        subprocess.run(
            [
                "fswebcam",
                "-r", "1920x1080",
                "-S", "25",
                "--jpeg", "95",
                "--no-banner",
                cam_file
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=True,
        )
        photo = FSInputFile(cam_file)
        await message.answer_photo(photo, caption="📸 Kamera surati")
        os.remove(cam_file)
        await msg.delete()
    except Exception as e:
        await message.answer(f"❌ Kamera xatoligi: {e}")


@dp.message(Command("lock"))
@dp.message(F.text == "🔒 Qulflash")
async def cmd_lock(message: types.Message):
    env = get_wayland_env()
    try:
        subprocess.run([
            "gdbus", "call", "--session",
            "--dest", "org.gnome.ScreenSaver",
            "--object-path", "/org/gnome/ScreenSaver",
            "--method", "org.gnome.ScreenSaver.Lock"
        ], env=env, timeout=3, check=True)
        await message.answer("🔒 Ekran qulflandi!")
    except Exception:
        subprocess.run(["loginctl", "lock-session"])
        await message.answer("🔒 Ekran qulflandi!")


@dp.message(F.text == "🔔 Xabar yuborish")
async def notify_button(message: types.Message, state: FSMContext):
    await state.set_state(NotifyState.waiting_text)
    await message.answer("✍️ Ekranga chiqariladigan xabarni yozing:")


@dp.message(NotifyState.waiting_text)
async def notify_receive_text(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    env = get_wayland_env()
    try:
        subprocess.run(["notify-send", "-u", "critical", "📩 Telegram Bildirishnomasi", text], env=env, timeout=4, check=True)
        await message.answer("🔔 Xabar noutbuk ekranida ko'rsatildi!", reply_markup=main_menu)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=main_menu)


@dp.message(F.text == "🔊 Ovoz")
async def volume_button(message: types.Message):
    volume = get_current_volume_percent()
    text = f"🔊 Joriy ovoz: <b>{volume}</b>"
    if is_muted():
        text += " (O'chirilgan 🔇)"
    await message.answer(text, parse_mode="HTML", reply_markup=volume_kb)


@dp.callback_query(F.data.in_({"vol_up", "vol_down", "vol_mute"}))
async def volume_callback(callback: CallbackQuery):
    action_map = {"vol_up": "up", "vol_down": "down", "vol_mute": "mute"}
    arg = action_map[callback.data]
    try:
        result_text = run_volume_action(arg)
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=volume_kb)
    except Exception as e:
        await callback.message.edit_text(f"❌ Xatolik: {e}", reply_markup=volume_kb)
    await callback.answer()


@dp.message(F.text == "📋 Clipboard")
async def clipboard_button(message: types.Message):
    await message.answer("📋 Clipboard amalini tanlang:", reply_markup=clipboard_kb)


@dp.callback_query(F.data == "clip_get")
async def clipboard_get_callback(callback: CallbackQuery):
    await callback.answer()
    text = get_clipboard_text()
    if text:
        await callback.message.answer(f"📥 <b>Nusxalangan matn:</b>\n\n<code>{text}</code>", parse_mode="HTML")
    else:
        await callback.message.answer("📋 Clipboard bo'sh yoki matn topilmadi.")


@dp.callback_query(F.data == "clip_set")
async def clipboard_set_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ClipboardState.waiting_text)
    await callback.message.answer("✍️ Clipboard'ga saqlanadigan matnni yuboring:")


@dp.message(ClipboardState.waiting_text)
async def clipboard_receive_text(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    try:
        set_clipboard_text(text)
        await message.answer("✅ Matn noutbuk clipboard'iga saqlandi!", reply_markup=main_menu)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=main_menu)


@dp.message(Command("reboot"))
@dp.message(F.text == "🔄 Qayta yoqish")
async def cmd_reboot(message: types.Message):
    await message.answer("⚠️ Noutbukni qayta ishga tushirmoqchimisiz?", reply_markup=confirm_kb("reboot"))


@dp.message(Command("shutdown"))
@dp.message(F.text == "🛑 O'chirish")
async def cmd_shutdown(message: types.Message):
    await message.answer("⚠️ Noutbukni o'chirmoqchimisiz?", reply_markup=confirm_kb("shutdown"))


@dp.callback_query(F.data == "confirm_reboot")
async def confirm_reboot(callback: CallbackQuery):
    await callback.message.edit_text("🔄 Noutbuk qayta ishga tushirilmoqda...")
    await callback.answer()
    await asyncio.sleep(1)
    subprocess.Popen(["systemctl", "reboot"])


@dp.callback_query(F.data == "confirm_shutdown")
async def confirm_shutdown(callback: CallbackQuery):
    await callback.message.edit_text("🛑 Noutbuk o'chirilmoqda...")
    await callback.answer()
    await asyncio.sleep(1)
    subprocess.Popen(["systemctl", "poweroff"])


@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery):
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


# ---------- FONDA DASTURLARNI KUZATISH ----------
async def app_tracker_loop():
    while True:
        try:
            today_str = datetime.now(UZ_TZ).strftime("%Y-%m-%d")
            if daily_stats.get("date") != today_str:
                reset_daily_stats()

            battery = psutil.sensors_battery()
            if battery:
                daily_stats["battery_samples"].append({
                    "percent": round(battery.percent),
                    "plugged": battery.power_plugged,
                })

            current_app = get_active_window_name()
            if current_app and current_app not in ("Bosh ekran", ""):
                daily_stats["app_minutes"][current_app] += 1
        except Exception:
            pass

        await asyncio.sleep(TRACK_INTERVAL_SECONDS)


async def daily_report_scheduler():
    sent_today = False
    while True:
        now = datetime.now(UZ_TZ)
        if now.hour == 23 and now.minute >= 55 and not sent_today:
            try:
                report_text = build_daily_report_text()
                await bot.send_message(chat_id=ADMIN_ID, text=report_text, parse_mode="HTML")
                sent_today = True
                reset_daily_stats()
            except Exception:
                pass
        elif now.hour == 0:
            sent_today = False
        await asyncio.sleep(30)


# ---------- STARTUP XABARI ----------
async def on_startup_notify():
    boot_time = datetime.now(UZ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    battery = psutil.sensors_battery()
    bat_text = f"{round(battery.percent)}%" if battery else "Aniqlanmadi"
    wifi_name = get_wifi_name()

    text = (
        "🟢 <b>Notebookingiz yondi!</b>\n\n"
        "💻 <b>Qurilma:</b> Surface Laptop\n"
        f"🔋 <b>Batareya:</b> {bat_text}\n"
        f"📶 <b>Wi-Fi:</b> <code>{wifi_name}</code>\n"
        f"🕒 <b>Vaqt:</b> {boot_time}"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML", reply_markup=main_menu)
    except Exception:
        pass


async def main():
    reset_daily_stats()
    await on_startup_notify()
    asyncio.create_task(app_tracker_loop())
    asyncio.create_task(daily_report_scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())