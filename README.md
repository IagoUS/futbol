# ⚽ Biwenger Agent

Aplicación web de Fantasy Football inteligente para **Biwenger** (puntuación Sofascore).  
Gestiona el **Mundial 2026** (junio 2026) y **LaLiga** desde el mismo dashboard.

---

## 🚀 Instalación y arranque (paso a paso)

### Requisitos previos
- **Python 3.11+** instalado
- **Node.js 18+** instalado

---

### 1. Backend (FastAPI)

Abre una terminal en la carpeta `backend/`:

```bash
cd backend

# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Arrancar el servidor
python main.py
```

El backend quedará disponible en **http://localhost:8000**

---

### 2. Frontend (React)

Abre **otra** terminal en la carpeta `frontend/`:

```bash
cd frontend

# Instalar dependencias
npm install

# Arrancar la aplicación
npm start
```

El frontend se abrirá automáticamente en **http://localhost:3000**

---

## 🔄 Uso básico

1. Abre **http://localhost:3000** en el navegador
2. Ve a la pestaña **🧠 Cerebro IA**
3. Pulsa el botón verde **🔄 SINCRONIZAR TODO**
4. Espera a que terminen los 10 scrapers (~30 segundos)
5. Pulsa **🧠 GENERAR CONSEJOS CON IA** para obtener los 5 análisis de Gemini

---

## ⚠️ Si el token caduca

Si la app muestra "Token caducado":

1. Abre [biwenger.as.com](https://biwenger.as.com) en el navegador
2. Pulsa F12 → pestaña **Network**
3. Filtra por `api/v2`
4. Recarga la página de Biwenger
5. Haz clic en cualquier petición → copia el valor del header `Authorization`
6. Actualiza `BIWENGER_TOKEN` en el fichero `backend/.env`
7. Reinicia el backend

---

## 📁 Estructura del proyecto

```
biwenger-agent/
├── backend/
│   ├── main.py          ← Servidor FastAPI (endpoints)
│   ├── scraper.py       ← 10 scrapers de la API de Biwenger
│   ├── analyzer.py      ← Motor de análisis (scores, ROI, riesgo)
│   ├── ai_advisor.py    ← 5 consultas a Gemini AI
│   ├── database.py      ← SQLite con aiosqlite
│   ├── .env             ← Credenciales (no compartir)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx              ← Barra superior + navegación
│       ├── api.ts               ← Cliente HTTP al backend
│       └── components/
│           ├── Mercado.tsx      ← Tabla de fichajes con filtros
│           ├── MiPlantilla.tsx  ← Tarjetas de mis jugadores
│           ├── CerebroIA.tsx    ← Sincronización + consejos IA
│           └── Liga.tsx         ← Clasificación + transferencias + gráficos
└── README.md
```

---

## 🔑 Variables de entorno (`backend/.env`)

| Variable | Descripción |
|---|---|
| `BIWENGER_TOKEN` | JWT de autenticación (caduca periódicamente) |
| `BIWENGER_LEAGUE` | ID de tu liga |
| `BIWENGER_USER` | Tu ID de usuario |
| `BIWENGER_VERSION` | Versión de la API |
| `GEMINI_API_KEY` | Clave de la API de Google Gemini |
| `COMPETITION` | `world-cup` o `laliga` |

---

## 🧠 Motor de IA

Los consejos se generan con **Gemini 2.0 Flash** analizando:

- 📊 Puntuación de Oportunidad (0-100) por jugador del mercado
- 💰 ROI de tu plantilla actual
- 🔍 Movimientos recientes de rivales  
- 📅 Calendario de las próximas 5 jornadas
- 🏃 Probabilidad de titularidad

Los 5 consejos son: **COMPRAR · VENDER · 11 IDEAL · ESPECULACIÓN · ALERTA RIVALES**
