import logging
import azure.functions as func
import openai
import os
import requests
import replicate
import json
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv
load_dotenv()

openai.api_key = os.environ["OPENAI_API_KEY"] # Store your API key securely as an environment variable.
replicate_api_token = os.environ["REPLICATE_API_TOKEN"] # Get Replicate API token


async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        topic = req.params.get('topic')
        if not topic:
            try:
                req_body = req.get_json()
            except ValueError:
                pass
            else:
                topic = req_body.get('topic')

        if topic:
        
            client = openai.OpenAI() # Initialize client

            story_response = client.chat.completions.create(
                model="gpt-4o-mini",  # Or your preferred model
                messages=[
                    {"role": "system", "content": "You are a creative storyteller for children."},
                    {"role": "user", "content": f"Write a short, creative story about {topic}"}
                ],
                max_tokens=200,
            )

            story = story_response.choices[0].message.content


            # *** Image Generation Logic ***
            image_urls = []
            sentences = story.split('. ') # Split the story into sentences for image prompts
            for i, sentence in enumerate(sentences):
                if i<4:  # generate 2 images.  Set higher for more images (be mindful of Replicate usage costs)

                    try:
                        output = replicate.run(
                            "stability-ai/stable-diffusion:db21e45d3f7023abc2a46ee38a23973f6dce16bb082a930b0c49861f96d1e5bf",  # Stable Diffusion model on Replicate
                            input={"prompt": sentence}
                        )


                        image_urls.append(output) # Add the image URL to the list
                        logging.info(f"Generated image {i + 1}: {output}")
                        print(f"Image generated for sentence {i+1}: {output}")
                    except Exception as e: # Catch API or network errors related to replicate
                        logging.error(f"Error generating image for sentence {i + 1} using Replicate: {str(e)}")
            
            # Construct and return the response
            return_data = {
                "storyText": story,
                "images": image_urls

            }
            # Convert the dictionary to a JSON string
            json_compatible_data = json.dumps(return_data, default=str)

            return func.HttpResponse(
                body=json_compatible_data,
                mimetype="application/json",
                status_code=200
            )                        
        else:
            return func.HttpResponse(
                 "Please pass a topic on the query string or in the request body",
                 status_code=400
            )
    except Exception as e:  # Handle exceptions properly
        logging.error(f"An error occurred: {e}")
        return func.HttpResponse(
            "An error occurred while processing your request.",
            status_code=500
        )