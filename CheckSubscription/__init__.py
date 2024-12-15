# api/CheckSubscription/__init__.py
import logging
import json
import os
import azure.functions as func
import stripe
from datetime import datetime
from ..shared.services.cosmos_service import CosmosService
from ..shared.auth.decorator import require_auth
stripe.api_key = os.environ.get('REACT_APP_STRIPE_SECRET_KEY')

@require_auth
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Get user ID from auth claims
        claims = getattr(req, 'auth_claims')
        user_id = claims.get('sub') or claims.get('oid') or claims.get('name')

        if not user_id:
            return func.HttpResponse(
                json.dumps({"error": "User not authenticated"}),
                status_code=401,
                mimetype="application/json"
            )

        cosmos_service = CosmosService()
        user = await cosmos_service.get_user(user_id)

        if not user:
            return func.HttpResponse(
                json.dumps({"error": "User not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        is_subscribed = False
        if user.subscription_status == "active":
           is_subscribed = True

        return func.HttpResponse(
            json.dumps({"tier": "PREMIUM" if is_subscribed else "FREE", "isSubscribed": is_subscribed}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error checking subscription status: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
