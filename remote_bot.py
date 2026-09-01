import os
import re
import asyncio
import subprocess
from datetime import datetime, timedelta
from collections import Counter
import psutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
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
ADMIN_ID = 123456789  # O'zingizning Telegram raqamli ID'ingiz

# Har necha daqiqada foydalanish statistikasi yig'ilishi (kunlik hisobot uchun)
TRACK_INTERVAL_MINUTES = 3

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ---------- HOLATLAR (FSM) ----------
class NotifyState(StatesGroup):
    waiting_text = State()


class ClipboardState(StatesGroup):
    waiting_text = State()


# ---------- KUNLIK STATISTIKA ----------
daily_stats = {}

EXCLUDED_PROC_NAMES = {
    "gnome-shell", "gnome-session-binary", "gnome-terminal-server",
    "gsd-power", "gsd-media-keys", "gsd-color", "gsd-datetime", "gsd-housekeeping",
    "gsd-keyboard", "gsd-print-notifications", "gsd-rfkill", "gsd-screensaver-proxy",
    "gsd-sharing", "gsd-smartcard", "gsd-sound", "gsd-wacom", "gsd-xsettings",
    "gsd-a11y-settings", "gsd-disk-utility-notify", "gsd-usb-protection", "gsd-wwan",
    "pulseaudio", "pipewire", "pipewire-pulse", "wireplumber",
    "dbus-daemon", "dbus-broker", "ibus-daemon", "ibus-x11", "ibus-extension-gtk3",
    "ibus-engine-simple", "at-spi-bus-launcher", "at-spi2-registryd",
    "xdg-permission-store", "xdg-desktop-portal", "xdg-desktop-portal-gnome",
    "xdg-desktop-portal-gtk", "xdg-document-portal",
    "evolution-source-registry", "evolution-calendar-factory", "evolution-addressbook-factory",
    "goa-daemon", "goa-identity-service", "gvfsd", "gvfsd-fuse", "gvfsd-trash",
    "gvfsd-metadata", "gvfs-udisks2-volume-monitor",
    "tracker-miner-fs-3", "tracker-extract-3", "tracker-store",
    "geoclue", "fwupd", "upowerd", "polkitd", "udisksd", "accounts-daemon",
    "packagekitd", "snapd", "systemd", "systemd-logind", "systemd-resolved",
    "systemd-timesyncd", "systemd-udevd", "cron", "rsyslogd", "avahi-daemon",
    "cupsd", "bluetoothd", "ModemManager", "NetworkManager", "wpa_supplicant",
    "chronyd", "irqbalance", "thermald", "networkd-dispatcher",
    "gjs", "Xwayland", "gdm-session-worker", "gdm3",
    "ssh-agent", "gpg-agent", "gcr-ssh-agent",
    "bash", "sh", "zsh", "python3", "python",
}


def reset_daily_stats():
    daily_stats["date"] = datetime.now().strftime("%Y-%m-%d")
    daily_stats["app_counter"] = Counter()
    daily_stats["battery_samples"] = []


# ---------- KLAVIATURALAR ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Status"), KeyboardButton(text="📸 Rasm")],
        [KeyboardButton(text="🔒 Qulflash"), KeyboardButton(text="🔊 Ovoz")],
        [KeyboardButton(text="📋 Clipboard"), KeyboardButton(text="📅 Kunlik hisobot")],
        [KeyboardButton(text="🔔 Bildirishnoma")],
        [KeyboardButton(text="🔄 Qayta ishga tushirish"), KeyboardButton(text="🛑 O'chirish")],
    ],
    resize_keyboard=True,
)

volume_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🔊 Oshirish", callback_data="vol_up"),
            InlineKeyboardButton(text="🔉 Pasaytirish", callback_data="vol_down"),
        ],
        [InlineKeyboardButton(text="🔇 Mute", callback_data="vol_mute")],
    ]
)

clipboard_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Oxirgi nusxani olish", callback_data="clip_get"),
            InlineKeyboardButton(text="📤 Yangi matn yuborish", callback_data="clip_set"),
        ]
    ]
)


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, davom et", callback_data=f"confirm_{action}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"),
            ]
        ]
    )


# ---------- YORDAMCHI FUNKSIYALAR ----------
def get_gui_env():
    uid = os.getuid()
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env["DBUS_SESSION_BUS_ADDRESS"] = env.get(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus"
    )
    env["DISPLAY"] = env.get("DISPLAY", ":0")
    env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
    return env


def get_current_volume_percent() -> str:
    env = get_gui_env()
    try:
        output = subprocess.check_output(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], env=env, timeout=4
        ).decode()
        match = re.search(r"(\d+)%", output)
        return f"{match.group(1)}%" if match else "N/A"
    except Exception:
        return "N/A"


def is_muted() -> bool:
    env = get_gui_env()
    try:
        output = subprocess.check_output(
            ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], env=env, timeout=4
        ).decode()
        return "yes" in output.lower()
    except Exception:
        return False


def get_disk_text() -> str:
    disk = psutil.disk_usage("/")
    free_gb = disk.free / (1024 ** 3)
    return f"💽 Disk: <b>{round(disk.percent)}%</b> band ({free_gb:.1f}GB bo'sh)"


def build_status_text() -> str:
    cpu = round(psutil.cpu_percent(interval=1))
    ram = round(psutil.virtual_memory().percent)

    battery = psutil.sensors_battery()
    if battery:
        bat_percent = round(battery.percent)
        bat_state = "Zaryadlanmoqda ⚡️" if battery.power_plugged else "Batareyada 🔋"
        bat_text = f"{bat_percent}% — {bat_state}"
    else:
        bat_text = "Mavjud emas"

    try:
        ip = subprocess.check_output(["curl", "-s", "--max-time", "4", "https://ifconfig.me"]).decode().strip()
    except Exception:
        ip = "Aniqlanmadi"

    volume = get_current_volume_percent()
    volume_line = f"🔊 Ovoz: <b>{volume}</b>"
    if is_muted():
        volume_line += " (o'chirilgan 🔇)"

    return (
        f"📊 <b>Tizim holati</b>\n\n"
        f"🧠 CPU: <b>{cpu}%</b>\n"
        f"💾 RAM: <b>{ram}%</b>\n"
        f"🔋 Batareya: <b>{bat_text}</b>\n"
        f"{volume_line}\n"
        f"{get_disk_text()}\n"
        f"🌐 IP: <code>{ip}</code>"
    )


def run_volume_action(arg: str) -> str:
    env = get_gui_env()

    if arg == "up":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], env=env, timeout=4, check=True)
        icon = "🔊"
    elif arg == "down":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], env=env, timeout=4, check=True)
        icon = "🔉"
    else:  # mute
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], env=env, timeout=4, check=True)
        icon = "🔇"

    volume = get_current_volume_percent()
    text = f"{icon} Ovoz: <b>{volume}</b>"
    if is_muted():
        text += " (o'chirilgan 🔇)"
    return text


def get_clipboard_text():
    env = get_gui_env()
    try:
        output = subprocess.check_output(["wl-paste", "--no-newline"], env=env, timeout=4).decode()
        return output if output else None
    except Exception:
        return None


def set_clipboard_text(text: str):
    env = get_gui_env()
    subprocess.run(["wl-copy", text], env=env, timeout=4, check=True)


def get_active_app_names():
    """Foydalanuvchi grafik dasturlarining nomlarini taxminan aniqlaydi
    (terminalsiz, joriy foydalanuvchi nomidan ishlayotgan jarayonlar)."""
    apps = set()
    current_uid = os.getuid()
    for p in psutil.process_iter(["name", "uids", "terminal"]):
        try:
            info = p.info
            uids = info.get("uids")
            if uids and uids.real != current_uid:
                continue
            if info.get("terminal") is not None:
                continue
            name = info.get("name")
            if not name or name in EXCLUDED_PROC_NAMES:
                continue
            apps.add(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return apps


def build_daily_report_text() -> str:
    stats = daily_stats
    date_str = stats.get("date", datetime.now().strftime("%Y-%m-%d"))
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

    tracked_minutes = len(battery_samples) * TRACK_INTERVAL_MINUTES
    hours = tracked_minutes // 60
    minutes = tracked_minutes % 60

    top_apps = stats.get("app_counter", Counter()).most_common(5)
    if top_apps:
        apps_lines = "\n".join(
            f"{i + 1}. {name} — ~{count * TRACK_INTERVAL_MINUTES} daqiqa"
            for i, (name, count) in enumerate(top_apps)
        )
    else:
        apps_lines = "Ma'lumot hali yig'ilmagan"

    return (
        f"📅 <b>Kunlik hisobot</b> — {date_str}\n\n"
        f"🔋 Batareya: {start_percent}% → {current_percent}% "
        f"(eng past: {min_percent}%, eng baland: {max_percent}%)\n"
        f"⏱ Kuzatilgan vaqt: {hours} soat {minutes} daqiqa\n\n"
        f"🧠 <b>Eng ko'p ishlatilgan ilovalar:</b>\n{apps_lines}\n\n"
        f"{get_disk_text()}"
    )


# ---------- XAVFSIZLIK ----------
@dp.message(F.from_user.id != ADMIN_ID)
async def unauthorized(message: types.Message):
    await message.reply("⛔️ Ruxsat berilmagan!")


@dp.callback_query(F.from_user.id != ADMIN_ID)
async def unauthorized_callback(callback: CallbackQuery):
    await callback.answer("⛔️ Ruxsat berilmagan!", show_alert=True)


# ---------- START / HELP ----------
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    text = (
        "🤖 <b>Surface Masofaviy Boshqaruv Markazi</b>\n\n"
        "Quyidagi tugmalardan foydalaning 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu)


# ---------- STATUS ----------
@dp.message(Command("status"))
@dp.message(F.text == "📊 Status")
async def cmd_status(message: types.Message):
    await message.answer(build_status_text(), parse_mode="HTML")


# ---------- PHOTO ----------
@dp.message(Command("photo"))
@dp.message(F.text == "📸 Rasm")
async def cmd_photo(message: types.Message):
    msg = await message.answer("📸 Surat olinmoqda...")
    cam_file = "/tmp/cam_shot.jpg"

    if os.path.exists(cam_file):
        os.remove(cam_file)

    try:
        subprocess.run(
            ["fswebcam", "-r", "1280x720", "--no-banner", cam_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=7,
            check=True,
        )
        photo = FSInputFile(cam_file)
        await message.answer_photo(photo, caption="📸 Veb-kamera surati")
        os.remove(cam_file)
        await msg.delete()
    except Exception as e:
        await message.answer(f"❌ Kamera xatoligi: {e}")


# ---------- LOCK ----------
@dp.message(Command("lock"))
@dp.message(F.text == "🔒 Qulflash")
async def cmd_lock(message: types.Message):
    env = get_gui_env()

    try:
        subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.ScreenSaver",
                "--object-path", "/org/gnome/ScreenSaver",
                "--method", "org.gnome.ScreenSaver.Lock",
            ],
            env=env,
            timeout=3,
            check=True,
        )
        await message.answer("🔒 Ekran qulflandi!")
    except Exception:
        subprocess.run(["loginctl", "lock-session"])
        await message.answer("🔒 Ekran qulflandi!")


# ---------- NOTIFY (tugma orqali, matn so'raladi) ----------
@dp.message(F.text == "🔔 Bildirishnoma")
async def notify_button(message: types.Message, state: FSMContext):
    await state.set_state(NotifyState.waiting_text)
    await message.answer("✍️ Bildirishnoma matnini yozib yuboring:")


@dp.message(NotifyState.waiting_text)
async def notify_receive_text(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()

    env = get_gui_env()
    try:
        subprocess.run(["notify-send", "📩 Telegram xabari", text], env=env, timeout=4, check=True)
        await message.answer("🔔 Bildirishnoma noutbukda ko'rsatildi!", reply_markup=main_menu)
    except Exception as e:
        await message.answer(f"❌ Bildirishnoma xatoligi: {e}", reply_markup=main_menu)


# ---------- NOTIFY (buyruq orqali: /notify matn) ----------
@dp.message(Command("notify"))
async def cmd_notify(message: types.Message, command: CommandObject):
    text = command.args
    if not text:
        await message.answer("⚠️ Foydalanish: <code>/notify Salom, bu test xabari</code>", parse_mode="HTML")
        return

    env = get_gui_env()
    try:
        subprocess.run(["notify-send", "📩 Telegram xabari", text], env=env, timeout=4, check=True)
        await message.answer("🔔 Bildirishnoma noutbukda ko'rsatildi!")
    except Exception as e:
        await message.answer(f"❌ Bildirishnoma xatoligi: {e}")


# ---------- VOLUME (tugma orqali menyu ko'rsatish) ----------
@dp.message(F.text == "🔊 Ovoz")
async def volume_button(message: types.Message):
    volume = get_current_volume_percent()
    text = f"🔊 Joriy ovoz: <b>{volume}</b>"
    if is_muted():
        text += " (o'chirilgan 🔇)"
    await message.answer(text, parse_mode="HTML", reply_markup=volume_kb)


# ---------- VOLUME (/volume up|down|mute) ----------
@dp.message(Command("volume"))
async def cmd_volume(message: types.Message, command: CommandObject):
    arg = (command.args or "").strip().lower()

    if arg not in ("up", "down", "mute"):
        await message.answer(
            "⚠️ Foydalanish:\n"
            "<code>/volume up</code> — ovozni oshirish\n"
            "<code>/volume down</code> — ovozni pasaytirish\n"
            "<code>/volume mute</code> — ovozni o'chirish/yoqish",
            parse_mode="HTML",
        )
        return

    try:
        result_text = run_volume_action(arg)
        await message.answer(result_text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ovoz sozlash xatoligi: {e}")


# ---------- VOLUME (inline tugmalar bosilganda) ----------
@dp.callback_query(F.data.in_({"vol_up", "vol_down", "vol_mute"}))
async def volume_callback(callback: CallbackQuery):
    action_map = {"vol_up": "up", "vol_down": "down", "vol_mute": "mute"}
    arg = action_map[callback.data]

    try:
        result_text = run_volume_action(arg)
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=volume_kb)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ovoz sozlash xatoligi: {e}", reply_markup=volume_kb)

    await callback.answer()


# ---------- CLIPBOARD (tugma orqali menyu ko'rsatish) ----------
@dp.message(F.text == "📋 Clipboard")
async def clipboard_button(message: types.Message):
    await message.answer("📋 Nima qilmoqchisiz?", reply_markup=clipboard_kb)


@dp.callback_query(F.data == "clip_get")
async def clipboard_get_callback(callback: CallbackQuery):
    await callback.answer()
    text = get_clipboard_text()
    if text:
        await callback.message.answer(f"📥 <b>Clipboard tarkibi:</b>\n\n{text}", parse_mode="HTML")
    else:
        await callback.message.answer("📋 Clipboard bo'sh yoki o'qib bo'lmadi.")


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


# ---------- KUNLIK HISOBOT (tugma orqali) ----------
@dp.message(F.text == "📅 Kunlik hisobot")
async def daily_report_button(message: types.Message):
    await message.answer(build_daily_report_text(), parse_mode="HTML")


# ---------- REBOOT (tasdiqlash bilan) ----------
@dp.message(Command("reboot"))
@dp.message(F.text == "🔄 Qayta ishga tushirish")
async def cmd_reboot(message: types.Message):
    await message.answer(
        "⚠️ Noutbukni qayta ishga tushirmoqchimisiz?",
        reply_markup=confirm_kb("reboot"),
    )


# ---------- SHUTDOWN (tasdiqlash bilan) ----------
@dp.message(Command("shutdown"))
@dp.message(F.text == "🛑 O'chirish")
async def cmd_shutdown(message: types.Message):
    await message.answer(
        "⚠️ Noutbukni o'chirmoqchimisiz?",
        reply_markup=confirm_kb("shutdown"),
    )


# ---------- TASDIQLASH TUGMALARI ----------
@dp.callback_query(F.data == "confirm_reboot")
async def confirm_reboot(callback: CallbackQuery):
    await callback.message.edit_text("🔄 Noutbuk qayta ishga tushirilmoqda...")
    await callback.answer()
    subprocess.run(["systemctl", "reboot"])


@dp.callback_query(F.data == "confirm_shutdown")
async def confirm_shutdown(callback: CallbackQuery):
    await callback.message.edit_text("🛑 Noutbuk o'chirilmoqda...")
    await callback.answer()
    subprocess.run(["systemctl", "poweroff"])


@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery):
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


# ---------- FONDA ISHLAYDIGAN VAZIFALAR ----------
async def usage_tracker_loop():
    """Har TRACK_INTERVAL_MINUTES daqiqada batareya va ochiq ilovalarni kuzatadi."""
    while True:
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            if daily_stats.get("date") != today_str:
                reset_daily_stats()

            battery = psutil.sensors_battery()
            if battery:
                daily_stats["battery_samples"].append({
                    "percent": round(battery.percent),
                    "plugged": battery.power_plugged,
                })

            apps = get_active_app_names()
            daily_stats["app_counter"].update(apps)
        except Exception:
            pass

        await asyncio.sleep(TRACK_INTERVAL_MINUTES * 60)


async def daily_report_scheduler():
    """Har kuni soat 23:55 da kunlik hisobotni avtomatik yuboradi."""
    while True:
        now = datetime.now()
        target = now.replace(hour=23, minute=55, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            report_text = build_daily_report_text()
            await bot.send_message(chat_id=ADMIN_ID, text=report_text, parse_mode="HTML")
        except Exception:
            pass

        reset_daily_stats()


# ---------- STARTUP XABARI ----------
async def on_startup_notify():
    boot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    battery = psutil.sensors_battery()
    bat_text = f"{round(battery.percent)}%" if battery else "Aniqlanmadi"

    text = (
        "🟢 <b>Notebookingiz yondi!</b>\n\n"
        "💻 <b>Tizim:</b> Surface (Ubuntu)\n"
        f"🔋 <b>Batareya:</b> {bat_text}\n"
        f"🕒 <b>Vaqt:</b> {boot_time}"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML", reply_markup=main_menu)
    except Exception:
        pass


async def main():
    reset_daily_stats()
    await on_startup_notify()
    asyncio.create_task(usage_tracker_loop())
    asyncio.create_task(daily_report_scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
