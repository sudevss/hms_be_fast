from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt
import secrets

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
    user_id: int
    facility_id: int

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

def authenticate_user(db: Session, user_id: int, facility_id: int):
    """Authenticate user by user_id and facility_id"""
    user = db.query(UserMaster).filter(
        UserMaster.UserID == user_id,
        UserMaster.FacilityID == facility_id
    ).first()
    
    if not user:
        return None
    
    # Get facility details
    facility = db.query(Facility).filter(
        Facility.FacilityID == facility_id
    ).first()
    
    if not facility:
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
    Login endpoint that authenticates user with user_id and facility_id
    Returns JWT token and user/facility details
    """
    # Authenticate user
    auth_result = authenticate_user(db, login_data.user_id, login_data.facility_id)
    
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID or facility ID combination",
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
        )
    )

@router.get("/verify-token")
def verify_user_token(token: str, db: Session = Depends(get_db)):
    """
    Verify if the provided token is valid and return user info
    """
    token_data = verify_token(token)
    
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user and facility details
    auth_result = authenticate_user(db, token_data.user_id, token_data.facility_id)
    
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User or facility no longer exists",
        )
    
    user, facility = auth_result
    
    return {
        "valid": True,
        "user_details": UserDetails(
            UserID=user.UserID,
            UserName=user.UserName,
            Role=user.Role,
            FacilityID=user.FacilityID
        ),
        "facility_details": FacilityDetails(
            FacilityID=facility.FacilityID,
            FacilityName=facility.FacilityName,
            FacilityAddress=facility.FacilityAddress,
            TaxNumber=facility.TaxNumber
        )
    }

@router.post("/refresh-token")
def refresh_token(current_token: str, db: Session = Depends(get_db)):
    """
    Refresh the access token
    """
    token_data = verify_token(current_token)
    
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify user still exists
    auth_result = authenticate_user(db, token_data.user_id, token_data.facility_id)
    
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User or facility no longer exists",
        )
    
    user, facility = auth_result
    
    # Create new access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={
            "user_id": user.UserID,
            "facility_id": user.FacilityID,
            "role": user.Role,
            "username": user.UserName
        },
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }

@router.get("/me")
def get_current_user_info(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get current authenticated user's information
    """
    # Get fresh user and facility details from database
    auth_result = authenticate_user(db, current_user.user_id, current_user.facility_id)
    
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User or facility no longer exists",
        )
    
    user, facility = auth_result
    
    return {
        "user_details": UserDetails(
            UserID=user.UserID,
            UserName=user.UserName,
            Role=user.Role,
            FacilityID=user.FacilityID
        ),
        "facility_details": FacilityDetails(
            FacilityID=facility.FacilityID,
            FacilityName=facility.FacilityName,
            FacilityAddress=facility.FacilityAddress,
            TaxNumber=facility.TaxNumber
            
        )
    }