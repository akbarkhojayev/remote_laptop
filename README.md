# 🤖 Noutbuk Masofaviy Boshqaruv Boti

Bu bot Telegram orqali **istalgan Ubuntu noutbuk yoki kompyuterni** masofadan boshqarish uchun yozilgan. Brend muhim emas — Lenovo, Dell, HP, Asus yoki boshqa har qanday kompyuterda ishlaydi, faqat Ubuntu (GNOME, Wayland) o'rnatilgan bo'lishi kerak.

Botga faqat siz (belgilangan admin) buyruq bera olasiz. Boshqa hech kim, hatto bot havolasini bilsa ham, hech narsa qila olmaydi.

---

## 📋 Ichida nima bor

1. [Bot nima qila oladi](#1-bot-nima-qila-oladi)
2. [Kerakli dasturlar](#2-kerakli-dasturlar)
3. [O'rnatish — qadam baqadam](#3-ornatish--qadam-baqadam)
4. [Botni doim ishlab turadigan qilish](#4-botni-doim-ishlab-turadigan-qilish)
5. [Barcha buyruqlar](#5-barcha-buyruqlar)
6. [Xavfsizlik](#6-xavfsizlik)
7. [Muammo chiqsa nima qilish kerak](#7-muammo-chiqsa-nima-qilish-kerak)

---

## 1. Bot nima qila oladi

| Tugma | Nima qiladi |
|---|---|
| 📊 Status | CPU, RAM, batareya, ovoz, disk holatini va IP manzilni ko'rsatadi |
| 📸 Rasm | Veb-kameradan rasmga oladi |
| 🔒 Qulflash | Ekranni qulflaydi |
| 🔊 Ovoz | Ovozni oshiradi / pasaytiradi / o'chiradi |
| 🔔 Bildirishnoma | Siz yozgan matnni noutbuk ekraniga chiqaradi |
| 📋 Clipboard | Noutbukdagi nusxa olingan matnni oladi yoki yangi matn joylaydi |
| 📅 Kunlik hisobot | Kun davomida batareya va eng ko'p ishlatilgan dasturlar haqida hisobot beradi |
| 🔄 Qayta ishga tushirish | Noutbukni restart qiladi (tasdiqlash so'raydi) |
| 🛑 O'chirish | Noutbukni o'chiradi (tasdiqlash so'raydi) |

> ℹ️ **Skrinshot funksiyasi yo'q.** GNOME (Wayland) tashqi dasturlarga skrinshot olishga ataylab ruxsat bermaydi — bu xato emas, GNOME'ning o'z xavfsizlik siyosati.

---

## 2. Kerakli dasturlar

Terminalni oching va shu buyruqni yozing:

```bash
sudo apt update
sudo apt install fswebcam libnotify-bin pulseaudio-utils wl-clipboard python3-pip
```

Bu nima uchun kerak:

- `fswebcam` → rasmga olish uchun
- `libnotify-bin` → ekranga bildirishnoma chiqarish uchun
- `pulseaudio-utils` → ovozni boshqarish uchun
- `wl-clipboard` → clipboard bilan ishlash uchun

Keyin Python kutubxonalarini o'rnating:

```bash
pip install aiogram psutil
```

---

## 3. O'rnatish — qadam baqadam

### 3.1. Telegram bot yarating

1. Telegram'da [@BotFather](https://t.me/BotFather) ni oching
2. `/newbot` deb yozing va ko'rsatmalarga amal qiling
3. Sizga bir token beradi, masalan: `123456789:ABCdefGhIJklmNoPQRstuVWxyz` — shuni saqlab qo'ying

### 3.2. O'z Telegram ID'ingizni bilib oling

1. Telegram'da [@userinfobot](https://t.me/userinfobot) ni oching
2. `/start` deb yozing — u sizga raqamli ID beradi (masalan `123456789`)

### 3.3. Bot faylini joylashtiring

```bash
mkdir -p ~/remote_bot
```

`bot.py` faylini shu `~/remote_bot` papkaga joylashtiring.

### 3.4. Tokeningizni va ID'ingizni kodga yozing

```bash
nano ~/remote_bot/bot.py
```

Faylning yuqorisida shu ikki qatorni topib, o'zgartiring:

```python
BOT_TOKEN = "SIZNING_BOT_TOKENINGIZ"
ADMIN_ID = 123456789
```

- `BOT_TOKEN` o'rniga @BotFather bergan tokenni yozing
- `ADMIN_ID` o'rniga @userinfobot bergan raqamni yozing

Saqlang: `Ctrl+O` bosing, `Enter` bosing, `Ctrl+X` bosing.

### 3.5. Botni sinab ko'ring

```bash
python3 ~/remote_bot/bot.py
```

Telegram'da botingizni toping va `/start` deb yozing. Agar tugmalar chiqsa — hammasi to'g'ri ishlayapti. Terminaldan chiqish uchun `Ctrl+C` bosing.

---

## 4. Botni doim ishlab turadigan qilish

Hozircha bot faqat siz terminalni ochib turgan paytda ishlaydi. Buni tuzatib, noutbuk yonganda bot ham avtomatik yonadigan qilamiz.

### 4.1. Xizmat fayli yarating

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/remote-bot.service
```

Shuni joylashtiring (`SIZNING_FOYDALANUVCHI_NOMINGIZ` o'rniga o'z foydalanuvchi nomingizni yozing — buni `whoami` buyrug'i bilan bilib olishingiz mumkin):

```ini
[Unit]
Description=Telegram Remote Control Bot
After=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 /home/SIZNING_FOYDALANUVCHI_NOMINGIZ/remote_bot/bot.py
WorkingDirectory=/home/SIZNING_FOYDALANUVCHI_NOMINGIZ/remote_bot
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Saqlang: `Ctrl+O` → `Enter` → `Ctrl+X`

### 4.2. Xizmatni yoqing

```bash
systemctl --user daemon-reload
systemctl --user enable remote-bot.service
systemctl --user start remote-bot.service
sudo loginctl enable-linger $USER
```

So'nggi buyruq — noutbuk qayta yoqilganda ham, siz login qilmasangiz ham, bot avtomatik ishga tushishini ta'minlaydi.

### 4.3. Foydali buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `systemctl --user status remote-bot.service` | Bot ishlab turganini tekshirish |
| `systemctl --user restart remote-bot.service` | Kodni o'zgartirgandan keyin qayta ishga tushirish |
| `journalctl --user -u remote-bot.service -f` | Botning jonli loglarini ko'rish |
| `systemctl --user stop remote-bot.service` | Botni to'xtatish |

---

## 5. Barcha buyruqlar

Botga `/start` yuboring — pastda tugmalar chiqadi. Xohlasangiz, shu buyruqlarni matn sifatida ham yozishingiz mumkin:

```
/status
/photo
/lock
/volume up
/volume down
/volume mute
/notify Salom, bu test xabari
/reboot
/shutdown
```

---

## 6. Xavfsizlik

- ❗️ **BOT_TOKEN ni hech kimga bermang.** Kim tokenni bilsa, botni boshqara oladi.
- Agar loyihani GitHub'ga yuklasangiz, tokenni kodda qoldirmang — avval `SIZNING_BOT_TOKENINGIZ` degan bo'sh joyga qaytarib, keyin yuklang.
- Reboot va shutdown tugmalari tasdiqlash so'raydi — tasodifan bosib yubormaysiz.
- Bot faqat sizning `ADMIN_ID`ingizga javob beradi, boshqa hech kimga emas.

---

## 7. Muammo chiqsa nima qilish kerak

**Bot Telegram'da javob bermayapti**
```bash
systemctl --user status remote-bot.service
journalctl --user -u remote-bot.service -f
```
Bu yerda xato xabarini ko'rasiz.

**Rasm olinmayapti**
```bash
which fswebcam
```
Agar hech narsa chiqmasa, dastur o'rnatilmagan — 2-bo'limga qarang.

**Bildirishnoma chiqmayapti**
```bash
notify-send "Test" "Salom"
```
Agar bu terminaldan ishlamasa, muammo botda emas, tizimda.

**Ovoz o'zgarmayapti**
```bash
pactl get-default-sink
```
Bu buyruq audio qurilma nomini ko'rsatishi kerak.

**Clipboard ishlamayapti**
```bash
echo $XDG_SESSION_TYPE
```
Natija `wayland` bo'lishi kerak. Agar `x11` chiqsa, `wl-copy`/`wl-paste` o'rniga boshqa vosita (`xclip`) kerak bo'ladi.

---

Savolingiz bo'lsa yoki yangi funksiya qo'shmoqchi bo'lsangiz, kodni ochib, mos joyga qo'shishingiz mumkin — bot tuzilishi sodda va tushunarli qilib yozilgan.
