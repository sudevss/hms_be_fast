from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, validator
from database import get_db
from model import SlotLookup, Facility
from datetime import time

router = APIRouter(
    prefix="/slot_lookup",
    tags=["SlotLookup"]
)

# ------------------- SCHEMAS -------------------

class SlotCreateSchema(BaseModel):
    SlotSize: str  # Should be "30" for 30-minute slots to match dashboard expectations
    SlotStartTime: time   
    SlotEndTime: time    
    FacilityID: int
    
    @validator('SlotSize')
    def validate_slot_size(cls, v):
        """Validate slot size format - should be numeric string for minutes"""
        if not v.isdigit():
            raise ValueError('SlotSize should be a numeric string representing minutes (e.g., "30")')
        slot_minutes = int(v)
        if slot_minutes not in [15, 30, 45, 60]:  # Common slot sizes
            raise ValueError('SlotSize should be one of: 15, 30, 45, 60 minutes')
        return v
    
    @validator('SlotEndTime')
    def validate_time_range(cls, v, values):
        """Ensure end time is after start time"""
        if 'SlotStartTime' in values and v <= values['SlotStartTime']:
            raise ValueError('SlotEndTime must be after SlotStartTime')
        return v

class SlotUpdateSchema(BaseModel):
    SlotSize: Optional[str] = None
    SlotStartTime: Optional[time] = None 
    SlotEndTime: Optional[time] = None
    
    @validator('SlotSize')
    def validate_slot_size(cls, v):
        if v is not None:
            if not v.isdigit():
                raise ValueError('SlotSize should be a numeric string representing minutes')
            if int(v) not in [15, 30, 45, 60]:
                raise ValueError('SlotSize should be one of: 15, 30, 45, 60 minutes')
        return v

class SlotLookupResponse(BaseModel):
    SlotID: int
    SlotSize: str
    SlotStartTime: time   
    SlotEndTime: time    
    FacilityID: int
    
    class Config:
        from_attributes = True  # Updated for Pydantic v2 (was orm_mode)

# ------------------- HELPER FUNCTIONS -------------------

def validate_facility_exists(facility_id: int, db: Session):
    """Check if facility exists"""
    facility = db.query(Facility).filter(Facility.FacilityID == facility_id).first()
    if not facility:
        raise HTTPException(status_code=404, detail=f"Facility with ID {facility_id} not found")
    return facility

def check_slot_overlap(slot_data: dict, db: Session, exclude_slot_id: Optional[int] = None):
    """Check for overlapping slots in the same facility"""
    query = db.query(SlotLookup).filter(
        SlotLookup.FacilityID == slot_data['FacilityID'],
        SlotLookup.SlotStartTime < slot_data['SlotEndTime'],
        SlotLookup.SlotEndTime > slot_data['SlotStartTime']
    )
    
    if exclude_slot_id:
        query = query.filter(SlotLookup.SlotID != exclude_slot_id)
    
    overlapping = query.first()
    if overlapping:
        raise HTTPException(
            status_code=400, 
            detail=f"Slot overlaps with existing slot {overlapping.SlotID} "
                   f"({overlapping.SlotStartTime}-{overlapping.SlotEndTime})"
        )

# ------------------- ENDPOINTS -------------------

@router.get("/", response_model=List[SlotLookupResponse])
def get_all_slots(
    facility_id: Optional[int] = Query(None, description="Filter by facility ID"), 
    slot_size: Optional[str] = Query(None, description="Filter by slot size (e.g., '30')"),
    db: Session = Depends(get_db)
):
    """Get all slots with optional filtering"""
    query = db.query(SlotLookup)
    
    if facility_id is not None:
        validate_facility_exists(facility_id, db)
        query = query.filter(SlotLookup.FacilityID == facility_id)
    
    if slot_size is not None:
        query = query.filter(SlotLookup.SlotSize == slot_size)
    
    return query.order_by(SlotLookup.SlotStartTime).all()

# @router.get("/facility/{facility_id}/30min", response_model=List[SlotLookupResponse])
# def get_30min_slots_for_facility(facility_id: int, db: Session = Depends(get_db)):
#     """Get all 30-minute slots for a facility - matches dashboard.py usage"""
#     validate_facility_exists(facility_id, db)
    
#     slots = db.query(SlotLookup).filter(
#         SlotLookup.FacilityID == facility_id,
#         SlotLookup.SlotSize == "30"  # Exactly how dashboard.py filters
#     ).order_by(SlotLookup.SlotStartTime).all()
    
#     return slots

@router.get("/{slot_id}", response_model=SlotLookupResponse)
def get_slot(slot_id: int, facility_id: int = Query(...), db: Session = Depends(get_db)):
    """Get a specific slot by ID and facility"""
    validate_facility_exists(facility_id, db)
    
    slot = db.query(SlotLookup).filter(
        SlotLookup.SlotID == slot_id,
        SlotLookup.FacilityID == facility_id
    ).first()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found for given facility")
    
    return slot

@router.post("/", response_model=SlotLookupResponse)
def create_slot(slot: SlotCreateSchema, db: Session = Depends(get_db)):
    """Create a new slot"""
    # Validate facility exists
    validate_facility_exists(slot.FacilityID, db)
    
    # Check for overlapping slots
    check_slot_overlap(slot.dict(), db)
    
    # Create new slot
    new_slot = SlotLookup(**slot.dict())
    db.add(new_slot)
    db.commit()
    db.refresh(new_slot)
    return new_slot

@router.put("/{slot_id}", response_model=SlotLookupResponse)
def update_slot(
    slot_id: int,
    slot: SlotUpdateSchema,
    facility_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """Update an existing slot"""
    validate_facility_exists(facility_id, db)
    
    existing_slot = db.query(SlotLookup).filter(
        SlotLookup.SlotID == slot_id,
        SlotLookup.FacilityID == facility_id
    ).first()
    
    if not existing_slot:
        raise HTTPException(status_code=404, detail="Slot not found for given facility")
    
    # Prepare update data
    update_data = slot.dict(exclude_unset=True)
    
    # If updating times, check for overlaps
    if 'SlotStartTime' in update_data or 'SlotEndTime' in update_data:
        # Build complete slot data for overlap check
        check_data = {
            'FacilityID': facility_id,
            'SlotStartTime': update_data.get('SlotStartTime', existing_slot.SlotStartTime),
            'SlotEndTime': update_data.get('SlotEndTime', existing_slot.SlotEndTime)
        }
        check_slot_overlap(check_data, db, exclude_slot_id=slot_id)
    
    # Apply updates
    for key, value in update_data.items():
        setattr(existing_slot, key, value)
    
    db.commit()
    db.refresh(existing_slot)
    return existing_slot

@router.delete("/{slot_id}")
def delete_slot(slot_id: int, facility_id: int = Query(...), db: Session = Depends(get_db)):
    """Delete a slot"""
    validate_facility_exists(facility_id, db)
    
    slot = db.query(SlotLookup).filter(
        SlotLookup.SlotID == slot_id,
        SlotLookup.FacilityID == facility_id
    ).first()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found for given facility")
    
    # Check if slot is being used in DoctorCalendar
    from model import DoctorCalendar
    usage_check = db.query(DoctorCalendar).filter(
        DoctorCalendar.SlotID == slot_id
    ).first()
    
    if usage_check:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete slot: it is being used in doctor schedules"
        )
    
    db.delete(slot)
    db.commit()
    return {"detail": "Slot deleted successfully"}

# ------------------- UTILITY ENDPOINTS -------------------

@router.post("/generate-standard-slots/{facility_id}")
def generate_standard_slots(
    facility_id: int,
    start_hour: int = Query(9, description="Start hour (24-hour format)"),
    end_hour: int = Query(17, description="End hour (24-hour format)"),
    slot_size: int = Query(30, description="Slot size in minutes"),
    db: Session = Depends(get_db)
):
    """Generate standard time slots for a facility"""
    validate_facility_exists(facility_id, db)
    
    if start_hour >= end_hour or start_hour < 0 or end_hour > 23:
        raise HTTPException(status_code=400, detail="Invalid hour range")
    
    if slot_size not in [15, 30, 45, 60]:
        raise HTTPException(status_code=400, detail="Slot size must be 15, 30, 45, or 60 minutes")
    
    # Clear existing slots for this facility
    db.query(SlotLookup).filter(SlotLookup.FacilityID == facility_id).delete()
    
    # Generate new slots
    created_slots = []
    current_hour = start_hour
    current_minute = 0
    
    while current_hour < end_hour or (current_hour == end_hour and current_minute == 0):
        start_time = time(current_hour, current_minute)
        
        # Calculate end time
        end_minute = current_minute + slot_size
        end_hour_calc = current_hour
        if end_minute >= 60:
            end_minute -= 60
            end_hour_calc += 1
        
        end_time = time(end_hour_calc, end_minute)
        
        # Don't create slot if it goes beyond end_hour
        if end_hour_calc > end_hour:
            break
        
        new_slot = SlotLookup(
            SlotSize=str(slot_size),
            SlotStartTime=start_time,
            SlotEndTime=end_time,
            FacilityID=facility_id
        )
        db.add(new_slot)
        created_slots.append({
            "start_time": start_time.strftime("%H:%M"),
            "end_time": end_time.strftime("%H:%M")
        })
        
        # Move to next slot
        current_minute += slot_size
        if current_minute >= 60:
            current_minute -= 60
            current_hour += 1
    
    db.commit()
    return {
        "message": f"Generated {len(created_slots)} slots for facility {facility_id}",
        "slots": created_slots
    }