# api/RegenerateImage/__init__.py
import logging
import json
import os
import uuid
import azure.functions as func
from ..shared.auth.decorator import require_auth
from ..shared.services.cosmos_service import CosmosService
from ..GenerateStory.__init__ import generate_image_stable_diffusion, generate_image_flux_schnell, generate_image_flux_pro, generate_image_google_imagen, save_to_blob_storage, generate_sas_token
import asyncio
from urllib.parse import urlparse
import aiohttp
from azure.storage.blob import BlobServiceClient, ContentSettings, generate_blob_sas, BlobSasPermissions, __version__
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

IMAGE_CONTAINER_NAME = "storyfairy-images" 

@require_auth
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        claims = getattr(req, 'auth_claims')
        user_id = claims.get('sub') or claims.get('oid') or claims.get('name')

        req_body = req.get_json()
        prompt = req_body.get('prompt')
        image_style = req_body.get('imageStyle')
        image_model = req_body.get('imageModel')
        story_id = req_body.get('storyId')
        image_index = req_body.get('imageIndex')

        if any(x is None for x in [prompt, image_style, image_model, story_id, image_index]):
            return func.HttpResponse(
                json.dumps({"error": "Prompt, imageStyle, imageModel, storyId and imageIndex are required"}),
                status_code=400,
                mimetype="application/json"
            )

        # Get user subscription status
        cosmos_service = CosmosService()
        user = await cosmos_service.get_user(user_id)

        if not user or not user.subscription_status or user.subscription_status != 'active':
            return func.HttpResponse(
                json.dumps({"error": "Premium subscription required"}),
                status_code=403,
                mimetype="application/json"
            )
        story = await cosmos_service.get_story_by_id(story_id,user_id);
        if not story:
            return func.HttpResponse(
                json.dumps({"error": "Story not found"}),
                status_code=404,
                mimetype="application/json"
            )
        if not story.get("images") or len(story.get("images")) <= image_index:
           return func.HttpResponse(
                    json.dumps({"error": "Invalid image index"}),
                    status_code=400,
                    mimetype="application/json"
                )

         # Extract the existing blob name from the imageUrl
        image_url = story["images"][image_index]["imageUrl"]
        parsed_url = urlparse(image_url)
        image_filename = os.path.basename(parsed_url.path);
        logging.info(f"Extracting image filename: {image_filename} from image url: {image_url}")
        # Generate new image using existing functions
        if image_model == 'flux_schnell':
            image_url, _ = await generate_image_flux_schnell(prompt)
        elif image_model == 'flux_pro':
            image_url, _ = await generate_image_flux_pro(prompt)
        elif image_model == 'stable_diffusion_3':
            image_url, _ = await generate_image_stable_diffusion(prompt, story["images"][image_index]["imageUrl"])
        elif image_model == 'imagen_3':
            image_url, _ = await generate_image_google_imagen(prompt, os.environ.get('GEMINI_API_KEY'))
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid image model: {image_model}"}),
                mimetype="application/json",
                status_code=400
            )

        if not image_url:
            return func.HttpResponse(
                json.dumps({"error": "Failed to generate image"}),
                status_code=500,
                mimetype="application/json"
            )
        connection_string = os.environ.get('STORAGE_CONNECTION_STRING')
        logging.info(f"Generate Image URL: {image_url}")
        
         # Save to Blob Storage
        async with aiohttp.ClientSession() as session:
             async with session.get(image_url) as response:
                    image_data = await response.read()
                    saved_url = save_to_blob_storage(
                        image_data, 
                        "image/jpeg",
                        "storyfairy-images",
                        image_filename,
                        connection_string
                    )

        if not saved_url:
                return func.HttpResponse(
                    json.dumps({"error": "Failed to save image to blob storage"}),
                    status_code=500,
                    mimetype="application/json"
                )
        logging.info(f"Saved image to blob storage: {saved_url}")
        
        parsed_url = urlparse(saved_url)
        blob_name = os.path.basename(parsed_url.path)
        image_url = f"/api/blob/{blob_name}"
        
        image_url_without_sas = f"/api/blob/{blob_name}?container=storyfairy-images"
        
        #Update Cosmos DB
        story["images"][image_index]["imageUrl"] = image_url
        await cosmos_service.update_story(story)

        return func.HttpResponse(
            json.dumps({"url": image_url_without_sas}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error regenerating image: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )