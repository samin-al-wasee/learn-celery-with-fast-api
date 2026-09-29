from fastapi import FastAPI

from app.api.routes import appointments, auth, call, chat, exports, health, records, users
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.request_id import install_request_id

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)
register_exception_handlers(app)
install_request_id(app, "monolith")
app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(users.router, prefix=settings.api_v1_prefix)
app.include_router(appointments.router, prefix=settings.api_v1_prefix)
app.include_router(records.router, prefix=settings.api_v1_prefix)
app.include_router(exports.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)
app.include_router(call.router, prefix=settings.api_v1_prefix)