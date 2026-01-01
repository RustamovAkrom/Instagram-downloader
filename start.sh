#!/bin/sh

# создаем сессию, если ее нет
if [ ! -f /sessions/ig_session.json ]; then
    echo "Creating Instagram session..."
    python create_session.py
fi

# запускаем FastAPI
uvicorn app.main:app --host 0.0.0.0 --port 8000
