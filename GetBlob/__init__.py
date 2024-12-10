import logging  
import os  
import azure.functions as func  
from azure.storage.blob import BlobServiceClient  
from azure.identity import DefaultAzureCredential  
from azure.core.exceptions import ResourceNotFoundError  

def main(req: func.HttpRequest) -> func.HttpResponse:  
    logging.info("GetBlob function triggered.")  
    try:  
        blob_name = req.route_params.get('blob_name')  
        # Allow container to be specified in query params, default to storyfairy-images  
        container_name = req.params.get('container', 'storyfairy-images')  

        # Validate container name  
        if container_name not in ['storyfairy-images', 'storyfairy-stories']:  
            return func.HttpResponse(  
                "Invalid container name", status_code=400  
            )  

        if not blob_name:  
            return func.HttpResponse(  
                "Blob name is required.", status_code=400  
            )  

        account_name = os.environ.get("ACCOUNT_NAME")  
        if not account_name:  
            logging.error("Storage account name not configured.")  
            return func.HttpResponse(  
                "Storage account configuration missing.", status_code=500  
            )  
        account_url = f"https://{account_name}.blob.core.windows.net"  

        try:  
            credential = DefaultAzureCredential()  
            logging.info(f"Using DefaultAzureCredential for authentication.")  
            blob_service_client = BlobServiceClient(account_url, credential=credential)  
        except Exception as auth_error:  
            logging.exception("Authentication error accessing storage account")  
            return func.HttpResponse(  
                f"Failed to authenticate with storage account: {str(auth_error)}",  
                status_code=500  
            )  

        try:  
            logging.info(f"Getting blob {blob_name} from container {container_name}")  
            container_client = blob_service_client.get_container_client(container_name)  
            blob_client = container_client.get_blob_client(blob_name)  

            if not blob_client.exists():  
                logging.warning(f"Blob {blob_name} not found")  
                return func.HttpResponse(  
                    "Blob not found", status_code=404  
                )  

            blob_data = blob_client.download_blob()  
            content = blob_data.readall()  
            content_type = blob_data.properties.content_settings.content_type  

            return func.HttpResponse(  
                content,  
                mimetype=content_type,  
                status_code=200  
            )  

        except ResourceNotFoundError:  
            logging.exception("Resource not found error")  
            return func.HttpResponse("Resource not found", status_code=404)  
        except Exception as blob_error:  
            logging.exception("Error accessing blob")  
            return func.HttpResponse("Error accessing blob", status_code=500)  

    except Exception as e:  
        logging.exception("An unexpected error occurred")  
        return func.HttpResponse(  
            "Internal server error", status_code=500  
        )  