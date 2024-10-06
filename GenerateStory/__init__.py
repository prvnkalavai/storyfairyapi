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
from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag
from nltk.chunk import ne_chunk
import google.generativeai as genai
import numpy
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

try:
    nltk.download('punkt')
    nltk.download('punkt_tab')
    nltk.download('averaged_perceptron_tagger')
    nltk.download('maxent_ne_chunker')
    nltk.download('words')
    nltk.download('averaged_perceptron_tagger_eng')
    nltk.download('maxent_ne_chunker_tab')
except Exception as e:
    logging.error(f"Error downloading NLTK resources: {e}")

load_dotenv()

STORY_CONTAINER_NAME = "storyfairy-stories" # Container for Stories
IMAGE_CONTAINER_NAME = "storyfairy-images" # Container for Images

def generate_story_openai(topic, api_key):
    try:
        openai.api_key = api_key
        client = openai.OpenAI()
        prompt = f"""
            Write a short, imaginative and creative 5 sentence children's story about {topic}.  

            Format the story in the following JSON format to ensure consistent structure: Avoid having any markdown components in the JSON output.            
            {{
                "sentences": [
                    "Sentence 1 with full character and scene details.",
                    "Sentence 2 with full character and scene details.",
                    "Sentence 3 with full character and scene details.",
                    "Sentence 4 with full character and scene details.",
                    "Sentence 5 with full character and scene details." 
                ]
            }}
            
            Crucially, EVERY sentence must include these details:
            * **Central Character:**  Always mention the main character by name. Include a FULL description of their appearance, personality, and any unique attributes (e.g., clothing, toys) in EVERY sentence.  Be extremely repetitive with explicit details.
            * **Scene:**  Vividly describe the setting in EVERY sentence.  If the scene changes, provide the FULL new scene description in EVERY subsequent sentence.  Be extremely repetitive with explicit details.
            * **Supporting Characters:** If new characters appear, provide their FULL descriptions in EVERY sentence where they are present. Be extremely repetitive with explicit details.

            Example:
            "Leo, a brave knight with shining armor and a golden sword, stood in the dark, echoing castle, facing a fierce dragon with fiery breath."
            "Leo, a brave knight with shining armor and a golden sword, charged at the fierce dragon with fiery breath in the dark, echoing castle."
            # and so on...  Every sentence must mention ALL relevant characters and FULL scene details. Ensure no details are left out in any sentence. Make sure the story stays within the max_tokens limit.
            """
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Or a suitable model
            messages=[
                {"role": "system", "content": "You are a creative storyteller for children."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=350
        )
        #story = response.choices[0].message.content
        #return story
        logging.info(f"Raw response from OpenAI: {response.choices[0].message.content}")
        story, sentences = parse_story_json(response.choices[0].message.content.strip())
        logging.info(f"Parsed JSON story: {story}")
        return story, sentences       
        
    except (openai.OpenAIError, requests.exceptions.RequestException) as e: # Catch OpenAI errors
        logging.error(f"OpenAI API error: {e}")
        return None
       
def generate_story_gemini(topic, api_key):
    try:
        Gemini_api_key = api_key
        genai.configure(api_key=Gemini_api_key)
        prompt = f"""
            Write a short, imaginative and creative 5 sentence children's story about {topic}.  

            Format the story as a followind JSON object with each sentence as a separate entry in an array of sentences to ensure consistent structure:
            Avoid having any markdown components in the JSON output.
            {{
                "sentences": [
                    "Sentence 1 with full character and scene details.",
                    "Sentence 2 with full character and scene details.",
                    "Sentence 3 with full character and scene details.",
                    "Sentence 4 with full character and scene details.",
                    "Sentence 5 with full character and scene details." 
                ]
            }}
            
            Crucially, EVERY sentence must include these details:
            * **Central Character:**  Always mention the main character by name. Include a FULL description of their appearance, personality, and any unique attributes (e.g., clothing, toys) in EVERY sentence.  Be extremely repetitive with explicit details.
            * **Scene:**  Vividly describe the setting in EVERY sentence.  If the scene changes, provide the FULL new scene description in EVERY subsequent sentence.  Be extremely repetitive with explicit details.
            * **Supporting Characters:** If new characters appear, provide their FULL descriptions in EVERY sentence where they are present. Be extremely repetitive with explicit details.

            Example:
            "Leo, a brave knight with shining armor and a golden sword, stood in the dark, echoing castle, facing a fierce dragon with fiery breath."
            "Leo, a brave knight with shining armor and a golden sword, charged at the fierce dragon with fiery breath in the dark, echoing castle."
            # and so on...  Every sentence must mention ALL relevant characters and FULL scene details. Ensure no details are left out in any sentence
            """
        model = genai.GenerativeModel('gemini-1.5-flash') # or 'gemini-pro'
        response = model.generate_content(prompt)
        logging.info(f"Raw response from Gemini: {response.text}")
        story, sentences = parse_story_json(response.text.strip())
        logging.info(f"Parsed JSON story: {story}")
        return story, sentences
    
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return None   

def parse_story_json(story_response):
    """Parses the JSON response from the language model (OpenAI/Gemini), extracts sentences, and handles errors."""

    try:
        #story_json_string = story_json_string.replace("```json", "").strip()
        story_json = json.loads(story_response)
        raw_sentences = story_json['sentences']
        sentences = [sentence.strip() for sentence in raw_sentences]

        # Join sentences into a full story without new lines
        story = ' '.join(sentences)
        return story, sentences
    except Exception as e:
        logging.error(f"Error parsing JSON: {e}")
        logging.error(f"Invalid JSON string: {story_response}")
        return None, None

def simplify_story(detailed_story):
    try:
        client = openai.OpenAI() # Or use Gemini. Configure appropriately
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Suitable model for simplification
            messages=[
                {"role": "system", "content": "You are a helpful assistant that simplifies text."},
                {"role": "user", "content": f"Please simplify the following story, removing repetitive descriptions while maintaining the core narrative:\n\n{detailed_story}"}

            ],
            max_tokens=300 # Adjust if needed
        )
        simplified_story = response.choices[0].message.content
        logging.info(f"Simplified story:\n{simplified_story}")
        return simplified_story

    except Exception as e:
        logging.error(f"Error simplifying story: {e}")
        return detailed_story  # Return original story if simplification fails

def generate_reference_image(character_description):
    prompt = f"High-resolution portrait of {character_description}, full body, detailed, character concept art, trending on ArtStation" # Create prompt
    try:
        logging.info(f"Reference image prompt: {prompt}")
        output = replicate.run(
            "stability-ai/stable-diffusion-3", # Or another high-quality model
            input={
                "prompt": prompt,
                "cfg": 7,
                "steps": 28,
                "width": 1024, # Higher resolution
                "height": 1024, # Higher resolution
                "samples": 1, # Generate just one image.
                "aspect_ratio": "1:1",
                "output_quality": 90,
                "negative_prompt": "ugly, blurry, distorted, text, watermark",
                "prompt_strength": 0.85,
                "scheduler": "K_EULER_ANCESTRAL"
            }
        )

        image_url = output[0] # Get URL from replicate response
        logging.info(f"Generated reference image: {image_url}")

        return image_url  # Return URL of reference image.
    except Exception as e:
        logging.error(f"Error generating reference image: {e}")
        return None

def generate_image_stable_diffusion(prompt,reference_image_url=None):
    input_params = {
        "cfg": 7,
        "steps": 28,
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "output_quality": 90,
        "negative_prompt": "ugly, blurry, distorted, text, watermark",
        "prompt_strength": 0.85,
        "scheduler": "K_EULER_ANCESTRAL",
        "width": 768, 
        "height": 768  
    }
    if reference_image_url:
        input_params["image"] = reference_image_url
    try:
        output = replicate.run(
           "stability-ai/stable-diffusion-3",  # Stable Diffusion model
            input=input_params
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
    
def save_to_blob_storage(data, content_type, container_name, file_name, connection_string): 
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

def construct_detailed_prompt(sentence, image_style="whimsical"):
    prompt = f"{sentence}, {image_style} style, children's book illustration, vibrant colors"
    return prompt, None

async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('############### Python HTTP trigger function processed a request.################')

    try:
        if os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT") is None: # Check if development environment
            logging.info("################# Using local authentication #################")
            
        else:  # Azure environment
            logging.info("#################Using Managed Identity authentication. #################")
            
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
            story, sentences = generate_story_gemini(topic, GEMINI_API_KEY) 
            if story is None: # Check if gemini story generation failed
                story, sentences = generate_story_openai(topic, openai.api_key)  # Gemini fallback
                if story is None: # If openai also fails
                    return func.HttpResponse("Failed to generate story using OpenAI and Gemini", status_code=500)
            
            simplified_story = simplify_story(story)  # Simplify the story for presentation
            

            simplified_story_filename = f"{topic.replace(' ', '_')}" # Meaningful story filename
            detailed_story_filename = f"{topic.replace(' ', '_')}_detailed" # Separate file name for detailed story
            simplified_story_url = save_to_blob_storage(simplified_story, "text/plain", STORY_CONTAINER_NAME, simplified_story_filename, STORAGE_CONNECTION_STRING)
            detailed_story_url = save_to_blob_storage(story, "text/plain", STORY_CONTAINER_NAME, detailed_story_filename, STORAGE_CONNECTION_STRING)
            if simplified_story_url is None: # Handle story upload failure
                return func.HttpResponse("Failed to upload story to blob storage", status_code=500)
            if detailed_story_url is None: # Handle Detailed story upload failure
                return func.HttpResponse("Failed to upload Detailed story to blob storage", status_code=500)
            
            #story_json = json.loads(story) # Load detailed story, which is a json string into python dict
            #sentences = story_json.get("sentences", []) # Get the list of sentences from the dictionary
            response_data = {  # Initialize response data here
                "storyText": simplified_story,
                "storyUrl": simplified_story_url,
                "detailedStoryUrl": detailed_story_url,
                "images": []
            }
            
            image_urls = []
            image_prompts = []

            if sentences:
                for i, sentence in enumerate(sentences):  # Iterate through ALL sentences
                    logging.info('################ Entering construct_detailed_prompt() Function ################')
                    detailed_prompt, _ = construct_detailed_prompt(sentence) # Create detailed prompt, _ for unused reference image url
                
                    logging.info('################ Entering generate_image_stable_diffusion() Function ################')
                    image_url, prompt = generate_image_flux_schnell(detailed_prompt) # No reference image available
                    if image_url is None:  # Stable Diffusion fallback
                        image_url, prompt = generate_image_stable_diffusion(detailed_prompt) 
                        if image_url is None: # If flux schnell also fails
                            logging.error(f"Failed to generate image for prompt: {prompt}") # Log the failing prompt
                            continue # Skip this sentence and move to next one.

                    image_urls.append(image_url)
                    image_prompts.append(prompt)
                    time.sleep(1)

            else: # If sentences list is empty or None
                return func.HttpResponse("Error processing the story. Please try again.", status_code=500)
            
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