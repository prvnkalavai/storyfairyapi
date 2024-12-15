# api/RegenerateImage/__init__.py
import logging
import json
import azure.functions as func
from ..shared.auth.decorator import require_auth
from ..shared.services.cosmos_service import CosmosService

@require_auth
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        claims = getattr(req, 'auth_claims')
        user_id = claims.get('sub') or claims.get('oid') or claims.get('name')

        req_body = req.get_json()
        prompt = req_body.get('prompt')
        image_style = req_body.get('imageStyle')
        image_model = req_body.get('imageModel')
        reference_image_url = req_body.get('referenceImageUrl')

        if not prompt:
            return func.HttpResponse(
                json.dumps({"error": "Prompt is required"}),
                status_code=400,
                mimetype="application/json"
            )

        # Get user subscription status
        cosmos_service = CosmosService()
        user = await cosmos_service.get_user(user_id)

        if not user or not user.subscription or user.subscription.status != 'active':
            return func.HttpResponse(
                json.dumps({"error": "Premium subscription required"}),
                status_code=403,
                mimetype="application/json"
            )

        # Generate new image using existing functions
        if reference_image_url:
            image_url, _ = await generate_image_with_reference(
                prompt,
                reference_image_url,
                image_style,
                image_model
            )
        else:
            image_url, _ = await generate_image(
                prompt,
                image_style,
                image_model
            )

        if not image_url:
            return func.HttpResponse(
                json.dumps({"error": "Failed to generate image"}),
                status_code=500,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps({"url": image_url}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error regenerating image: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )