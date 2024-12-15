# api/Subscribe/__init__.py
import logging
import json
import os
import azure.functions as func
import stripe
from datetime import datetime, timedelta
from ..shared.services.cosmos_service import CosmosService
from ..shared.auth.decorator import require_auth

stripe.api_key = os.environ.get('REACT_APP_STRIPE_SECRET_KEY')
#SUBSCRIPTION_PRICE_ID = os.environ.get('REACT_APP_STRIPE_SUBSCRIPTION_PRICE_ID')

@require_auth
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Get user ID from auth claims
        claims = getattr(req, 'auth_claims')
        logging.info(f"Auth claims: {claims}")
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

        # Get price id from the request body
        try:
            req_body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid request body"}),
                status_code=400,
                mimetype="application/json"
            )

        price_id = req_body.get('priceId')
        if not price_id:
            return func.HttpResponse(
                json.dumps({"error": "Price ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        base_url = 'http://localhost:3000' if os.getenv('ENVT') == 'Development' else 'https://www.storyfairy.app'
        # Create Stripe checkout session
        session = stripe.checkout.Session.create(
            mode='subscription',
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            success_url = f"{base_url}/payment-status?status=success&session_id={{CHECKOUT_SESSION_ID}}", 
            cancel_url = f"{base_url}/payment-status?status=cancelled",
            metadata={
                'user_id': user_id,
                'type': 'subscription'
            }
        )

        return func.HttpResponse(
            json.dumps({"sessionUrl": session.url}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error creating subscription: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )