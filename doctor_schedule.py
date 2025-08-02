from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from database import get_db
from model import DoctorSchedule, Appointment, Doctors as Doctor
from datetime import datetime, timedelta

router = APIRouter(
    prefix="/doctor_schedule",
    tags=["DoctorSchedule"]
)

class DoctorScheduleBase(BaseModel):
    DoctorID: int
    DayOfWeek: str
    StartTime: str
    EndTime: str
    Slotsize: str
    AppointmentsPerSlot: int
    FacilityID: int

class DoctorScheduleResponse(DoctorScheduleBase):
    ScheduleID: int

    class Config:
        orm_mode = True

@router.get("/", response_model=List[DoctorScheduleResponse])
def get_all_schedules(db: Session = Depends(get_db)):
    return db.query(DoctorSchedule).all()

@router.get("/{schedule_id}", response_model=DoctorScheduleResponse)
def get_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.ScheduleID == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule

@router.post("/", response_model=DoctorScheduleResponse)
def create_schedule(schedule: DoctorScheduleBase, db: Session = Depends(get_db)):
    new_schedule = DoctorSchedule(**schedule.dict())
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    return new_schedule

@router.put("/{schedule_id}", response_model=DoctorScheduleResponse)
def update_schedule(schedule_id: int, schedule: DoctorScheduleBase, db: Session = Depends(get_db)):
    existing_schedule = db.query(DoctorSchedule).filter(DoctorSchedule.ScheduleID == schedule_id).first()
    if not existing_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    for key, value in schedule.dict().items():
        setattr(existing_schedule, key, value)
    db.commit()
    db.refresh(existing_schedule)
    return existing_schedule

@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.ScheduleID == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
    return {"detail": "Schedule deleted successfully"}

class AppointmentDetails(BaseModel):
    AppointmentID: int
    AppointmentDate: str
    AppointmentTime: str

    class Config:
        orm_mode = True

class FreeSlot(BaseModel):
    StartTime: str
    EndTime: str

class DoctorScheduleWithDetails(BaseModel):
    ScheduleID: int
    DayOfWeek: str
    StartTime: str
    EndTime: str
    Slotsize: str
    FreeSlots: List[FreeSlot]

class DoctorWithSchedulesAndAppointments(BaseModel):
    DoctorID: int
    Schedules: List[DoctorScheduleWithDetails]
    Appointments: List[AppointmentDetails]

    class Config:
        orm_mode = True

@router.get("/doctor/{doctor_id}/details", response_model=DoctorWithSchedulesAndAppointments)
def get_doctor_details_with_free_slots(doctor_id: int, date: str, db: Session = Depends(get_db)):
    """
    Retrieve all schedules, appointments, and calculate free slots for a doctor on a given date.
    """
    # Fetch schedules for the doctor
    schedules = db.query(DoctorSchedule).filter(DoctorSchedule.DoctorID == doctor_id).all()

    # Fetch appointments for the doctor on the given date
    appointments = db.query(Appointment).filter(
        Appointment.DoctorID == doctor_id,
        Appointment.AppointmentDate == date
    ).all()

    # Prepare appointment data
    appointment_data = [
        AppointmentDetails(
            AppointmentID=appointment.AppointmentID,
            AppointmentDate=appointment.AppointmentDate,
            AppointmentTime=appointment.AppointmentTime
        )
        for appointment in appointments
    ]

    # Calculate free slots for each schedule
    schedule_data = []
    for schedule in schedules:
        start_time = datetime.strptime(schedule.StartTime, "%H:%M")
        end_time = datetime.strptime(schedule.EndTime, "%H:%M")
        slot_size = timedelta(minutes=int(schedule.Slotsize))

        # Generate all possible slots
        all_slots = []
        current_time = start_time
        while current_time + slot_size <= end_time:
            all_slots.append((current_time, current_time + slot_size))
            current_time += slot_size

        # Mark booked slots
        booked_slots = set(
            datetime.strptime(appointment.AppointmentTime, "%H:%M")
            for appointment in appointments
            if appointment.ScheduleID == schedule.ScheduleID
        )

        # Calculate free slots
        free_slots = [
            FreeSlot(StartTime=slot[0].strftime("%H:%M"), EndTime=slot[1].strftime("%H:%M"))
            for slot in all_slots
            if slot[0] not in booked_slots
        ]

        schedule_data.append(
            DoctorScheduleWithDetails(
                ScheduleID=schedule.ScheduleID,
                DayOfWeek=schedule.DayOfWeek,
                StartTime=schedule.StartTime,
                EndTime=schedule.EndTime,
                Slotsize=schedule.Slotsize,
                FreeSlots=free_slots
            )
        )

    return DoctorWithSchedulesAndAppointments(
        DoctorID=doctor_id,
        Schedules=schedule_data,
        Appointments=appointment_data
    )

@router.get("/facility/{facility_id}/details", response_model=List[DoctorWithSchedulesAndAppointments])
def get_facility_doctors_with_free_slots(facility_id: int, db: Session = Depends(get_db)):
    """
    Retrieve all schedules, appointments, and calculate free slots for all doctors in a facility for all dates,
    considering slotsize and appointments per hour.
    """
    # Fetch all schedules in the facility
    schedules = db.query(DoctorSchedule).filter(DoctorSchedule.FacilityID == facility_id).all()

    if not schedules:
        raise HTTPException(status_code=404, detail="No schedules found for the given facility")

    # Group schedules by doctor
    doctor_schedules = {}
    for schedule in schedules:
        if schedule.DoctorID not in doctor_schedules:
            doctor_schedules[schedule.DoctorID] = []
        doctor_schedules[schedule.DoctorID].append(schedule)

    result = []

    for doctor_id, schedules in doctor_schedules.items():
        # Fetch all appointments for the doctor
        appointments = db.query(Appointment).filter(Appointment.DoctorID == doctor_id).all()

        # Prepare appointment data
        appointment_data = [
            AppointmentDetails(
                AppointmentID=appointment.AppointmentID,
                AppointmentDate=appointment.AppointmentDate,
                AppointmentTime=appointment.AppointmentTime
            )
            for appointment in appointments
        ]

        # Calculate free slots for each schedule
        schedule_data = []
        for schedule in schedules:
            start_time = datetime.strptime(schedule.StartTime, "%H:%M")
            end_time = datetime.strptime(schedule.EndTime, "%H:%M")
            slot_size = timedelta(minutes=int(schedule.Slotsize))
            appointments_per_slot = schedule.AppointmentsPerSlot

            # Generate all possible slots
            all_slots = []
            current_time = start_time
            while current_time + slot_size <= end_time:
                all_slots.append((current_time, current_time + slot_size))
                current_time += slot_size

            # Mark booked slots with counts
            booked_slots = {}
            for appointment in appointments:
                if appointment.ScheduleID == schedule.ScheduleID:
                    appointment_time = datetime.strptime(appointment.AppointmentTime, "%H:%M")
                    if appointment_time not in booked_slots:
                        booked_slots[appointment_time] = 0
                    booked_slots[appointment_time] += 1

            # Calculate free slots
            free_slots = []
            for slot in all_slots:
                slot_start = slot[0]
                if booked_slots.get(slot_start, 0) < appointments_per_slot:
                    free_slots.append(
                        FreeSlot(StartTime=slot_start.strftime("%H:%M"), EndTime=slot[1].strftime("%H:%M"))
                    )

            schedule_data.append(
                DoctorScheduleWithDetails(
                    ScheduleID=schedule.ScheduleID,
                    DayOfWeek=schedule.DayOfWeek,
                    StartTime=schedule.StartTime,
                    EndTime=schedule.EndTime,
                    Slotsize=schedule.Slotsize,
                    FreeSlots=free_slots
                )
            )

        result.append(
            DoctorWithSchedulesAndAppointments(
                DoctorID=doctor_id,
                Schedules=schedule_data,
                Appointments=appointment_data
            )
        )

    return result