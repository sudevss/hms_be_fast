"""
auth_middleware.py - Authentication Middleware (With Receptionist Role)
Place this file in your project root directory (same level as main.py)

This file provides centralized authentication dependencies for your FastAPI application.
SUPPORTS BOTH USER AND ADMIN TOKENS!
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import datetime
from typing import Optional
import base64

from database import get_db
from model import UserMaster, Admin, Facility
from config import SECRET_KEY, ALGORITHM

# Security scheme
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)  # For optional authentication


class CurrentUser:
    """Represents the currently authenticated user (includes both users and admins)"""
    def __init__(self, user_id: int, username: str, role: str, facility_id: int, user_type: str = "user"):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.facility_id = facility_id
        self.user_type = user_type  # "user" or "super_admin"
        
    def is_admin(self) -> bool:
        """Check if user has admin role"""
        return self.role.lower() in ['admin', 'administrator', 'superadmin'] or self.user_type == "super_admin"
    
    def is_super_admin(self) -> bool:
        """Check if user is a super admin"""
        return self.user_type == "super_admin"
    
    def is_doctor(self) -> bool:
        """Check if user is a doctor"""
        return self.role.lower() == 'doctor'
    
    def is_nurse(self) -> bool:
        """Check if user is a nurse"""
        return self.role.lower() == 'nurse'
    
    def is_receptionist(self) -> bool:
        """Check if user is a receptionist"""
        return self.role.lower() == 'receptionist'
    
    def has_role(self, role: str) -> bool:
        """Check if user has specific role"""
        return self.role.lower() == role.lower()


class CurrentAdmin:
    """Represents the currently authenticated admin"""
    def __init__(self, username: str, facility_id: Optional[int] = None):
        self.username = username
        self.facility_id = facility_id


def verify_jwt_token(token: str, db: Session):
    """
    Verify JWT token and return user information
    HANDLES BOTH USER TOKENS AND ADMIN TOKENS!
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Clean the token - remove any whitespace or special characters
        token = token.strip()
        
        # Check if token looks valid (basic validation)
        if not token or len(token) < 10:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Try to decode the token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except Exception as decode_error:
            # More specific error message
            error_msg = str(decode_error)
            if "Invalid crypto padding" in error_msg or "codec can't decode" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token is corrupted or invalid. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            elif "Signature has expired" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Could not validate token: {error_msg}",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        
        # Check token expiration
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired. Please login again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check if it's an ADMIN token (from admin.py login)
        token_type = payload.get("type")
        if token_type == "super_admin":
            username = payload.get("sub") or payload.get("username")
            facility_id = payload.get("facility_id", 0)
            
            if username is None:
                raise credentials_exception
            
            # Verify admin exists
            admin = db.query(Admin).filter(Admin.username == username).first()
            if admin is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Admin account not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return CurrentUser(
                user_id=0,  # Admins don't have user_id
                username=username,
                role="SuperAdmin",
                facility_id=facility_id if facility_id else 0,
                user_type="super_admin"
            )
        
        # Otherwise it's a REGULAR USER token (from login.py)
        else:
            user_id = payload.get("user_id")
            facility_id = payload.get("facility_id")
            username = payload.get("username")
            role = payload.get("role")
            
            if user_id is None or facility_id is None:
                raise credentials_exception
            
            # Verify user still exists in database
            user = db.query(UserMaster).filter(
                UserMaster.user_id == user_id,
                UserMaster.facility_id == facility_id
            ).first()
            
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return CurrentUser(
                user_id=user_id,
                username=username,
                role=role,
                facility_id=facility_id,
                user_type="user"
            )
            
    except HTTPException:
        raise
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_admin_token(token: str, db: Session):
    """
    Verify admin JWT token
    This works for tokens generated by admin.py
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Clean the token
        token = token.strip()
        
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        
        # Check token expiration
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if username is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
    
    # Verify admin still exists in database
    admin = db.query(Admin).filter(Admin.username == username).first()
    
    if admin is None:
        raise credentials_exception
    
    return CurrentAdmin(
        username=username,
        facility_id=admin.facility_id
    )


# ============================================
# DEPENDENCY FUNCTIONS (Use these in your routes)
# ============================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> CurrentUser:
    """
    Dependency to get current authenticated user (works with both user and admin tokens!)
    Use this in routes that require authentication
    
    Example:
        @router.get("/protected")
        def protected_route(current_user: CurrentUser = Depends(get_current_user)):
            return {"message": f"Hello {current_user.username}"}
    """
    return verify_jwt_token(credentials.credentials, db)


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> CurrentAdmin:
    """
    Dependency to get current authenticated admin
    Use this in routes that require admin authentication
    
    Example:
        @router.get("/admin-only")
        def admin_route(current_admin: CurrentAdmin = Depends(get_current_admin)):
            return {"message": f"Hello admin {current_admin.username}"}
    """
    return verify_admin_token(credentials.credentials, db)


def require_roles(*allowed_roles: str):
    """
    Dependency factory to require specific roles
    Use this to restrict routes to specific user roles
    
    Example:
        @router.get("/doctors-only")
        def doctor_route(current_user: CurrentUser = Depends(require_roles("doctor"))):
            return {"message": "Doctors only area"}
            
        @router.get("/staff-only")
        def staff_route(current_user: CurrentUser = Depends(require_roles("doctor", "nurse", "receptionist"))):
            return {"message": "Staff area"}
    """
    def role_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(current_user.has_role(role) for role in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker


def require_admin_role(
    current_user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    """
    Dependency to require admin role (accepts both super admins and users with admin role)
    Use this for routes that need admin privileges
    
    Example:
        @router.delete("/users/{user_id}")
        def delete_user(user_id: int, current_user: CurrentUser = Depends(require_admin_role)):
            # Only users with admin role can access this
            pass
    """
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


def require_same_facility(
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Dependency factory to ensure user can only access their facility's data
    
    Example:
        @router.get("/patients/{patient_id}")
        def get_patient(
            patient_id: int,
            current_user: CurrentUser = Depends(require_same_facility),
            db: Session = Depends(get_db)
        ):
            # Verify patient belongs to same facility
            patient = db.query(Patient).filter(
                Patient.id == patient_id,
                Patient.facility_id == current_user.facility_id
            ).first()
            if not patient:
                raise HTTPException(404, "Patient not found")
            return patient
    """
    return current_user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
) -> Optional[CurrentUser]:
    """
    Dependency to get current user if token is provided, None otherwise
    Use this for routes that work differently for authenticated vs anonymous users
    
    Example:
        @router.get("/public-data")
        def public_data(current_user: Optional[CurrentUser] = Depends(get_optional_user)):
            if current_user:
                return {"message": f"Hello {current_user.username}", "premium_data": True}
            return {"message": "Hello guest", "premium_data": False}
    """
    if credentials is None:
        return None
    
    try:
        return verify_jwt_token(credentials.credentials, db)
    except HTTPException:
        return None