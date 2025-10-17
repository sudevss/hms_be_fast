"""
admin.py - Admin Router for Super Admin Management - SECURED VERSION
Location: router/admin.py

This manages super admin accounts (with facility association)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt

from database import get_db
from model import Admin, Facility
from auth_middleware import get_current_user, require_admin_role, CurrentUser
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_HOURS  # ← Import from shared config

router = APIRouter(
    prefix="/admin",
    tags=["Super Admin Management"]
)

# Password hashing
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================
# Pydantic Models
# ============================================

class AdminCreate(BaseModel):
    username: str
    password: str
    facility_id: Optional[int] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "username": "superadmin",
                "password": "securepassword123",
                "facility_id": 1
            }
        }

class AdminLogin(BaseModel):
    username: str
    password: str

class AdminResponse(BaseModel):
    username: str
    facility_id: Optional[int] = None
    
    class Config:
        orm_mode = True
        from_attributes = True

class AdminDetailedResponse(BaseModel):
    username: str
    facility_id: int
    facility_name: Optional[str] = None
    facility_address: Optional[str] = None

class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    admin_details: dict
    message: str

class PasswordChange(BaseModel):
    new_password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "new_password": "newpassword123"
            }
        }

# ============================================
# Utility Functions
# ============================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash"""
    return bcrypt_context.verify(plain_password, hashed_password)

def create_admin_token(admin_username: str, facility_id: int, expires_delta: Optional[timedelta] = None):
    """Create JWT token for admin"""
    to_encode = {
        "sub": admin_username,
        "username": admin_username,
        "facility_id": facility_id,
        "role": "super_admin"
    }
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=8)  # Increased from 30 minutes to 8 hours
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def validate_password_strength(password: str) -> bool:
    """Validate password meets minimum requirements"""
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Optional: Add more complexity requirements
    # has_upper = any(c.isupper() for c in password)
    # has_lower = any(c.islower() for c in password)
    # has_digit = any(c.isdigit() for c in password)
    
    return True

# ============================================
# PUBLIC ENDPOINTS (No authentication required)
# ============================================

@router.post("/login", response_model=AdminTokenResponse)
def admin_login(
    login_data: AdminLogin,
    db: Session = Depends(get_db)
):
    """
    Super admin login endpoint - Returns JWT token
    PUBLIC ENDPOINT - No authentication required
    """
    if not login_data.username or not login_data.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required"
        )
    
    # Find admin by username (primary key)
    admin = db.query(Admin).filter(
        Admin.username == login_data.username.strip()
    ).first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(login_data.password, admin.hashed_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get facility details
    facility = db.query(Facility).filter(
        Facility.facility_id == admin.facility_id
    ).first()
    
    # Create access token with longer expiration
    access_token_expires = timedelta(hours=8)  # Increased from 30 minutes
    access_token = create_admin_token(
        admin_username=admin.username,
        facility_id=admin.facility_id,
        expires_delta=access_token_expires
    )
    
    return AdminTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=8 * 60 * 60,  # 8 hours in seconds
        admin_details={
            "username": admin.username,
            "facility_id": admin.facility_id,
            "facility_name": facility.FacilityName if facility else None,
            "role": "super_admin"
        },
        message=f"Welcome Super Admin {admin.username}!"
    )

# ============================================
# PROTECTED ADMIN MANAGEMENT ENDPOINTS
# All endpoints below require super admin authentication
# ============================================

@router.post("/register", response_model=AdminResponse, status_code=status.HTTP_201_CREATED)
def create_super_admin(
    admin_data: AdminCreate,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Create a new super admin account
    🔒 PROTECTED - Requires super admin authentication
    
    Note: Admin username is the primary key, must be unique
    """
    # Validate input
    if not admin_data.username or not admin_data.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is required"
        )
    
    # Validate password strength
    validate_password_strength(admin_data.password)
    
    # Check if facility exists (only if facility_id is provided)
    if admin_data.facility_id:
        facility = db.query(Facility).filter(
            Facility.facility_id == admin_data.facility_id
        ).first()
        
        if not facility:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Facility with ID {admin_data.facility_id} not found"
            )
    
    # Check if admin already exists (username is primary key)
    existing_admin = db.query(Admin).filter(
        Admin.username == admin_data.username.strip()
    ).first()
    
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Admin with username '{admin_data.username}' already exists"
        )
    
    try:
        # Create new admin
        new_admin = Admin(
            username=admin_data.username.strip(),
            hashed_pass=hash_password(admin_data.password)
        )
        
        # Only set facility_id if provided and column exists
        if admin_data.facility_id and hasattr(Admin, 'facility_id'):
            new_admin.facility_id = admin_data.facility_id
        
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
        
        return AdminResponse(
            username=new_admin.username,
            facility_id=getattr(new_admin, 'facility_id', None)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create admin: {str(e)}"
        )

@router.get("/list", response_model=list[AdminDetailedResponse])
def list_all_admins(
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    List all super admins with their facility details
    🔒 PROTECTED - Requires super admin authentication
    """
    admins = db.query(Admin).all()
    
    result = []
    for admin in admins:
        facility = db.query(Facility).filter(
            Facility.facility_id == admin.facility_id
        ).first()
        
        result.append(AdminDetailedResponse(
            username=admin.username,
            facility_id=admin.facility_id,
            facility_name=facility.FacilityName if facility else None,
            facility_address=facility.FacilityAddress if facility else None
        ))
    
    return result

@router.get("/facility/{facility_id}", response_model=list[AdminResponse])
def get_admins_by_facility(
    facility_id: int,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Get all admins for a specific facility
    🔒 PROTECTED - Requires super admin authentication
    """
    admins = db.query(Admin).filter(
        Admin.facility_id == facility_id
    ).all()
    
    if not admins:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No admins found for facility {facility_id}"
        )
    
    return [AdminResponse(username=admin.username, facility_id=admin.facility_id) 
            for admin in admins]

@router.get("/{username}", response_model=AdminDetailedResponse)
def get_admin_by_username(
    username: str,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Get a specific admin by username (primary key)
    🔒 PROTECTED - Requires super admin authentication
    """
    admin = db.query(Admin).filter(Admin.username == username).first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with username '{username}' not found"
        )
    
    facility = db.query(Facility).filter(
        Facility.facility_id == admin.facility_id
    ).first()
    
    return AdminDetailedResponse(
        username=admin.username,
        facility_id=admin.facility_id,
        facility_name=facility.FacilityName if facility else None,
        facility_address=facility.FacilityAddress if facility else None
    )

@router.put("/{username}/password")
def change_admin_password(
    username: str,
    password_data: PasswordChange,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Change super admin password
    🔒 PROTECTED - Requires super admin authentication
    """
    # Validate password strength
    validate_password_strength(password_data.new_password)
    
    admin = db.query(Admin).filter(Admin.username == username).first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with username '{username}' not found"
        )
    
    try:
        # Update password
        admin.hashed_pass = hash_password(password_data.new_password)
        db.commit()
        
        return {
            "success": True,
            "detail": f"Password updated successfully for admin '{username}'"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update password: {str(e)}"
        )

@router.put("/{username}/facility")
def change_admin_facility(
    username: str,
    new_facility_id: int,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Change admin's facility assignment
    🔒 PROTECTED - Requires super admin authentication
    """
    admin = db.query(Admin).filter(Admin.username == username).first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with username '{username}' not found"
        )
    
    # Check if new facility exists
    facility = db.query(Facility).filter(
        Facility.facility_id == new_facility_id
    ).first()
    
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Facility with ID {new_facility_id} not found"
        )
    
    try:
        old_facility_id = admin.facility_id
        admin.facility_id = new_facility_id
        db.commit()
        
        return {
            "success": True,
            "detail": f"Admin '{username}' moved from facility {old_facility_id} to {new_facility_id}",
            "new_facility": facility.FacilityName
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update facility: {str(e)}"
        )

@router.delete("/{username}")
def delete_admin(
    username: str,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Delete a super admin account
    🔒 PROTECTED - Requires super admin authentication
    
    Note: Username is the primary key
    """
    admin = db.query(Admin).filter(Admin.username == username).first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with username '{username}' not found"
        )
    
    # Prevent self-deletion
    if admin.username == current_user.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own admin account"
        )
    
    try:
        facility_id = admin.facility_id
        db.delete(admin)
        db.commit()
        
        return {
            "success": True,
            "detail": f"Admin '{username}' (Facility: {facility_id}) deleted successfully"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete admin: {str(e)}"
        )

@router.get("/count/total")
def get_admin_count(
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Get total number of admins
    🔒 PROTECTED - Requires super admin authentication
    """
    count = db.query(Admin).count()
    facilities_with_admins = db.query(Admin.facility_id).distinct().count()
    
    return {
        "total_admins": count,
        "facilities_with_admins": facilities_with_admins,
        "setup_needed": count == 0
    }

# ============================================
# INITIAL SETUP ENDPOINT (Public - Only works if no admins exist)
# ============================================

@router.post("/initial-setup", response_model=AdminResponse, status_code=status.HTTP_201_CREATED)
def initial_admin_setup(
    admin_data: AdminCreate,
    db: Session = Depends(get_db)
):
    """
    Create the FIRST super admin account (Initial Setup)
    🔓 PUBLIC - Only works when NO admins exist in the system
    
    After the first admin is created, use /admin/register (which requires authentication)
    """
    # Check if any admins already exist
    admin_count = db.query(Admin).count()
    
    if admin_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Initial setup already completed. Use /admin/register endpoint with authentication."
        )
    
    # Validate input
    if not admin_data.username or not admin_data.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is required"
        )
    
    # Validate password strength
    validate_password_strength(admin_data.password)
    
    # Check if facility exists (only if facility_id is provided)
    if admin_data.facility_id:
        facility = db.query(Facility).filter(
            Facility.facility_id == admin_data.facility_id
        ).first()
        
        if not facility:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Facility with ID {admin_data.facility_id} not found"
            )
    
    try:
        # Create first admin
        new_admin = Admin(
            username=admin_data.username.strip(),
            hashed_pass=hash_password(admin_data.password)
        )
        
        if admin_data.facility_id and hasattr(Admin, 'facility_id'):
            new_admin.facility_id = admin_data.facility_id
        
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
        
        return AdminResponse(
            username=new_admin.username,
            facility_id=getattr(new_admin, 'facility_id', None)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create initial admin: {str(e)}"
        )