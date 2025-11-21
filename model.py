
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Date, Integer, String, ForeignKey, DateTime, Time, Boolean, Numeric, func, CheckConstraint, Index, UniqueConstraint, Text
from database import Base
import sqlalchemy as sa

class Facility(Base):
    __tablename__ = "facility"

    facility_id = Column(Integer, primary_key=True, index=True)
    FacilityName = Column(String(200), nullable=False)
    FacilityAddress = Column(String(500))
    ABDM_NHFR_ID = Column(String(100))
    TaxNumber = Column(String(50))

    # Relationships
    users = relationship("UserMaster", back_populates="facility")
    patients = relationship("Patients", back_populates="facility")
    doctors = relationship("Doctors", back_populates="facility")
    doctor_schedules = relationship("DoctorSchedule", back_populates="facility")
    booked_slots = relationship("DoctorBookedSlots", back_populates="facility")
    appointments = relationship("Appointment", back_populates="facility")

class Doctors(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    firstname = Column(String(100), nullable=False, index=True)
    lastname = Column(String(100), nullable=False, index=True)
    specialization = Column(String(100))
    phone_number = Column(String(20))
    email = Column(String(200), index=True)
    consultation_fee = Column(Numeric(10, 2))
    ABDM_NHPR_id = Column(String(100))
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    gender = Column(String(10))
    age = Column(Integer)
    experience = Column(Integer)
    
    # New flags for soft delete and active status
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    # Relationships
    facility = relationship("Facility", back_populates="doctors")
    doctor_schedules = relationship("DoctorSchedule", back_populates="doctor")
    booked_slots = relationship("DoctorBookedSlots", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    medical_records = relationship("MedicalRecord", back_populates="doctor")
    medical_documents = relationship("MedicalDocument", back_populates="doctor")

class Patients(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    firstname = Column(String(100), index=True, nullable=False)
    lastname = Column(String(100), index=True, nullable=False)
    dob = Column(Date)
    age = Column(Integer)
    contact_number = Column(String(20), nullable=False)
    address = Column(String(200))
    gender = Column(String(10))
    ABDM_ABHA_id = Column(String(50))
    email_id = Column(String(200), nullable=False)
    disease = Column(String(200))
    room_id = Column(Integer)
    payment_status = Column(Integer, default=0)
    order_id = Column(String(50))
    amount = Column(Integer, default=0)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    payment_method = Column(String(50), default="Cash")
    is_paid = Column(Boolean, default=False)

    # New fields
    last_visited_doctor_id = Column(Integer, ForeignKey("doctors.id"))
    last_visited_date = Column(Date)

    # Relationships
    facility = relationship("Facility", back_populates="patients")
    appointments = relationship("Appointment", back_populates="patient")
    medical_records = relationship("MedicalRecord", back_populates="patient")
    medical_documents = relationship("MedicalDocument", back_populates="patient")
    last_visited_doctor = relationship("Doctors", foreign_keys=[last_visited_doctor_id])

class UserMaster(Base):
    __tablename__ = "usermaster"

    user_id = Column(Integer, primary_key=True, index=True)
    UserName = Column(String(50), nullable=False)
    Password = Column(String(100), nullable=False)
    Role = Column(String(20), nullable=False)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)

    facility = relationship("Facility", back_populates="users")

class Admin(Base):
    """
    Super Admin Model - Fixed version
    Primary Key: username
    """
    __tablename__ = "admin"

    username = Column(String(50), primary_key=True, index=True)
    hashed_pass = Column(String(255), nullable=False)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)

    # Relationships
    facility = relationship("Facility")

class DoctorSchedule(Base):
    __tablename__ = "doctor_schedule"

    facility_id = Column(Integer, ForeignKey("facility.facility_id"), primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), primary_key=True)
    start_date = Column(Date, primary_key=True)
    end_date = Column(Date, primary_key=True)
    week_day = Column(String(10), primary_key=True)
    window_num = Column(Integer, primary_key=True)
    slot_start_time = Column(Time, nullable=False)
    slot_end_time = Column(Time, nullable=False)
    total_slots = Column(String(50), nullable=True)
    slot_duration_minutes = Column(Integer, nullable=False, default=15)
    availability_flag = Column(String(1), nullable=False, default='A')  # 'A' = Available, 'L' = Leave


    facility = relationship("Facility", back_populates="doctor_schedules")
    doctor = relationship("Doctors", back_populates="doctor_schedules")
    __table_args__ = (
        CheckConstraint("availability_flag IN ('A', 'L')", name="check_availability_flag"),
        Index("idx_doctor_schedule_availability", "facility_id", "doctor_id", "availability_flag"),
    )


class DoctorBookedSlots(Base):
    __tablename__ = "doctor_booked_slots"

    DCID = Column(Integer, primary_key=True, index=True, autoincrement=True)
    Doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    Facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False, index=True)
    Slot_date = Column(Date, nullable=False, index=True)
    Start_Time = Column(Time, nullable=False)
    End_Time = Column(Time, nullable=False)
    Booked_status = Column(String(20), nullable=False, default="Not Booked")

    # Relationships
    doctor = relationship("Doctors", back_populates="booked_slots")
    facility = relationship("Facility", back_populates="booked_slots")
    appointments = relationship("Appointment", back_populates="booked_slot")

    _table_args_ = (
        CheckConstraint("Start_Time < End_Time", name="check_time_order"),
        CheckConstraint("Booked_status IN ('Booked','Not Booked')", name="check_booked_status"),
        Index("idx_doctor_facility_date", "Doctor_id", "Facility_id", "Slot_date"),
        UniqueConstraint(
            "Doctor_id", "Facility_id", "Slot_date", "Start_Time",
            name="unique_doctor_slot"
        ),
    )

class Appointment(Base):
    __tablename__ = "appointment"

    appointment_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False, index=True)
    DCID = Column(Integer, ForeignKey("doctor_booked_slots.DCID"), nullable=False, index=True)

    payment_method = Column(String(50), default="Cash")
    payment_status = Column(Boolean, nullable=False, default=False)
    payment_comments = Column(Text)
    AppointmentDate = Column(Date, nullable=False, index=True)
    AppointmentTime = Column(Time, nullable=False)
    Reason = Column(String(200), nullable=False)
    CheckinTime = Column(DateTime)
    Cancelled = Column(Boolean, nullable=False, default=False)
    TokenID = Column(String(20))
    AppointmentMode = Column(String(50), nullable=False)
    AppointmentStatus = Column(String(50), nullable=False, default="Scheduled")

    # Relationships
    patient = relationship("Patients", back_populates="appointments")
    doctor = relationship("Doctors", back_populates="appointments")
    facility = relationship("Facility", back_populates="appointments")
    booked_slot = relationship("DoctorBookedSlots", back_populates="appointments")

    _table_args_ = (
        CheckConstraint("AppointmentMode IN ('a','A','w','W')", name="check_appointment_mode"),
        CheckConstraint("AppointmentStatus IN ('Scheduled','Waiting','Completed','Cancelled')",
                        name="check_appointment_status"),
        CheckConstraint(
            "payment_method IN ('Cash','Debit Card','Credit Card','UPI','Net Banking')",
            name="check_payment_method"
        ),
        Index("idx_patient_date", "patient_id", "AppointmentDate"),
        Index("idx_doctor_date", "doctor_id", "AppointmentDate"),
        Index("idx_facility_date", "facility_id", "AppointmentDate"),
        UniqueConstraint("TokenID", "facility_id", "AppointmentDate", name="uq_token_facility_date"),
    )

class MedicalRecord(Base):
    __tablename__ = "medical_record"

    record_id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"))
    Diagnosis = Column(String(500))
    Treatment = Column(String(500))
    Medicine_Prescription = Column(String(1000))
    Lab_Prescription = Column(String(1000))
    RecordDate = Column(DateTime, default=func.now())
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)

    patient = relationship("Patients", back_populates="medical_records")
    doctor = relationship("Doctors", back_populates="medical_records")
    appointment = relationship("Appointment")
    facility = relationship("Facility")

class Billing(Base):
    __tablename__ = "billing"

    bill_id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"), nullable=False)
    Amount = Column(Integer, nullable=False)
    BillDate = Column(DateTime, default=func.now())
    PaymentStatus = Column(String(20), nullable=False)
    PaymentMode = Column(String(100))
    TransactionID = Column(String(50))
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)

    appointment = relationship("Appointment")
    facility = relationship("Facility")

class MedicalDocument(Base):
    __tablename__ = "medical_document"

    document_id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"))
    patient_id = Column(Integer, ForeignKey("patients.id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    DocumentType = Column(String(100))
    DocumentPath = Column(String(255))
    facility_id = Column(Integer, ForeignKey("facility.facility_id"))

    appointment = relationship("Appointment")
    patient = relationship("Patients", back_populates="medical_documents")
    doctor = relationship("Doctors", back_populates="medical_documents")
    facility = relationship("Facility")

class PatientDiagnosis(Base):
    __tablename__ = "patient_diagnosis"

    diagnosis_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    DATE = Column(Date, nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    VITAL_BP = Column(String(50))
    VITAL_HR = Column(String(50))
    VITAL_TEMP = Column(String(50))
    VITAL_SPO2 = Column(String(50))
    CHIEF_COMPLAINT = Column(Text)
    ASSESSMENT_NOTES = Column(Text)
    TREATMENT_PLAN = Column(Text)
    RECOMM_TESTS = Column(Text)
    FOLLOWUP_DATE = Column(Date)
    weight = Column(String(50))
    height = Column(String(50))

    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    appointment = relationship("Appointment")
    doctor = relationship("Doctors")

    _table_args_ = (
        Index("idx_patient_diagnosis_date", "patient_id", "DATE"),
        Index("idx_facility_patient", "facility_id", "patient_id"),
    )

class PatientReports(Base):
    __tablename__ = "patient_reports"

    upload_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    DATE = Column(Date, nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"))
    diagnosis_id = Column(Integer, ForeignKey("patient_diagnosis.diagnosis_id"))
    FILENAME = Column(Text, nullable=False)
    FILE_BLOB = Column(sa.LargeBinary)

    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    appointment = relationship("Appointment")
    diagnosis = relationship("PatientDiagnosis")

    _table_args_ = (
        Index("idx_patient_reports_facility", "facility_id"),
        Index("idx_patient_reports_patient", "patient_id"),
        Index("idx_patient_reports_date", "DATE"),
        Index("idx_patient_reports_appointment", "appointment_id"),
    )