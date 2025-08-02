from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import date as DateType
from database import get_db
from model import DoctorCalendar

router = APIRouter(
    prefix="/doctor_calendar",
    tags=["Doctor Calendar"]
)

class DoctorCalendarBase(BaseModel):
    doctor_id: int = Field(..., description="ID of the doctor", gt=0)
    calendar_date: DateType = Field(..., description="Calendar date")
    slot_id: int = Field(..., description="Time slot ID", gt=0)
    full_day_leave: bool = Field(default=False, description="Whether doctor is on full day leave")
    slot_leave: bool = Field(default=False, description="Whether this specific slot is on leave")
    total_appointments: int = Field(..., description="Total appointment slots available", ge=0)
    booked_appointments: int = Field(default=0, description="Number of booked appointments", ge=0)
    facility_id: int = Field(..., description="ID of the medical facility", gt=0)

class DoctorCalendarCreate(DoctorCalendarBase):
    pass

class DoctorCalendarUpdate(BaseModel):
    doctor_id: Optional[int] = Field(None, gt=0)
    calendar_date: Optional[DateType] = None
    slot_id: Optional[int] = Field(None, gt=0)
    full_day_leave: Optional[bool] = None
    slot_leave: Optional[bool] = None
    total_appointments: Optional[int] = Field(None, ge=0)
    booked_appointments: Optional[int] = Field(None, ge=0)
    facility_id: Optional[int] = Field(None, gt=0)

class DoctorCalendarResponse(BaseModel):
    dcid: int
    doctor_id: int
    calendar_date: DateType
    slot_id: int
    full_day_leave: bool
    slot_leave: bool
    total_appointments: int
    booked_appointments: int
    available_appointments: int
    facility_id: int

    class Config:
        from_attributes = True

def convert_db_to_response(db_entry) -> DoctorCalendarResponse:
    """Convert database model to response model"""
    return DoctorCalendarResponse(
        dcid=db_entry.DCID,
        doctor_id=db_entry.DoctorID,
        calendar_date=db_entry.Date,
        slot_id=db_entry.SlotID,
        full_day_leave=db_entry.FullDayLeave == 'Y',
        slot_leave=db_entry.SlotLeave == 'Y',
        total_appointments=db_entry.TotalAppointments,
        booked_appointments=db_entry.BookedAppointments,
        available_appointments=db_entry.AvailableAppointments,
        facility_id=db_entry.FacilityID
    )

@router.get("/", response_model=List[DoctorCalendarResponse])
def get_all_calendar_entries(
    skip: int = Query(0, ge=0, description="Skip records"),
    limit: int = Query(100, ge=1, le=1000, description="Limit records"),
    doctor_id: Optional[int] = Query(None, description="Filter by doctor ID"),
    facility_id: Optional[int] = Query(None, description="Filter by facility ID"),
    date_from: Optional[DateType] = Query(None, description="Filter from date"),
    date_to: Optional[DateType] = Query(None, description="Filter to date"),
    db: Session = Depends(get_db)
):
    """Get all calendar entries with optional filtering"""
    query = db.query(DoctorCalendar)
    
    if doctor_id:
        query = query.filter(DoctorCalendar.DoctorID == doctor_id)
    if facility_id:
        query = query.filter(DoctorCalendar.FacilityID == facility_id)
    if date_from:
        query = query.filter(DoctorCalendar.Date >= date_from)
    if date_to:
        query = query.filter(DoctorCalendar.Date <= date_to)
    
    entries = query.offset(skip).limit(limit).all()
    return [convert_db_to_response(entry) for entry in entries]

@router.get("/{dcid}", response_model=DoctorCalendarResponse)
def get_calendar_entry(dcid: int, db: Session = Depends(get_db)):
    """Get a specific calendar entry by ID"""
    entry = db.query(DoctorCalendar).filter(DoctorCalendar.DCID == dcid).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    return convert_db_to_response(entry)

@router.post("/", response_model=DoctorCalendarResponse, status_code=201)
def create_calendar_entry(entry_data: DoctorCalendarCreate, db: Session = Depends(get_db)):
    """Create a new calendar entry"""
    try:
        # Calculate available appointments
        available_appointments = max(0, entry_data.total_appointments - entry_data.booked_appointments)
        
        new_entry = DoctorCalendar(
            DoctorID=entry_data.doctor_id,
            Date=entry_data.calendar_date,
            SlotID=entry_data.slot_id,
            FullDayLeave='Y' if entry_data.full_day_leave else 'N',
            SlotLeave='Y' if entry_data.slot_leave else 'N',
            TotalAppointments=entry_data.total_appointments,
            BookedAppointments=entry_data.booked_appointments,
            AvailableAppointments=available_appointments,
            FacilityID=entry_data.facility_id
        )
        
        db.add(new_entry)
        db.commit()
        db.refresh(new_entry)
        return convert_db_to_response(new_entry)
        
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Calendar entry already exists or violates constraints")

@router.put("/{dcid}", response_model=DoctorCalendarResponse)
def update_calendar_entry_full(dcid: int, entry_data: DoctorCalendarCreate, db: Session = Depends(get_db)):
    """Update entire calendar entry"""
    existing_entry = db.query(DoctorCalendar).filter(DoctorCalendar.DCID == dcid).first()
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    
    try:
        # Calculate available appointments
        available_appointments = max(0, entry_data.total_appointments - entry_data.booked_appointments)
        
        # Update all fields
        existing_entry.DoctorID = entry_data.doctor_id
        existing_entry.Date = entry_data.calendar_date
        existing_entry.SlotID = entry_data.slot_id
        existing_entry.FullDayLeave = 'Y' if entry_data.full_day_leave else 'N'
        existing_entry.SlotLeave = 'Y' if entry_data.slot_leave else 'N'
        existing_entry.TotalAppointments = entry_data.total_appointments
        existing_entry.BookedAppointments = entry_data.booked_appointments
        existing_entry.AvailableAppointments = available_appointments
        existing_entry.FacilityID = entry_data.facility_id
        
        db.commit()
        db.refresh(existing_entry)
        return convert_db_to_response(existing_entry)
        
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update violates database constraints")

@router.patch("/{dcid}", response_model=DoctorCalendarResponse)
def update_calendar_entry_partial(dcid: int, entry_data: DoctorCalendarUpdate, db: Session = Depends(get_db)):
    """Partially update calendar entry"""
    existing_entry = db.query(DoctorCalendar).filter(DoctorCalendar.DCID == dcid).first()
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    
    try:
        # Update only provided fields
        update_data = entry_data.dict(exclude_unset=True)
        
        if 'doctor_id' in update_data:
            existing_entry.DoctorID = update_data['doctor_id']
        if 'calendar_date' in update_data:
            existing_entry.Date = update_data['calendar_date']
        if 'slot_id' in update_data:
            existing_entry.SlotID = update_data['slot_id']
        if 'full_day_leave' in update_data:
            existing_entry.FullDayLeave = 'Y' if update_data['full_day_leave'] else 'N'
        if 'slot_leave' in update_data:
            existing_entry.SlotLeave = 'Y' if update_data['slot_leave'] else 'N'
        if 'total_appointments' in update_data:
            existing_entry.TotalAppointments = update_data['total_appointments']
        if 'booked_appointments' in update_data:
            existing_entry.BookedAppointments = update_data['booked_appointments']
        if 'facility_id' in update_data:
            existing_entry.FacilityID = update_data['facility_id']
        
        # Recalculate available appointments
        existing_entry.AvailableAppointments = max(0, existing_entry.TotalAppointments - existing_entry.BookedAppointments)
        
        db.commit()
        db.refresh(existing_entry)
        return convert_db_to_response(existing_entry)
        
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update violates database constraints")

@router.delete("/{dcid}")
def delete_calendar_entry(dcid: int, db: Session = Depends(get_db)):
    """Delete a calendar entry"""
    entry = db.query(DoctorCalendar).filter(DoctorCalendar.DCID == dcid).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    
    db.delete(entry)
    db.commit()
    return {"message": "Calendar entry deleted successfully", "dcid": dcid}