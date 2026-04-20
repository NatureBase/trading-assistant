# trading-assistant

Aplikasi trading berbasis lokal dengan arsitektur **backend + frontend**.  
Aplikasi ini memungkinkan pengguna untuk memantau data market secara live, melakukan analisis, dan menjalankan sistem trading berbasis data.

> ⚠️ Aplikasi ini dijalankan melalui terminal (bukan installer `.exe` / `.dmg`)

---

## 🚀 Fitur Utama

- 📊 Live market data (WebSocket + REST API)
- 📈 Chart interaktif
- 🔄 Auto reconnect WebSocket
- 📁 Support data lokal (historical data)
- 🌐 Integrasi Binance API
- ⚙️ Configurable data source (REST / local / hybrid)
- 💾 Session & caching data

---

## 🧱 Arsitektur

Project terdiri dari dua bagian utama:

frontend/  → UI (React + Vite)  
backend/   → API & data engine (Python)

Aplikasi dijalankan dengan **2 terminal terpisah**:
- Terminal 1 → backend
- Terminal 2 → frontend

---

## 📦 Requirements

Install Python 3.13.5 dari link berikut https://www.python.org/downloads/ <br>
Pilih OS nya (antara Windows/macOS/Linux) dan cari python versi 3.13.5 untuk didownload.
Setelah download, install python dengan mengklik installernya dan klik next. Jangan lupa untuk mencentang "Add python to PATH"<br>
<img width="1200" height="675" alt="image" src="https://github.com/user-attachments/assets/6de94283-fbd9-45d9-b3f5-d3b1d1dd5c9c" />

<br>
Setelah itu buka Command Prompt dan jalankan perintah ini (ketik dan klik Enter)
```bash
python --version
```
<img width="1800" height="740" alt="image" src="https://github.com/user-attachments/assets/f1fcbd2d-72ea-4030-b20e-c51cada70d16" />
<br>
Jika muncul hasil seperti di bawah ini, maka Python terlah berhasil diinstall.
```bash
Python 3.13.5
```

---

## 📥 Installation

Download repo ini dengan cara seperti yang ada di gambar. Extract folder dan tempatkan di directory yang kamu inginkan. <br>
<img width="1181" height="608" alt="Screenshot 2026-04-20 at 09 39 46" src="https://github.com/user-attachments/assets/407684a1-1375-4f11-bb20-2faef3dda3b5" />

---

## ⚙️ Setup Backend

Buka satu tab Command Prompt, lalu jalankan perinta berikut untuk berpindah ke alamat folder aplikasinya. Misal, folder aplikasi berada di Downloads:

```bash
cd Downloads/trading-assistant/backend
```

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Run Backend

```bash
python main.py
```
atau
```bash
uvicorn app.main:app --reload  
```
---

## 🎨 Setup Frontend

 Buka tab Command Prompt yang berbeda, lalu jalankan perintah berikut:

```bash
cd frontend
npm install
npm run dev
```

Akses:
http://localhost:5173

---

## ▶️ Menjalankan Aplikasi

Jalankan 2 terminal:

**Terminal 1 (Backend):**
```bash
cd backend
source .venv/bin/activate
python main.py
```

**Terminal 2 (Frontend):**
```bash
cd frontend
npm run dev
```

---
