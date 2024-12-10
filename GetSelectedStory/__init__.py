# GetSelectedStory/init.py  
import logging  
import json  
import azure.functions as func  
from ..shared.auth.decorator import require_auth  
from ..shared.services.cosmos_service import CosmosService  
from urllib.parse import urlparse  

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

        # Get story ID from request  
        story_id = req.route_params.get('storyId')  
        logging.info(f"Story ID: {story_id}")  

        if not story_id:  
            return func.HttpResponse(  
                json.dumps({"error": "Story ID is required"}),  
                status_code=400,  
                mimetype="application/json"  
            )  

        # Initialize services  
        cosmos_service = CosmosService()  

        # Get story metadata from Cosmos DB  
        story = await cosmos_service.get_story_by_id(story_id, user_id)  
        logging.info(f"Story: {story}")  

        if not story:  
            return func.HttpResponse(  
                json.dumps({"error": "Story not found or unauthorized"}),  
                status_code=404,  
                mimetype="application/json"  
            )  

        # Function to convert blob URL to API proxy URL  
        def get_proxy_url(blob_url):  
            if not blob_url:  
                return None  
            blob_name = blob_url.split('/')[-1]  
            return f"/api/blob/{blob_name}?container=storyfairy-images"  

        # Process images  
        processed_images = []  
        for image in story.get('images', []):  
            processed_image = {  
                'prompt': image.get('prompt', ''),  
                'imageUrl': get_proxy_url(image.get('imageUrl'))  
            }  
            processed_images.append(processed_image)  

        # Process cover images  
        processed_cover_images = {}  
        for cover_type, cover_data in story.get('coverImages', {}).items():  
            processed_cover_images[cover_type] = {  
                'prompt': cover_data.get('prompt', ''),  
                'url': get_proxy_url(cover_data.get('url'))  
            }  

        # Prepare response  
        response_data = {  
            "id": story["id"],  
            "userId": story["userId"],  
            "title": story["title"],  
            "storyText": story["storyText"],  
            "detailedStoryText": story["detailedStoryText"],  
            "createdAt": story["createdAt"],  
            "metadata": story["metadata"],  
            "images": processed_images,  
            "coverImages": processed_cover_images  
        }  

        return func.HttpResponse(  
            json.dumps(response_data),  
            status_code=200,  
            mimetype="application/json"  
        )  

    except Exception as error:  
        logging.error(f'Error in GetSelectedStory: {str(error)}')  
        return func.HttpResponse(  
            json.dumps({"error": str(error)}),  
            status_code=500,  
            mimetype="application/json"  
        )  