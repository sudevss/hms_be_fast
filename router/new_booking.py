from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime, time,timedelta
from pydantic import BaseModel, validator
import re
from database import get_db
import model


router = APIRouter(prefix="/new_booking", tags=["new_booking"])

# -------------------- Helper Functions --------------------

def check_doctor_schedule_enhanced(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """Enhanced version with proper facility_id handling - FIXED FIELD NAMES"""
    try:
        day_of_week = appointment_date.strftime('%A')
        
        doctor_schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.Doctor_id == doctor_id,
            model.DoctorSchedule.Facility_id == facility_id,
            model.DoctorSchedule.WeekDay == day_of_week,
            model.DoctorSchedule.Start_Date <= appointment_date,
            model.DoctorSchedule.End_Date >= appointment_date
        ).all()
        
        if not doctor_schedules:
            return False, f"Doctor {doctor_id} is not scheduled to work on {day_of_week}s at facility {facility_id} for the date {appointment_date}"
        
        available_windows = []
        for schedule in doctor_schedules:
            start_time = schedule.Slot_Start_Time
            end_time = schedule.Slot_End_Time
            
            if isinstance(start_time, str):
                try:
                    start_time = datetime.strptime(start_time, '%H:%M:%S').time()
                except ValueError:
                    start_time = datetime.strptime(start_time, '%H:%M').time()
            
            if isinstance(end_time, str):
                try:
                    end_time = datetime.strptime(end_time, '%H:%M:%S').time()
                except ValueError:
                    end_time = datetime.strptime(end_time, '%H:%M').time()
            
            available_windows.append(f"Window {schedule.Window_Num}: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
            
            if start_time <= appointment_time < end_time:
                return True, f"Doctor is available in schedule window {schedule.Window_Num}: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
        
        return False, f"Doctor {doctor_id} not available at {appointment_time.strftime('%H:%M')} on {day_of_week} at facility {facility_id}. Available windows: {', '.join(available_windows)}"
        
    except Exception as e:
        return False, f"Error checking doctor schedule: {str(e)}"

def find_or_create_available_slot(db, doctor_id, facility_id, appointment_date, appointment_time):
    try:
        slot_start_time = appointment_time
        slot_end_time = (datetime.combine(date.today(), appointment_time) + timedelta(minutes=15)).time()

        # Check for exact match first
        existing_slot = db.query(model.DoctorBookedSlots).filter(
            model.DoctorBookedSlots.Doctor_id == doctor_id,
            model.DoctorBookedSlots.Facility_id == facility_id,
            model.DoctorBookedSlots.Slot_date == appointment_date,
            model.DoctorBookedSlots.Start_Time == slot_start_time,
            model.DoctorBookedSlots.End_Time == slot_end_time
        ).first()

        if existing_slot:
            if existing_slot.Booked_status == "Booked":
                return None, f"Time slot {appointment_time.strftime('%H:%M')} on {appointment_date} is already booked"
            else:
                existing_slot.Booked_status = "Booked"
                db.commit()
                return existing_slot.DCID, None

        # Check for overlapping slots (booked status only)
        overlapping_slots = db.query(model.DoctorBookedSlots).filter(
            model.DoctorBookedSlots.Doctor_id == doctor_id,
            model.DoctorBookedSlots.Facility_id == facility_id,
            model.DoctorBookedSlots.Slot_date == appointment_date,
            model.DoctorBookedSlots.Booked_status == "Booked",
            # Check for any overlap: new slot overlaps if it starts before existing ends AND ends after existing starts
            ((model.DoctorBookedSlots.Start_Time < slot_end_time) & (model.DoctorBookedSlots.End_Time > slot_start_time))
        ).all()

        if overlapping_slots:
            conflicting_times = []
            for slot in overlapping_slots:
                conflicting_times.append(f"{slot.Start_Time.strftime('%H:%M')}-{slot.End_Time.strftime('%H:%M')}")
            return None, f"Time slot {slot_start_time.strftime('%H:%M')}-{slot_end_time.strftime('%H:%M')} overlaps with existing booked slots: {', '.join(conflicting_times)}. Please choose a time with at least 15-minute gap."

        # Create new slot if no conflicts
        new_slot = model.DoctorBookedSlots(
            Doctor_id=doctor_id,
            Facility_id=facility_id,
            Slot_date=appointment_date,
            Start_Time=slot_start_time,
            End_Time=slot_end_time,
            Booked_status="Booked"
        )
        db.add(new_slot)
        db.commit()
        db.refresh(new_slot)
        return new_slot.DCID, None

    except Exception as e:
        return None, str(e)

def update_slot_booking_status(db, dcid, status="Booked"):
    try:
        slot = db.query(model.DoctorBookedSlots).filter(model.DoctorBookedSlots.DCID == dcid).first()
        if not slot:
            return False, f"No slot found with DCID {dcid}"
        if status not in ["Booked", "Not Booked"]:
            return False, f"Invalid status: {status}"
        slot.Booked_status = status
        db.commit()
        return True, None
    except Exception as e:
        return False, str(e)

def validate_appointment_constraints(db: Session, patient_id: int, doctor_id: int, 
                                   facility_id: int, appointment_date: date, appointment_time: time):
    try:
        # Check for overlapping appointments (same patient, same date, same time)
        overlapping = db.query(model.Appointment).filter(
            model.Appointment.PatientID == patient_id,
            model.Appointment.AppointmentDate == appointment_date,
            model.Appointment.AppointmentTime == appointment_time,
            model.Appointment.Cancelled == False
        ).first()
        
        if overlapping:
            return False, "Patient already has an appointment at this time"
        
        # Removed the daily appointment limit check
        # Now patients can book unlimited appointments per day
        
        return True, "Validation passed"
        
    except Exception as e:
        return False, f"Error validating appointment constraints: {str(e)}"

# -------------------- Pydantic Models --------------------

class PatientInfo(BaseModel):
    firstname: str
    lastname: str
    age: Optional[int] = None
    dob: Optional[date] = None
    contact_number: str
    address: Optional[str] = None
    gender: Optional[str] = None
    email_id: Optional[str] = None
    disease: Optional[str] = None
    ABDM_ABHA_id: Optional[str] = None
    
    @validator('contact_number')
    def validate_phone(cls, v):
        if not v:
            raise ValueError("Contact number is required")
        phone = re.sub(r'[^\d]', '', v)
        if len(phone) != 10 or not phone.isdigit():
            raise ValueError("Contact number must be a valid 10-digit number")
        return phone
    
    @validator('email_id')
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError("Invalid email format")
        return v
    
    @validator('firstname')
    def validate_firstname(cls, v):
        if not v or not v.strip():
            raise ValueError("First name is required")
        return v.strip()
    
    @validator('lastname')
    def validate_lastname(cls, v):
        if not v or not v.strip():
            raise ValueError("Last name is required")
        return v.strip()
    
    @property
    def name(self) -> str:
        return f"{self.firstname} {self.lastname}".strip()
    
    def dict(self, **kwargs):
        data = super().dict(**kwargs)
        data['name'] = self.name
        return data

class DashboardAppointmentCreate(BaseModel):
    patient_info: PatientInfo
    DoctorID: int
    FacilityID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str = "A"
    room_id: Optional[int] = 1
    payment_status: Optional[int] = 0
    payment_method: Optional[str] = "Cash"

    @validator('AppointmentTime', pre=True)
    def parse_time(cls, v):
        if v is None:
            raise ValueError("AppointmentTime is required")
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                return datetime.fromisoformat(f"2000-01-01T{v}").time().replace(second=0, microsecond=0)
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
            if isinstance(v, time):
                return v.replace(second=0, microsecond=0)
        except Exception:
            raise ValueError("Invalid format for AppointmentTime")

    @validator('AppointmentDate')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError("Appointment date cannot be in the past")
        return v

    @validator('payment_status')
    def validate_payment_status(cls, v):
        if v not in [0, 1]:
            raise ValueError("Payment status must be 0 (unpaid) or 1 (paid)")
        return v

    @validator('payment_method')
    def validate_payment_method(cls, v):
        valid_methods = ['Cash', 'Debit Card', 'Credit Card', 'UPI', 'Net Banking']
        if v and v not in valid_methods:
            raise ValueError(f"Payment method must be one of: {', '.join(valid_methods)}")
        return v or "Cash"

class AppointmentResponse(BaseModel):
    AppointmentID: int
    PatientID: int
    DoctorID: int
    FacilityID: int
    DCID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str
    CheckinTime: Optional[datetime] = None
    Cancelled: Optional[bool] = None
    TokenID: Optional[str] = None
    AppointmentStatus: Optional[str] = None
    payment_method: Optional[str] = None

class DashboardAppointmentResponse(BaseModel):
    appointment: AppointmentResponse
    patient: dict
    is_new_patient: bool
    message: str

class PatientDetails(BaseModel):
    id: int
    name: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    contact_number: str
    age: Optional[int] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    email_id: Optional[str] = None
    disease: Optional[str] = None
    ABDM_ABHA_id: Optional[str] = None
    facility_id: int
    recent_appointments: List[dict] = []

class PatientLookupResponse(BaseModel):
    exists: bool
    total_patients: int
    patients: List[PatientDetails] = []
    message: str

class QuickAppointmentCreate(BaseModel):
    PatientID: int
    DoctorID: int
    FacilityID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str = "A"
    room_id: Optional[int] = 1
    payment_status: Optional[int] = 0
    payment_method: Optional[str] = "Cash"

    @validator('PatientID')
    def validate_patient_id(cls, v):
        if not v or v <= 0:
            raise ValueError("Valid PatientID is required")
        return v

    @validator('AppointmentTime', pre=True)
    def parse_time(cls, v):
        if v is None:
            raise ValueError("AppointmentTime is required")
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                return datetime.fromisoformat(f"2000-01-01T{v}").time().replace(second=0, microsecond=0)
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
            if isinstance(v, time):
                return v.replace(second=0, microsecond=0)
        except Exception:
            raise ValueError("Invalid format for AppointmentTime")

    @validator('AppointmentDate')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError("Appointment date cannot be in the past")
        return v

    @validator('payment_status')
    def validate_payment_status(cls, v):
        if v not in [0, 1]:
            raise ValueError("Payment status must be 0 (unpaid) or 1 (paid)")
        return v

    @validator('payment_method')
    def validate_payment_method(cls, v):
        valid_methods = ['Cash', 'Debit Card', 'Credit Card', 'UPI', 'Net Banking']
        if v and v not in valid_methods:
            raise ValueError(f"Payment method must be one of: {', '.join(valid_methods)}")
        return v or "Cash"

# -------------------- Endpoints --------------------
@router.post("/book", response_model=DashboardAppointmentResponse)
def dashboard_book_appointment(booking_data: DashboardAppointmentCreate, db: Session = Depends(get_db)):
    """Enhanced Dashboard API: Books appointment with proper validation flow"""
    try:
        schedule_valid, schedule_message = check_doctor_schedule_enhanced(
            db, booking_data.DoctorID, booking_data.FacilityID, 
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not schedule_valid:
            raise HTTPException(400, f"Doctor schedule validation failed: {schedule_message}")
        
        slot_dcid, error_message = find_or_create_available_slot(
            db, booking_data.DoctorID, booking_data.FacilityID,
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not slot_dcid:
            raise HTTPException(400, f"Booking validation failed: {error_message}")
        
        phone_number = booking_data.patient_info.contact_number
        facility_id = booking_data.FacilityID
        
        # Always create new patient - allow multiple patients with same phone number
        is_new_patient = True
        if not booking_data.patient_info.name:
            raise HTTPException(400, "Name is required for new patient")
        
        name_parts = booking_data.patient_info.name.split()
        firstname = name_parts[0] if name_parts else "Unknown"
        lastname = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        new_patient = model.Patients(
            firstname=firstname,
            lastname=lastname,
            age=booking_data.patient_info.age or 0,
            dob=booking_data.patient_info.dob or date.today(),
            contact_number=phone_number,
            address=booking_data.patient_info.address or "Not provided",
            gender=booking_data.patient_info.gender or "Not specified",
            email_id=booking_data.patient_info.email_id or f"{phone_number}@temp.com",
            disease=booking_data.patient_info.disease or "General consultation",
            room_id=booking_data.room_id,
            payment_status=booking_data.payment_status,
            ABDM_ABHA_id=booking_data.patient_info.ABDM_ABHA_id,
            FacilityID=facility_id
        )
        
        db.add(new_patient)
        db.flush()
        patient_id = new_patient.id
        
        patient_dict = {
            "id": new_patient.id,
            "name": booking_data.patient_info.name,
            "contact_number": new_patient.contact_number,
            "age": new_patient.age,
            "address": new_patient.address,
            "gender": new_patient.gender,
            "email_id": new_patient.email_id,
            "disease": new_patient.disease,
            "ABDM_ABHA_id": new_patient.ABDM_ABHA_id
        }
        
        is_valid, validation_error = validate_appointment_constraints(
            db, patient_id, booking_data.DoctorID, facility_id,
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not is_valid:
            raise HTTPException(400, f"Appointment validation failed: {validation_error}")
        
        if not db.query(model.Doctors).filter(model.Doctors.id == booking_data.DoctorID).first():
            raise HTTPException(404, "Doctor not found")
        
        new_appointment = model.Appointment(
            PatientID=patient_id,
            DoctorID=booking_data.DoctorID,
            FacilityID=facility_id,
            DCID=slot_dcid,
            AppointmentDate=booking_data.AppointmentDate,
            AppointmentTime=booking_data.AppointmentTime,
            Reason=booking_data.Reason,
            AppointmentMode=booking_data.AppointmentMode,
            AppointmentStatus="Scheduled",
            Cancelled=False,
            TokenID=None,
            CheckinTime=None,
            payment_method=booking_data.payment_method
        )
        
        db.add(new_appointment)
        update_slot_booking_status(db, slot_dcid)
        db.commit()
        db.refresh(new_appointment)
        
        appointment_response = AppointmentResponse(
            AppointmentID=new_appointment.AppointmentID,
            PatientID=new_appointment.PatientID,
            DoctorID=new_appointment.DoctorID,
            FacilityID=new_appointment.FacilityID,
            DCID=new_appointment.DCID,
            AppointmentDate=new_appointment.AppointmentDate,
            AppointmentTime=new_appointment.AppointmentTime,
            Reason=new_appointment.Reason,
            AppointmentMode=new_appointment.AppointmentMode,
            CheckinTime=new_appointment.CheckinTime,
            Cancelled=new_appointment.Cancelled,
            TokenID=new_appointment.TokenID,
            AppointmentStatus=new_appointment.AppointmentStatus,
            payment_method=new_appointment.payment_method
        )
        
        payment_msg = "paid" if booking_data.payment_status == 1 else "unpaid"
        payment_method_msg = f"via {booking_data.payment_method}"
        success_message = f"New patient created and appointment booked successfully ({payment_msg} {payment_method_msg})"
        
        return DashboardAppointmentResponse(
            appointment=appointment_response,
            patient=patient_dict,
            is_new_patient=True,
            message=success_message
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error processing dashboard booking: {str(e)}")


@router.get("/lookup", response_model=PatientLookupResponse)
def dashboard_patient_lookup(
    phone_number: str = Query(..., description="Patient phone number"),
    facility_id: Optional[int] = Query(None, alias="FacilityID", description="Filter by specific facility"),
    db: Session = Depends(get_db)
):
    """Lookup ALL patients registered with the same phone number"""
    try:
        clean_phone = re.sub(r'[^\d]', '', phone_number)
        if len(clean_phone) != 10:
            raise HTTPException(400, "Invalid phone number format. Must be 10 digits.")
        
        query = db.query(model.Patients).filter(model.Patients.contact_number == clean_phone)
        if facility_id:
            query = query.filter(model.Patients.FacilityID == facility_id)
        
        patients = query.order_by(model.Patients.FacilityID, model.Patients.firstname, model.Patients.lastname).all()
        
        if not patients:
            msg = f"No patients found with phone number {clean_phone}"
            if facility_id:
                msg += f" in facility {facility_id}"
            msg += ". New patient will be created when booking."
            return PatientLookupResponse(exists=False, total_patients=0, patients=[], message=msg)
        
        patient_details_list = []
        for patient in patients:
            try:
                recent_appointments = db.query(model.Appointment).filter(
                    model.Appointment.PatientID == patient.id
                ).order_by(model.Appointment.AppointmentDate.desc()).limit(10).all()
            except Exception:
                recent_appointments = []
            
            appointment_history = []
            for apt in recent_appointments:
                try:
                    doctor = db.query(model.Doctors).filter(model.Doctors.id == apt.DoctorID).first()
                    doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}" if doctor else "Unknown Doctor"
                    
                    facility = db.query(model.Facility).filter(model.Facility.FacilityID == apt.FacilityID).first()
                    facility_name = facility.FacilityName if facility else f"Facility {apt.FacilityID}"
                    
                    status = "Cancelled" if apt.Cancelled else (apt.AppointmentStatus or ("Checked In" if apt.CheckinTime else "Scheduled"))
                    
                    appointment_history.append({
                        "appointment_id": apt.AppointmentID,
                        "date": apt.AppointmentDate.isoformat(),
                        "time": apt.AppointmentTime.strftime("%H:%M"),
                        "doctor": doctor_name,
                        "facility": facility_name,
                        "reason": apt.Reason,
                        "status": status,
                        "mode": apt.AppointmentMode,
                        "cancelled": apt.Cancelled,
                        "checkin_time": apt.CheckinTime.isoformat() if apt.CheckinTime else None,
                        "token_id": apt.TokenID,
                        "payment_method": getattr(apt, 'payment_method', 'Cash')
                    })
                except Exception:
                    continue
            
            full_name = f"{patient.firstname} {patient.lastname}".strip()
            
            patient_details_list.append(PatientDetails(
                id=patient.id,
                name=full_name,
                firstname=patient.firstname,
                lastname=patient.lastname,
                contact_number=patient.contact_number,
                age=patient.age,
                dob=patient.dob.isoformat() if patient.dob else None,
                address=patient.address,
                gender=patient.gender,
                email_id=getattr(patient, 'email_id', None),
                disease=getattr(patient, 'disease', None),
                ABDM_ABHA_id=getattr(patient, 'ABDM_ABHA_id', None),
                facility_id=patient.FacilityID,
                recent_appointments=appointment_history
            ))
        
        total = len(patients)
        total_all_appointments = sum(len(p.recent_appointments) for p in patient_details_list)
        
        message = f"Found {total} {'patient' if total == 1 else 'patients'} with phone number {clean_phone}"
        
        if facility_id:
            message += f" in facility {facility_id}"
        else:
            counts = {}
            for p in patients:
                counts[p.FacilityID] = counts.get(p.FacilityID, 0) + 1
            if len(counts) > 1:
                parts = [f"{cnt} in facility {fid}" for fid, cnt in counts.items()]
                message += f" across facilities ({', '.join(parts)})"
        
        if total_all_appointments > 0:
            message += f". Total recent appointments: {total_all_appointments} (including cancelled/completed)"
        
        message += ". Select a patient to book appointment or create new patient."
        
        return PatientLookupResponse(
            exists=True,
            total_patients=total,
            patients=patient_details_list,
            message=message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error looking up patients: {str(e)}")


@router.post("/book-existing", response_model=DashboardAppointmentResponse)
def book_appointment_for_existing_patient(booking_data: QuickAppointmentCreate, db: Session = Depends(get_db)):
    """Enhanced Quick booking for existing patients using PatientID"""
    try:
        schedule_valid, schedule_message = check_doctor_schedule_enhanced(
            db, booking_data.DoctorID, booking_data.FacilityID,
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not schedule_valid:
            raise HTTPException(400, f"Doctor schedule validation failed: {schedule_message}")
        
        slot_dcid, error_message = find_or_create_available_slot(
            db, booking_data.DoctorID, booking_data.FacilityID,
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not slot_dcid:
            raise HTTPException(400, f"Booking validation failed: {error_message}")
        
        existing_patient = db.query(model.Patients).filter(
            model.Patients.id == booking_data.PatientID,
            model.Patients.FacilityID == booking_data.FacilityID
        ).first()
        
        if not existing_patient:
            raise HTTPException(404, f"Patient with ID {booking_data.PatientID} not found in facility {booking_data.FacilityID}")
        
        is_valid, validation_error = validate_appointment_constraints(
            db, booking_data.PatientID, booking_data.DoctorID, booking_data.FacilityID,
            booking_data.AppointmentDate, booking_data.AppointmentTime
        )
        
        if not is_valid:
            raise HTTPException(400, f"Appointment validation failed: {validation_error}")
        
        if booking_data.payment_status is not None:
            existing_patient.payment_status = booking_data.payment_status
        if booking_data.room_id is not None:
            existing_patient.room_id = booking_data.room_id
        db.flush()
        
        full_name = f"{existing_patient.firstname} {existing_patient.lastname}".strip()
        patient_dict = {
            "id": existing_patient.id,
            "name": full_name,
            "contact_number": existing_patient.contact_number,
            "age": existing_patient.age,
            "address": existing_patient.address,
            "gender": existing_patient.gender,
            "email_id": getattr(existing_patient, 'email_id', None),
            "disease": getattr(existing_patient, 'disease', None),
            "ABDM_ABHA_id": getattr(existing_patient, 'ABDM_ABHA_id', None)
        }
        
        if not db.query(model.Doctors).filter(model.Doctors.id == booking_data.DoctorID).first():
            raise HTTPException(404, "Doctor not found")
        
        new_appointment = model.Appointment(
            PatientID=booking_data.PatientID,
            DoctorID=booking_data.DoctorID,
            FacilityID=booking_data.FacilityID,
            DCID=slot_dcid,
            AppointmentDate=booking_data.AppointmentDate,
            AppointmentTime=booking_data.AppointmentTime,
            Reason=booking_data.Reason,
            AppointmentMode=booking_data.AppointmentMode,
            AppointmentStatus="Scheduled",
            Cancelled=False,
            TokenID=None,
            CheckinTime=None,
            payment_method=booking_data.payment_method
        )
        
        db.add(new_appointment)
        update_slot_booking_status(db, slot_dcid)
        db.commit()
        db.refresh(new_appointment)
        
        appointment_response = AppointmentResponse(
            AppointmentID=new_appointment.AppointmentID,
            PatientID=new_appointment.PatientID,
            DoctorID=new_appointment.DoctorID,
            FacilityID=new_appointment.FacilityID,
            DCID=new_appointment.DCID,
            AppointmentDate=new_appointment.AppointmentDate,
            AppointmentTime=new_appointment.AppointmentTime,
            Reason=new_appointment.Reason,
            AppointmentMode=new_appointment.AppointmentMode,
            CheckinTime=new_appointment.CheckinTime,
            Cancelled=new_appointment.Cancelled,
            TokenID=new_appointment.TokenID,
            AppointmentStatus=new_appointment.AppointmentStatus,
            payment_method=new_appointment.payment_method
        )
        
        payment_msg = "paid" if booking_data.payment_status == 1 else "unpaid"
        payment_method_msg = f"via {booking_data.payment_method}"
        success_message = f"Appointment booked for existing patient successfully ({payment_msg} {payment_method_msg})"
        
        return DashboardAppointmentResponse(
            appointment=appointment_response,
            patient=patient_dict,
            is_new_patient=False,
            message=success_message
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error processing quick booking for existing patient: {str(e)}")