"""
usermaster.py - Fixed Version with Proper Super Admin Controls
REPLACE your existing usermaster.py with this entire file
Location: router/usermaster.py

Key Changes:
- Only SUPER ADMINS can access other facilities
- Regular admins can only manage their own facility
- Regular users have read-only access to their facility
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from database import get_db
from model import UserMaster

# Import authentication dependencies
from auth_middleware import (
    get_current_user, 
    require_admin_role,
    CurrentUser
)

router = APIRouter(
    prefix="/usermaster",
    tags=["UserMaster"]
)

# ============================================
# Pydantic Models
# ============================================

class UserMasterBase(BaseModel):
    UserName: str
    Password: str
    Role: str
    facility_id: int

class UserMasterCreate(BaseModel):
    UserName: str
    Password: str
    Role: str
    facility_id: Optional[int] = None  # Super admin can specify, others use their own

class UserMasterUpdate(BaseModel):
    UserName: Optional[str] = None
    Password: Optional[str] = None
    Role: Optional[str] = None
    
    class Config:
        validate_assignment = True

class UserMasterResponse(BaseModel):
    user_id: int
    UserName: str
    Role: str
    facility_id: int
    
    class Config:
        orm_mode = True


# ============================================
# PROTECTED ENDPOINTS
# ============================================

@router.get("/", response_model=List[UserMasterResponse])
def get_all_users_in_facility(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all users in the current user's facility
    Protected: Requires authentication
    - Regular users: Only their facility
    - Regular admins: Only their facility
    - Super admins: Only their facility (use /all to see all facilities)
    """
    users = db.query(UserMaster).filter(
        UserMaster.facility_id == current_user.facility_id
    ).all()
    return users


@router.get("/all", response_model=List[UserMasterResponse])
def get_all_users_all_facilities(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all users from ALL facilities
    🔒 SUPER ADMIN ONLY
    """
    if not current_user.is_super_admin():
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only super admins can view users from all facilities"
        )
    
    users = db.query(UserMaster).all()
    return users


@router.get("/facility/{facility_id}", response_model=List[UserMasterResponse])
def get_users_by_facility(
    facility_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all users in a specific facility
    Protected:
    - Regular users: Only own facility
    - Regular admins: Only own facility
    - Super admins: Any facility ✅
    """
    # Only super admins can access other facilities
    if not current_user.is_super_admin() and facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only super admins can view users from other facilities"
        )
    
    users = db.query(UserMaster).filter(
        UserMaster.facility_id == facility_id
    ).all()
    return users


@router.post("/", response_model=UserMasterResponse)
def create_user(
    user: UserMasterCreate,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Create a new user
    Protected:
    - Regular admins: Can only create users in their own facility
    - Super admins: Can create users in any facility
    """
    # Determine which facility to create user in
    if user.facility_id is not None:
        # Super admin can specify facility
        if not current_user.is_super_admin():
            raise HTTPException(
                status_code=403,
                detail="Access denied. Only super admins can create users in other facilities"
            )
        target_facility_id = user.facility_id
    else:
        # Use current user's facility
        target_facility_id = current_user.facility_id
    
    # Regular admins can only create in their own facility
    if not current_user.is_super_admin() and target_facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only create users in your own facility"
        )
    
    # Check if username already exists in target facility
    existing = db.query(UserMaster).filter(
        UserMaster.UserName == user.UserName,
        UserMaster.facility_id == target_facility_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"User with username '{user.UserName}' already exists in facility {target_facility_id}"
        )
    
    # Create new user
    new_user = UserMaster(
        UserName=user.UserName,
        Password=user.Password,
        Role=user.Role,
        facility_id=target_facility_id
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/user/{user_id}", response_model=UserMasterResponse)
def get_user_by_id(
    user_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific user by ID
    Protected: 
    - Regular users/admins: Only from own facility
    - Super admins: From any facility
    """
    user = db.query(UserMaster).filter(
        UserMaster.user_id == user_id
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    # Check facility access
    if not current_user.is_super_admin() and user.facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only view users from your own facility"
        )
    
    return user


@router.get("/facility/{facility_id}/user/{user_id}", response_model=UserMasterResponse)
def get_user_by_facility_and_user_id(
    facility_id: int,
    user_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific user by facility and user ID
    Protected:
    - Regular users/admins: Only own facility
    - Super admins: Any facility ✅
    """
    # Only super admins can access other facilities
    if not current_user.is_super_admin() and facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only super admins can view users from other facilities"
        )
    
    user = db.query(UserMaster).filter(
        UserMaster.facility_id == facility_id,
        UserMaster.user_id == user_id
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found in the specified facility"
        )
    
    return user


@router.put("/user/{user_id}", response_model=UserMasterResponse)
def update_user(
    user_id: int,
    user_update: UserMasterUpdate,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Update a user's information
    Protected:
    - Regular admins: Only users in own facility
    - Super admins: Users in any facility ✅
    """
    existing_user = db.query(UserMaster).filter(
        UserMaster.user_id == user_id
    ).first()
    
    if not existing_user:
        raise HTTPException(
            status_code=404,
            detail=f"User with ID {user_id} not found"
        )
    
    # Check facility access
    if not current_user.is_super_admin() and existing_user.facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only update users in your own facility"
        )
    
    # Only update fields that are provided and not None or empty
    update_data = user_update.dict(exclude_unset=True, exclude_none=True)
    
    # Filter out empty strings or placeholder values
    filtered_data = {}
    for key, value in update_data.items():
        if value is not None and value != "" and value != "string":
            filtered_data[key] = value
    
    if not filtered_data:
        raise HTTPException(
            status_code=400,
            detail="No valid fields provided for update"
        )
    
    # Prevent users from updating their own account to avoid privilege escalation
    if existing_user.user_id == current_user.user_id and 'Role' in filtered_data:
        raise HTTPException(
            status_code=403,
            detail="You cannot change your own role"
        )
    
    # Update the user
    for key, value in filtered_data.items():
        setattr(existing_user, key, value)
    
    db.commit()
    db.refresh(existing_user)
    return existing_user


@router.put("/facility/{facility_id}/user/{user_id}", response_model=UserMasterResponse)
def update_user_by_facility_and_user_id(
    facility_id: int,
    user_id: int,
    user_update: UserMasterUpdate,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Update a user by facility and user ID
    Protected:
    - Regular admins: Only own facility
    - Super admins: Any facility ✅
    """
    # Only super admins can update users in other facilities
    if not current_user.is_super_admin() and facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only super admins can update users in other facilities"
        )
    
    existing_user = db.query(UserMaster).filter(
        UserMaster.facility_id == facility_id,
        UserMaster.user_id == user_id
    ).first()
    
    if not existing_user:
        raise HTTPException(
            status_code=404,
            detail=f"User with ID {user_id} not found in facility {facility_id}"
        )
    
    # Only update fields that are provided
    update_data = user_update.dict(exclude_unset=True, exclude_none=True)
    filtered_data = {k: v for k, v in update_data.items() 
                     if v is not None and v != "" and v != "string"}
    
    if not filtered_data:
        raise HTTPException(
            status_code=400,
            detail="No valid fields provided for update"
        )
    
    # Prevent self-role modification
    if existing_user.user_id == current_user.user_id and 'Role' in filtered_data:
        raise HTTPException(
            status_code=403,
            detail="You cannot change your own role"
        )
    
    for key, value in filtered_data.items():
        setattr(existing_user, key, value)
    
    db.commit()
    db.refresh(existing_user)
    return existing_user


@router.delete("/user/{user_id}")
def delete_user(
    user_id: int,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Delete a user
    Protected:
    - Regular admins: Only users in own facility
    - Super admins: Users in any facility ✅
    """
    user = db.query(UserMaster).filter(
        UserMaster.user_id == user_id
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User with ID {user_id} not found"
        )
    
    # Check facility access
    if not current_user.is_super_admin() and user.facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only delete users from your own facility"
        )
    
    # Prevent self-deletion
    if user.user_id == current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot delete your own account"
        )
    
    db.delete(user)
    db.commit()
    
    return {
        "success": True,
        "detail": f"User {user_id} deleted successfully"
    }


@router.delete("/facility/{facility_id}/user/{user_id}")
def delete_user_by_facility_and_user_id(
    facility_id: int,
    user_id: int,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Delete a user by facility and user ID
    Protected:
    - Regular admins: Only own facility
    - Super admins: Any facility ✅
    """
    # Only super admins can delete users from other facilities
    if not current_user.is_super_admin() and facility_id != current_user.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only super admins can delete users from other facilities"
        )
    
    user = db.query(UserMaster).filter(
        UserMaster.facility_id == facility_id,
        UserMaster.user_id == user_id
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User with ID {user_id} not found in facility {facility_id}"
        )
    
    # Prevent self-deletion
    if user.user_id == current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot delete your own account"
        )
    
    db.delete(user)
    db.commit()
    
    return {
        "success": True,
        "detail": f"User {user_id} deleted successfully from facility {facility_id}"
    }