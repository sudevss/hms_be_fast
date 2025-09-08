from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt
import secrets
import hashlib

from database import get_db
from model import UserMaster, Facility

router = APIRouter(
    prefix="/login",
    tags=["Authentication"]
)

# Configuration
SECRET_KEY = secrets.token_urlsafe(32)  # In production, use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Security scheme
security = HTTPBearer()

# Pydantic models
class LoginRequest(BaseModel):
    user_id: str  # Changed from username to user_id to match the UI
    password: str

class UserDetails(BaseModel):
    UserID: int
    UserName: str
    Role: str
    FacilityID: int
    
    class Config:
        orm_mode = True

class FacilityDetails(BaseModel):
    FacilityID: int
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
    message: str  # Added welcome message

class TokenData(BaseModel):
    user_id: Optional[int] = None
    facility_id: Optional[int] = None

class CurrentUser:
    def __init__(self, user_id: int, username: str, role: str, facility_id: int):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.facility_id = facility_id

# Utility functions
def hash_password(password: str) -> str:
    """Hash password using SHA-256 (replace with bcrypt in production)"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, stored_password: str) -> bool:
    """Verify password against hash or plain text (for transition period)"""
    # Check if password is already hashed (64 characters for SHA-256)
    if len(stored_password) == 64 and all(c in '0123456789abcdef' for c in stored_password.lower()):
        # Compare with hashed version
        return hash_password(plain_password) == stored_password
    else:
        # Compare plain text (for backward compatibility)
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

def verify_token(token: str):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        facility_id: int = payload.get("facility_id")
        
        if user_id is None or facility_id is None:
            return None
        
        return TokenData(user_id=user_id, facility_id=facility_id)
    except jwt.PyJWTError:
        return None

def authenticate_user(db: Session, user_id: str, password: str):
    """Authenticate user by User ID and password"""
    # Strip whitespace
    user_id = user_id.strip()
    password = password.strip()
    
    print(f"DEBUG: Attempting to authenticate user_id: '{user_id}'")
    
    # Try to find user by UserName (which seems to store the User ID based on your image)
    user = db.query(UserMaster).filter(
        UserMaster.UserName == user_id
    ).first()
    
    # If not found, try case-insensitive match
    if not user:
        user = db.query(UserMaster).filter(
            UserMaster.UserName.ilike(user_id)
        ).first()
    
    # Alternative: If UserName doesn't match User ID format, try by UserID field
    if not user and user_id.isdigit():
        user = db.query(UserMaster).filter(
            UserMaster.UserID == int(user_id)
        ).first()
    
    if not user:
        print(f"DEBUG: User with ID '{user_id}' not found in database")
        return None
    
    print(f"DEBUG: Found user '{user.UserName}' (ID: {user.UserID}) with password '{user.Password}'")
    print(f"DEBUG: Comparing with input password '{password}'")
    
    # Verify password
    if not verify_password(password, user.Password):
        print(f"DEBUG: Password verification failed")
        return None
    
    print(f"DEBUG: Password verification successful")
    
    # Get facility details
    facility = db.query(Facility).filter(
        Facility.FacilityID == user.FacilityID
    ).first()
    
    if not facility:
        print(f"DEBUG: Facility with ID {user.FacilityID} not found")
        return None
    
    return user, facility

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> CurrentUser:
    """
    Dependency to get current authenticated user from JWT token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode JWT token
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        facility_id: int = payload.get("facility_id")
        username: str = payload.get("username")
        role: str = payload.get("role")
        
        if user_id is None or facility_id is None:
            raise credentials_exception
            
    except jwt.PyJWTError:
        raise credentials_exception
    
    # Verify user still exists in database
    user = db.query(UserMaster).filter(
        UserMaster.UserID == user_id,
        UserMaster.FacilityID == facility_id
    ).first()
    
    if user is None:
        raise credentials_exception
    
    return CurrentUser(
        user_id=user_id,
        username=username,
        role=role,
        facility_id=facility_id
    )

# API Endpoints
@router.post("/login", response_model=LoginResponse)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """
    HMS Login endpoint that authenticates user with User ID and password
    Returns JWT token and user/facility details with welcome message
    """
    # Validate input
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
            "user_id": user.UserID,
            "facility_id": user.FacilityID,
            "role": user.Role,
            "username": user.UserName
        },
        expires_delta=access_token_expires
    )
    
    # Create welcome message
    welcome_message = f"Welcome to HMS, {user.UserName}! ({user.Role})"
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # in seconds
        user_details=UserDetails(
            UserID=user.UserID,
            UserName=user.UserName,
            Role=user.Role,
            FacilityID=user.FacilityID
        ),
        facility_details=FacilityDetails(
            FacilityID=facility.FacilityID,
            FacilityName=facility.FacilityName,
            FacilityAddress=facility.FacilityAddress,
            TaxNumber=facility.TaxNumber
        ),
        message=welcome_message
    )

# @router.get("/me")
# def get_current_user_info(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
#     """
#     Get current authenticated user's information
#     """
#     # Get fresh user and facility details from database
#     user = db.query(UserMaster).filter(UserMaster.UserID == current_user.user_id).first()
#     facility = db.query(Facility).filter(Facility.FacilityID == current_user.facility_id).first()
    
#     if not user or not facility:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="User or facility no longer exists",
#         )
    
#     return {
#         "user_details": UserDetails(
#             UserID=user.UserID,
#             UserName=user.UserName,
#             Role=user.Role,
#             FacilityID=user.FacilityID
#         ),
#         "facility_details": FacilityDetails(
#             FacilityID=facility.FacilityID,
#             FacilityName=facility.FacilityName,
#             FacilityAddress=facility.FacilityAddress,
#             TaxNumber=facility.TaxNumber
#         )
#     }

# @router.post("/logout")
# def logout(current_user: CurrentUser = Depends(get_current_user)):
#     """
#     Logout endpoint (client should discard the token)
#     """
#     return {
#         "success": True,
#         "message": f"Successfully logged out. Goodbye, {current_user.username}!"
#     }