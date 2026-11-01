# CANScope

CANScope is a simulated automotive CAN bus analysis platform built with a FastAPI backend and a React dashboard.

## Features

- Virtual ECU simulation for engine, ABS, BMS, and dashboard systems
- Real-time CAN traffic generation and WebSocket broadcasting
- Signal decoding and live diagnostics
- Fault injection and anomaly detection
- SQLite event and frame persistence
- Dashboard metrics, signal trends, and CAN frame inspection

## Run locally

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open the dashboard at http://localhost:5173.

The backend API is available at http://localhost:8000/api/dashboard and the WebSocket is at ws://localhost:8000/ws/traffic.
