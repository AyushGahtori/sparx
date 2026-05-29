from fastapi import APIRouter

from app.api.routes import agents, callbacks, calls, campaigns, deepgram, health, summaries, system, twilio, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(twilio.router, tags=["Twilio"])
api_router.include_router(deepgram.router, tags=["Deepgram"])
api_router.include_router(calls.router, tags=["Calls"])
api_router.include_router(campaigns.router, tags=["Campaigns"])
api_router.include_router(callbacks.router, tags=["Callbacks"])
api_router.include_router(summaries.router, tags=["Summaries"])
api_router.include_router(agents.router, tags=["Agents"])
api_router.include_router(webhooks.router, tags=["Webhooks"])
api_router.include_router(system.router, tags=["System"])
