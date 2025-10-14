from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from database import get_db
from model import Facility
from auth_middleware import get_current_user, require_admin_role, CurrentUser

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

@router.get("/", response_model=List[FacilityResponse])
def get_all_facilities(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Facility).all()

@router.get("/{facility_id}", response_model=FacilityResponse)
def get_facility(
    facility_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    facility = db.query(Facility).filter(Facility.facility_id == facility_id).first()
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")
    return facility

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

@router.api_route("/{facility_id}", methods=["PATCH"], tags=["Facility"])
async def update_facility(
    facility_id: int,
    facility: FacilityUpdateSchema = None,
    background_tasks: BackgroundTasks = None,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    try:
        existing_facility = db.query(Facility).filter(
            Facility.facility_id == facility_id
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

@router.delete("/{facility_id}")
def delete_facility(
    facility_id: int,
    current_user: CurrentUser = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    facility = db.query(Facility).filter(Facility.facility_id == facility_id).first()
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")
    db.delete(facility)
    db.commit()
    return {"detail": "Facility deleted successfully"}