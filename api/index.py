from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import sys

# Ajouter le dossier parent au path pour que les imports fonctionnent sur Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from api.artworks import router as artworks_router
    from api.artwork_types import router as artwork_types_router
    from api.events import router as events_router
    from api.orders import router as orders_router
    from api.dashboard import router as dashboard_router
    from api.auth_admin import router as auth_router
    from api.subscribe import router as subscribe_router_old  # Ancien endpoint (deprecated)
    from app.routers.newsletter import router as newsletter_router
except ImportError:
    # Fallback aux imports relatifs si les absolus ne marchent pas
    from .artworks import router as artworks_router
    from .artwork_types import router as artwork_types_router
    from .events import router as events_router
    from .orders import router as orders_router
    from .dashboard import router as dashboard_router
    from .auth_admin import router as auth_router
    from .subscribe import router as subscribe_router_old  # Ancien endpoint (deprecated)
    from app.routers.newsletter import router as newsletter_router

app = FastAPI(
    title="Elisabeth Constantin API",
    description="API pour le site d'art d'Elisabeth Constantin",
    version="1.0.0"
)

# Configuration CORS
allowed_origins_str = os.getenv("FRONTEND_URL", "http://localhost:5173")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",")]

# Si on utilise "*" (wildcard), désactiver credentials
allow_credentials = "*" not in allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router, prefix="/api/admin", tags=["admin-auth"])
app.include_router(dashboard_router, prefix="/api/admin", tags=["admin-dashboard"])
app.include_router(artworks_router, prefix="/api/artworks", tags=["artworks"])
app.include_router(artwork_types_router, prefix="/api/artwork-types", tags=["artwork-types"])
app.include_router(events_router, prefix="/api/events", tags=["events"])
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])

# Newsletter endpoints (nouveau système avec double opt-in)
app.include_router(newsletter_router, prefix="/api/newsletter", tags=["newsletter"])

# Ancien endpoint de souscription (deprecated - à garder pour compatibilité temporaire)
app.include_router(subscribe_router_old, prefix="/api/subscribe", tags=["subscribe-deprecated"])

# Webhook MailerLite pour synchroniser les statuts
try:
    from api.webhook_mailerlite import router as webhook_router
    app.include_router(webhook_router, prefix="/api/webhooks/mailerlite", tags=["webhooks"])
except ImportError:
    from .webhook_mailerlite import router as webhook_router
    app.include_router(webhook_router, prefix="/api/webhooks/mailerlite", tags=["webhooks"])

@app.get("/health")
async def health():
    """Liveness probe: ne dépend d'aucune ressource externe (Mongo, Stripe, MailerLite)."""
    return {"status": "ok"}

@app.get("/")
async def root():
    return {
        "message": "Elisabeth Constantin API - FastAPI",
        "status": "healthy",
        "endpoints": {
            "artworks": "/api/artworks",
            "events": "/api/events", 
            "orders": "/api/orders",
            "admin": "/api/admin"
        }
    }

@app.get("/api")
async def api_root():
    return {
        "message": "Elisabeth Constantin API - FastAPI",
        "status": "healthy",
        "endpoints": {
            "artworks": "/api/artworks",
            "events": "/api/events", 
            "orders": "/api/orders",
            "admin": "/api/admin"
        }
    }

# L'application FastAPI est automatiquement détectée par Vercel
# via le nom 'app' et sera servie avec uvicorn
