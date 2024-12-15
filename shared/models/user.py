# api/shared/models/user.py
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel

class User(BaseModel):
  id: str
  user_id: str
  email: str
  credits: int
  created_at: str
  updated_at: str
  subscription_status: Optional[Literal['active','inactive','cancelled']] = None
  subscription_start_date: Optional[str] = None
  subscription_end_date: Optional[str] = None
  stripe_subscription_id: Optional[str] = None

class UserDTO(BaseModel):
  user_id: str
  email: str
  credits: int