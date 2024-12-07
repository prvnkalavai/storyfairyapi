# api/shared/auth/decorator.py
import json
import logging
import os
from typing import Callable, TypeVar, cast
from azure.functions import HttpRequest, HttpResponse
from functools import wraps
from .middleware import AuthMiddleware
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

T = TypeVar('T', bound=Callable[..., HttpResponse])

def get_secrets_from_keyvault(secret_name: str) -> str:
    logging.info("Getting secret from Key Vault", secret_name)
    key_vault_url = "https://kv-storyfairy.vault.azure.net/"
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=key_vault_url, credential=credential)
    return client.get_secret(secret_name).value

def require_auth(func: T) -> T:
  """Decorator to require authentication for Function App endpoints"""
  @wraps(func)
  async def wrapper(req: HttpRequest, *args, **kwargs) -> HttpResponse:
      try:
          #logging.info(f"Logging the token from the request in decorator before extracting it in middleware: {req.headers.get('X-My-Auth-Token')}")
      
          # Initialize AuthMiddleware here instead of importing
          auth_middleware = AuthMiddleware(
              tenant="storyfairy",
              client_id="acbb77b8-2056-46eb-8026-8c6bcb9b73cd",
              user_flow="B2C_1_Storyfairy_SUSI",
              tenant_id="011d91cd-02a5-4ba6-a39c-5d99324308f4"
              #tenant=get_secrets_from_keyvault('b2c-tenant'),
              #client_id=get_secrets_from_keyvault('b2c-client-id'),
              #user_flow=get_secrets_from_keyvault('b2c-user-flow'),
              #tenant_id=get_secrets_from_keyvault('b2c-tenant-id')
          )
          
          token = auth_middleware.get_token_from_header(req)
          if not token:
              return HttpResponse(
                  json.dumps({"error": "No authorization token provided"}),
                  status_code=401,
                  mimetype="application/json"
              )

          claims = auth_middleware.validate_token(token)
          setattr(req, 'auth_claims', claims)

          return await func(req, *args, **kwargs)

      except Exception as e:
          logging.error(f"Authentication error: {str(e)}")
          return HttpResponse(
              json.dumps({"error": f"Authentication error: {str(e)}"}),
              status_code=401,
              mimetype="application/json"
          )

  return cast(T, wrapper)