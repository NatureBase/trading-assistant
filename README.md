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

Install Python 3.13.5 dari link berikut https://www.python.org/downloads/
Pilih OS nya (antara Windows/macOS/Linux) dan cari python versi 3.13.5 untuk didownload.
Setelah download, install python dengan mengklik installernya dan klik next. Jangan lupa untuk mencentang "Add python to PATH"
<img width="1200" height="675" alt="image" src="https://github.com/user-attachments/assets/6de94283-fbd9-45d9-b3f5-d3b1d1dd5c9c" />


---

## 📥 Installation

```bash
git clone https://github.com/NatureBase/trading-assistant.git
cd trading-assistant
```

---

## ⚙️ Setup Backend

```bash
cd backend
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

---

## 🎨 Setup Frontend

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

## ⚙️ Konfigurasi

```bash
cp .env.example .env
```

Contoh:
```
API_HOST=127.0.0.1
API_PORT=8000
DATA_SOURCE=binance
BINANCE_MODE=rest
```

---

## 📁 Struktur Project

```
trading-assistant/
├─ backend/
├─ frontend/
├─ README.md
```

---

## 🛠️ Troubleshooting

- python tidak dikenali → install Python
- node tidak dikenali → install Node.js
- port sudah digunakan → ubah config
- frontend tidak connect → cek backend running

---

## 🔐 Security

- Jangan commit API key
- Gunakan .env

---

## ⚠️ Disclaimer

Untuk pembelajaran & eksperimen. Risiko trading ditanggung pengguna.

---

## 📄 License

MIT License
