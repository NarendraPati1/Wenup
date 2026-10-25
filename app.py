"""
app.py — The Main Engine / Launchpad for the Backend!

In plain English:
This file starts our web server. When the user types something in the chat box
on their browser, their browser sends a message to this server, which then processes
it and sends back a response.
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Bring in all our API endpoints (the URLs our frontend talks to)
from backend.routes import api_router

# 1. Create our web app instance using FastAPI (super fast Python web framework)
app = FastAPI(title="Document Intake Assistant")

# 2. CORS (Cross-Origin Resource Sharing) setup:
# Think of this as giving a security pass to our React frontend running on port 5173.
# Without this pass, modern browsers block frontend-to-backend communication for security reasons.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],  # Allow GET, POST, etc.
    allow_headers=["*"],  # Allow all headers like Content-Type
)

# 3. Plug in all the chat routes (like /api/chat, /api/initial, etc.)
app.include_router(api_router)


# 4. A quick health check route:
# If you visit http://127.0.0.1:8000/ in your browser, you will see {"status": "ok"}.
# It's an easy way to verify that the server is alive and kicking!
@app.get("/")
def index():
    return {"status": "ok"}


# 5. Start the server when this script is run directly: `python app.py`
# It listens on 127.0.0.1 (localhost) on port 8000.
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
