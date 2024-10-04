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
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, ContentSettings
import time
import nltk
import google.generativeai as genai
import numpy
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

nltk.download('punkt')
nltk.download('punkt_tab')
nltk.download('averaged_perceptron_tagger')
nltk.download('maxent_ne_chunker')
nltk.download('words')
nltk.download('averaged_perceptron_tagger_eng')
nltk.download('maxent_ne_chunker_tab')

load_dotenv()

STORY_CONTAINER_NAME = "storyfairy-stories" # Container for Stories
IMAGE_CONTAINER_NAME = "storyfairy-images" # Container for Images

def generate_story_openai(topic, api_key):
    try:
        openai.api_key = api_key
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Or a suitable model
            messages=[
                {"role": "system", "content": "You are a creative storyteller for children."},
                {"role": "user", "content": f"Write a short, funny children's story about {topic} that is no more than 4-5 sentences long. Make the characters and the scene of the story as descriptive as possible"}
            ],
            max_tokens=200
        )
        story = response.choices[0].message.content
        logging.info(f"Generated story: {story}")
        return story
    except (openai.OpenAIError, requests.exceptions.RequestException) as e: # Catch OpenAI errors
        logging.error(f"OpenAI API error: {e}")
        return None
       
def generate_story_gemini(topic, api_key):
    try:
        Gemini_api_key = api_key
        genai.configure(api_key=Gemini_api_key)
        prompt = f"Write a short, funny children's story about {topic} that is no more than 4-5 sentences long. Make the characters and the scene of the story as descriptive as possible"
        model = genai.GenerativeModel('gemini-1.5-flash') # or 'gemini-pro'
        response = model.generate_content(prompt)
        story = response.text
        logging.info(f"Generated story (Gemini): {story}")
        logging.info(f"Prompt used for Gemini: {prompt}")
        return story
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return None   

def generate_image_stable_diffusion(prompt):
    try:
        output = replicate.run(
           "stability-ai/stable-diffusion-3",  # Stable Diffusion model
            input={
                "cfg": 7,
                    "steps": 28,
                    "prompt": prompt,
                    "output_quality": 90,
                    "negative_prompt": "ugly, blurry, distorted, text, watermark",
                    "prompt_strength": 0.85,
                    "scheduler": "K_EULER_ANCESTRAL",
                    "width": 768, 
                    "height": 512               
            }
        )
        image_url = output[0] # Get first element of returned list which is the URL
        logging.info(f"Generated image (Stable Diffusion): {image_url}")  # Log generated URL
        return image_url, prompt  # Return URL and prompt
    except Exception as e:
        logging.error(f"Stable Diffusion error: {e}")
        return None, prompt # Return None for URL and the prompt
   
def generate_image_flux_schnell(prompt):
    try:
        output = replicate.run(
            "black-forest-labs/flux-schnell",  # Flux Schnell model
            input={
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "go_fast": True,
                "megapixels": "1",
                "num_outputs": 1,
                "output_quality": 80,
                "num_inference_steps": 4
                }                
            )
        image_url = output[0]
        logging.info(f"Generated image (Flux Schnell): {image_url}")  # Log the generated image URL
        return image_url, prompt  # Return URL and prompt
    except Exception as e:
        logging.error(f"Flux Schnell error: {e}")
        return None, prompt
    
def split_story(story):
    sentences = story.split('. ')  # Split into sentences
    return sentences

def save_to_blob_storage(data, content_type, container_name, file_name, connection_string): # New Function to save to blob storage
  try:
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)

    if container_name == STORY_CONTAINER_NAME:
        file_name += ".txt"
    else:
        file_name += ".png" # Check and change the image format as needed
        
    blob_client = container_client.get_blob_client(file_name)

    blob_client.upload_blob(data, blob_type="BlockBlob", content_settings=ContentSettings(content_type=content_type))
    logging.info(f"File {file_name} uploaded to blob storage in container: {container_name}")

    return blob_client.url # Return the blob URL

  except Exception as e:
    logging.error(f"Error uploading to blob storage: {e}")
    return None

def construct_detailed_prompt(sentence, sentences, character_descriptions, image_style="whimsical"):
    previous_sentence = sentences[sentences.index(sentence)-1] if sentences.index(sentence) > 0 else "" # Get previous sentence, handle first sentence case
    prompt = f"{previous_sentence} {sentence}"
    logging.info('################ Entering enhance_prompt_with_context() Function ################')
    prompt = enhance_prompt_with_context(prompt, character_descriptions, sentence)
    final_prompt = f"{prompt}, {image_style} style, children's book illustration, vibrant colors"
    return final_prompt

def enhance_prompt_with_context(prompt, character_descriptions, sentence):
    for chunk in nltk.ne_chunk(nltk.pos_tag(nltk.word_tokenize(sentence))):
        if hasattr(chunk, 'label') and chunk.label() == 'PERSON':  # Identify named entities
            character_name = ' '.join(c[0] for c in chunk)
            
            # Attempt to extract a simple description (adjective before the name)
            words = nltk.word_tokenize(sentence)
            name_index = words.index(character_name.split()[-1]) # Use last name if it's multiple words
            if name_index > 0 and nltk.pos_tag([words[name_index - 1]])[0][1].startswith('JJ'): # Check if adjective before name.
                description = words[name_index - 1]
                character_descriptions[character_name] = description

    # Scene Description Extraction (using simple heuristics)
    scene_keywords = ["in a", "inside a", "at the", "on a", "beneath the", "above the"] # Extend list as needed
    for keyword in scene_keywords:
        if keyword in sentence.lower():
            scene_description = sentence.split(keyword, 1)[1].strip() # Split after first instance of keyword.
            prompt = f"{prompt}, {scene_description}"
            break  # Use first matching scene description found

    return prompt
    
async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        if os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT") is None: # Check if development environment
            logging.info("Using local authentication")
            
        else:  # Azure environment
            logging.info("Using Managed Identity authentication.")
            
        key_vault_uri = os.environ["KEY_VAULT_URI"]
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=key_vault_uri, credential=credential)
        openai.api_key = client.get_secret("openai-api-key").value
        GEMINI_API_KEY = client.get_secret("gemini-api-key").value
        REPLICATE_API_TOKEN = client.get_secret("replicate-api-token").value
        os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN
        STORAGE_CONNECTION_STRING = client.get_secret("storage-connection-string").value
        
        topic = req.params.get('topic')
        if not topic:
            try:
                req_body = req.get_json()
            except ValueError:
                pass
            else:
                topic = req_body.get('topic')

        if topic:
            story = generate_story_gemini(topic, GEMINI_API_KEY)
            if story is None: # Check if openai story generation failed
                story = generate_story_openai(topic, openai.api_key)  # Gemini fallback
                if story is None: # If gemini also fails
                    return func.HttpResponse("Failed to generate story using OpenAI and Gemini", status_code=500)

            sentences = split_story(story)
            character_descriptions = {}
            image_urls = []
            image_prompts = []

            for i, sentence in enumerate(sentences):  # Iterate through ALL sentences
                logging.info('################ Entering construct_detailed_prompt() Function ################')
                detailed_prompt = construct_detailed_prompt(sentence, sentences, character_descriptions) # Create detailed prompt

                logging.info('################ Entering generate_image_flux_schnell() Function ################')
                image_url, prompt = generate_image_flux_schnell(detailed_prompt) # Use default whimsical style

                if image_url is None:  # Stable Diffusion fallback
                    image_url, prompt = generate_image_stable_diffusion(detailed_prompt)
                    if image_url is None: # If flux schnell also fails
                        logging.error(f"Failed to generate image for prompt: {prompt}") # Log the failing prompt
                        continue # Skip this sentence and move to next one.

                image_urls.append(image_url)
                image_prompts.append(prompt)
                time.sleep(1)

            story_filename = f"{topic.replace(' ', '_')}" # Meaningful story filename
            story_url = save_to_blob_storage(story, "text/plain", STORY_CONTAINER_NAME, story_filename, STORAGE_CONNECTION_STRING)
            if story_url is None: # Handle story upload failure
                return func.HttpResponse("Failed to upload story to blob storage", status_code=500)
            
            
            saved_image_urls = []
            response_data = {  # Initialize response data here
                "storyText": story,
                "storyUrl": story_url,
                "images": []
            }
            for i, image_url in enumerate(image_urls):
                try:
                    image_response = requests.get(image_url)  # Get the actual URL from the list returned by replicate
                    image_response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                    image_data = image_response.content
                    image_filename = f"{topic.replace(' ', '_')}-image{i+1}" # Updated image file name
                    saved_image_url = save_to_blob_storage(image_data, "image/jpeg", IMAGE_CONTAINER_NAME, image_filename, STORAGE_CONNECTION_STRING) # Pass file_name

                    if saved_image_url: # Check if upload was successful
                        response_data["images"].append({
                            "imageUrl": saved_image_url,
                            "prompt": image_prompts[i]
                        })
                        logging.info(f"Generated image {i+1} URL: {saved_image_url}")
                        logging.info(f"Prompt used for image {i+1}: {image_prompts[i]}")  # Log prompt with image URL
                    
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error downloading image: {e}")
                except Exception as e:
                    logging.error(f"Error saving image {i+1} to blob storage: {e}")

            return func.HttpResponse(
                json.dumps(response_data, default=str),  # Return grouped image URLs and prompts
                mimetype="application/json",
                status_code=200
            )
        else:
            return func.HttpResponse(
                "Please pass a topic on the query string or in the request body",
                status_code=400
            )
    except Exception as e:
        logging.exception(f"An error occurred: {e}")
        return func.HttpResponse(
            "An error occurred while processing your request.",
            status_code=500
        )