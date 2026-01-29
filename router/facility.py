from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from database import get_db
from model import Facility
from auth_middleware import get_current_user, require_admin_role, CurrentUser
import io

router = APIRouter(
    prefix="/facility",
    tags=["Facility"]
)

class FacilityBase(BaseModel):
    FacilityName: str
    FacilityAddress: str
    TaxNumber: str

class FacilityUpdateSchema(BaseModel):
    FacilityName: Optional[str] = None
    FacilityAddress: Optional[str] = None
    TaxNumber: Optional[str] = None

class FacilityResponse(FacilityBase):
    facility_id: int

    class Config:
        orm_mode = True

def successful_response(status_code: int):
    return {"status_code": status_code, "message": "Success"}

def get_notfound_exception():
    return HTTPException(status_code=404, detail="Facility not found")

def get_effective_facility_id(current_user: CurrentUser, facility_id: Optional[int]) -> int:
    """
    Determine the effective facility_id based on user role
    - Super Admin: Use provided facility_id parameter
    - Regular User: Always use facility_id from token
    """
    if current_user.is_super_admin():
        if facility_id is None:
            raise HTTPException(status_code=400, detail="facility_id is required")
        return facility_id
    else:
        # Regular user - always use facility_id from token, ignore parameter
        return current_user.facility_id

@router.get("/", response_model=List[FacilityResponse])
def get_all_facilities(
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: Optional[int] = Query(None, description="Facility ID to filter facilities"),
    db: Session = Depends(get_db)
):
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        return db.query(Facility).filter(Facility.facility_id == effective_facility_id).all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving facilities: {str(e)}")

@router.get("/detail", response_model=FacilityResponse)
def get_facility(
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        facility = db.query(Facility).filter(Facility.facility_id == effective_facility_id).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        return facility
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving facility: {str(e)}")

@router.post("/", response_model=FacilityResponse)
def create_facility(
    facility: FacilityBase,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    new_facility = Facility(**facility.dict())
    db.add(new_facility)
    db.commit()
    db.refresh(new_facility)
    return new_facility

@router.api_route("/update", methods=["PATCH"], tags=["Facility"])
async def update_facility(
    facility: FacilityUpdateSchema = None,
    background_tasks: BackgroundTasks = None,
    current_user: CurrentUser = Depends(require_admin_role),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        existing_facility = db.query(Facility).filter(
            Facility.facility_id == effective_facility_id
        ).first()
        
        if not existing_facility:
            raise get_notfound_exception()
        
        # Get only the fields that were explicitly set in the request
        update_data = facility.dict(exclude_unset=True, exclude_none=True) if facility else {}
        filtered_data = {}
        
        # Define invalid values to skip
        invalid_strings = {"", "string", "example", "test", "sample"}
        
        for k, v in update_data.items():
            if v is None:
                continue
                
            # Skip invalid string values
            if isinstance(v, str) and (v.strip().lower() in invalid_strings or v.strip() == ""):
                continue
            
            # For all fields, only update if value differs from current
            current_value = getattr(existing_facility, k, None)
            if current_value != v:
                filtered_data[k] = v
        
        if not filtered_data:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")
        
        # Update facility fields efficiently
        for key, value in filtered_data.items():
            if hasattr(existing_facility, key):
                setattr(existing_facility, key, value)

        db.commit()
        db.refresh(existing_facility)
        
        return successful_response(200)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/delete")
def delete_facility(
    current_user: CurrentUser = Depends(require_admin_role),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        facility = db.query(Facility).filter(Facility.facility_id == effective_facility_id).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        db.delete(facility)
        db.commit()
        return {"detail": "Facility deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting facility: {str(e)}")

@router.post("/logo")
async def upload_facility_logo(
    logo: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_admin_role),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    """
    Upload a logo for a facility
    Accepts image files (png, jpg, jpeg, gif, svg)
    """
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        # Validate facility exists
        facility = db.query(Facility).filter(Facility.facility_id == effective_facility_id).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        # Validate file type
        allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg"}
        file_ext = logo.filename.lower()[logo.filename.rfind("."):]
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        # Read file content
        logo_content = await logo.read()
        
        # Validate file size (max 5MB)
        if len(logo_content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size too large. Maximum 5MB allowed")
        
        # Update facility with logo
        facility.logo_filename = logo.filename
        facility.logo_blob = logo_content
        
        db.commit()
        
        return {
            "status_code": 200,
            "message": "Logo uploaded successfully",
            "filename": logo.filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error uploading logo: {str(e)}")

@router.get("/logo")
def get_facility_logo(
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    """
    Download the logo for a facility
    Returns the image file
    """
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        facility = db.query(Facility).filter(Facility.facility_id == effective_facility_id).first()
    
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        if not facility.logo_blob or not facility.logo_filename:
            raise HTTPException(status_code=404, detail="No logo found for this facility")
        
        # Determine media type from filename
        file_ext = facility.logo_filename.lower()[facility.logo_filename.rfind("."):]
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml"
        }
        
        media_type = media_type_map.get(file_ext, "application/octet-stream")
        
        # Return image as streaming response
        return StreamingResponse(
            io.BytesIO(facility.logo_blob),
            media_type=media_type,
            headers={
                "Content-Disposition": f"inline; filename={facility.logo_filename}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving logo: {str(e)}")

@router.delete("/logo")
def delete_facility_logo(
    current_user: CurrentUser = Depends(require_admin_role),
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    db: Session = Depends(get_db)
):
    """
    Delete the logo for a facility
    """
    try:
        # Get effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        facility = db.query(Facility).filter(Facility.facility_id == effective_facility_id).first()
        
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        if not facility.logo_blob:
            raise HTTPException(status_code=404, detail="No logo found for this facility")
        
        facility.logo_filename = None
        facility.logo_blob = None
        
        db.commit()
        
        return {
            "status_code": 200,
            "message": "Logo deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting logo: {str(e)}")