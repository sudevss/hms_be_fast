"""
login.py - Complete Updated File
REPLACE your existing login.py with this entire file
Location: Same as your current login.py file
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt
import hashlib

from database import get_db
from model import UserMaster, Facility

# Import from auth_middleware (make sure auth_middleware.py is created first)
from auth_middleware import get_current_user, CurrentUser, SECRET_KEY, ALGORITHM

router = APIRouter(
    prefix="/login",
    tags=["Authentication"]
)

# Configuration
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Pydantic models
class LoginRequest(BaseModel):
    user_id: str
    password: str

class UserDetails(BaseModel):
    user_id: int
    UserName: str
    Role: str
    facility_id: int
    
    class Config:
        orm_mode = True

class FacilityDetails(BaseModel):
    facility_id: int
    FacilityName: str
    FacilityAddress: str
    TaxNumber: str
    
    class Config:
        orm_mode = True

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user_details: UserDetails
    facility_details: FacilityDetails
    message: str

# Utility functions
def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, stored_password: str) -> bool:
    """Verify password against hash or plain text"""
    if len(stored_password) == 64 and all(c in '0123456789abcdef' for c in stored_password.lower()):
        return hash_password(plain_password) == stored_password
    else:
        return plain_password == stored_password

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def authenticate_user(db: Session, user_id: str, password: str):
    """Authenticate user by User ID and password"""
    user_id = user_id.strip()
    password = password.strip()
    
    # Try to find user by UserName
    user = db.query(UserMaster).filter(
        UserMaster.UserName == user_id
    ).first()
    
    # If not found, try case-insensitive match
    if not user:
        user = db.query(UserMaster).filter(
            UserMaster.UserName.ilike(user_id)
        ).first()
    
    # Alternative: If UserName doesn't match, try by user_id field
    if not user and user_id.isdigit():
        user = db.query(UserMaster).filter(
            UserMaster.user_id == int(user_id)
        ).first()
    
    if not user:
        return None
    
    # Verify password
    if not verify_password(password, user.Password):
        return None
    
    # Get facility details
    facility = db.query(Facility).filter(
        Facility.facility_id == user.facility_id
    ).first()
    
    if not facility:
        return None
    
    return user, facility

# API Endpoints
def _perform_login(login_data: LoginRequest, db: Session) -> LoginResponse:
    """
    HMS Login endpoint - Returns JWT token and user/facility details
    This token can be used for all protected endpoints
    """
    if not login_data.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID is required"
        )
    
    if not login_data.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required"
        )
    
    # Authenticate user
    auth_result = authenticate_user(db, login_data.user_id, login_data.password)
    
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID or Password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user, facility = auth_result
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "user_id": user.user_id,
            "facility_id": user.facility_id,
            "role": user.Role,
            "username": user.UserName
        },
        expires_delta=access_token_expires
    )
    
    welcome_message = f"Welcome to HMS, {user.UserName}! ({user.Role})"
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_details=UserDetails(
            user_id=user.user_id,
            UserName=user.UserName,
            Role=user.Role,
            facility_id=user.facility_id
        ),
        facility_details=FacilityDetails(
            facility_id=facility.facility_id,
            FacilityName=facility.FacilityName,
            FacilityAddress=facility.FacilityAddress,
            TaxNumber=facility.TaxNumber
        ),
        message=welcome_message
    )


@router.post("", response_model=LoginResponse)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    return _perform_login(login_data, db)


@router.post("/login", response_model=LoginResponse, include_in_schema=False)
def login_legacy_alias(login_data: LoginRequest, db: Session = Depends(get_db)):
    return _perform_login(login_data, db)

@router.get("/me")
def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current authenticated user's information
    Protected route - requires valid JWT token
    """
    user = db.query(UserMaster).filter(
        UserMaster.user_id == current_user.user_id
    ).first()
    
    facility = db.query(Facility).filter(
        Facility.facility_id == current_user.facility_id
    ).first()
    
    if not user or not facility:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User or facility no longer exists",
        )
    
    return {
        "user_details": UserDetails(
            user_id=user.user_id,
            UserName=user.UserName,
            Role=user.Role,
            facility_id=user.facility_id
        ),
        "facility_details": FacilityDetails(
            facility_id=facility.facility_id,
            FacilityName=facility.FacilityName,
            FacilityAddress=facility.FacilityAddress,
            TaxNumber=facility.TaxNumber
        )
    }

@router.post("/logout")
def logout(current_user: CurrentUser = Depends(get_current_user)):
    """
    Logout endpoint (client should discard the token)
    Protected route - requires valid JWT token
    """
    return {
        "success": True,
        "message": f"Successfully logged out. Goodbye, {current_user.username}!"
    }
