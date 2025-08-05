
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Date, Integer, String, ForeignKey, DateTime, Time, Boolean,DECIMAL,Numeric
from database import Base
import sqlalchemy as sa

class Patients(Base):
    __tablename__ = "patients"  # ✅ Fix: double underscores

    id = Column(Integer, primary_key=True, index=True)
    firstname = Column(String, index=True, nullable=False)
    lastname = Column(String, index=True, nullable=False)
    dob = Column(Date)
    age = Column(Integer)
    contact_number = Column(String, nullable=False)
    address = Column(String)
    gender = Column(String(1))
    ABDM_ABHA_id = Column(String, nullable=True)
    email_id = Column(String, nullable=False)
    disease = Column(String)
    room_id = Column(Integer)
    payment_status = Column(Integer, default=0)
    order_id = Column(String, default=None)
    amount = Column(Integer, default=0)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))
    payment_method = Column(String(50), default="Cash")
    is_paid = Column(Boolean, default=False)

    # ✅ New fields
    last_visited_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    last_visited_date = Column(Date, nullable=True)

    # Relationships
    facility = relationship("Facility", foreign_keys=[FacilityID], back_populates="patients")
    appointments = relationship("Appointment", back_populates="patient")
    medical_records = relationship("MedicalRecord", back_populates="patient")
    medical_documents = relationship("MedicalDocument", back_populates="patient")
    last_visited_doctor = relationship("Doctors", foreign_keys=[last_visited_doctor_id])
class Doctors(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    firstname = Column(String, nullable=False, index=True)
    lastname = Column(String, nullable=False, index=True)
    specialization = Column(String)
    phone_number = Column(String)
    email = Column(String, index=True)
    consultation_fee = Column(Numeric(10, 2))  # Using Numeric for precise currency handling
    ABDM_NHPR_id = Column(String)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    facility = relationship("Facility", foreign_keys=[FacilityID], back_populates="doctors")
    schedules = relationship("DoctorSchedule", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    medical_records = relationship("MedicalRecord", back_populates="doctor")
    medical_documents = relationship("MedicalDocument", back_populates="doctor")

class UserMaster(Base):
    __tablename__ = "usermaster"

    UserID = Column(Integer, primary_key=True, index=True)
    UserName = Column(String(50))
    Password = Column(String(50))
    Role = Column(String(20))
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    facility = relationship("Facility", back_populates="users")

class Admin(Base):
    __tablename__ = "admin"

    username = Column(String, primary_key=True, index=True)
    hashed_pass = Column(String)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    facility = relationship("Facility")

class Facility(Base):
    __tablename__ = "facility"

    FacilityID = Column(Integer, primary_key=True, index=True)
    FacilityName = Column(String(200))
    FacilityAddress = Column(String(500))
    ABDM_NHFR_ID = Column(String(100))
    TaxNumber = Column(String(50))

    users = relationship("UserMaster", back_populates="facility")
    patients = relationship("Patients", foreign_keys="Patients.FacilityID", back_populates="facility")
    doctors = relationship("Doctors", foreign_keys="Doctors.FacilityID", back_populates="facility")
    schedules = relationship("DoctorSchedule", back_populates="facility")
    appointments = relationship("Appointment", back_populates="facility")
class SlotLookup(Base):
    __tablename__ = "slot_lookup"  # <-- Fix underscore bug here

    SlotID = Column(Integer, primary_key=True, index=True)
    SlotSize = Column(String(10))
    SlotStartTime = Column(Time)  # <-- FIXED
    SlotEndTime = Column(Time)    # <-- FIXED
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    facility = relationship("Facility")
class DoctorSchedule(Base):
    __tablename__ = "doctor_schedule"

    ScheduleID = Column(Integer, primary_key=True, index=True)
    DoctorID = Column(Integer, ForeignKey("doctors.id"))
    DayOfWeek = Column(String(10))
    StartTime = Column(String)
    EndTime = Column(String)
    Slotsize = Column(String(10))
    AppointmentsPerSlot = Column(Integer)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    doctor = relationship("Doctors", back_populates="schedules")
    facility = relationship("Facility", back_populates="schedules")

class DoctorCalendar(Base):
    __tablename__ = "doctor_calendar"

    DCID = Column(Integer, primary_key=True, index=True)
    DoctorID = Column(Integer, ForeignKey("doctors.id"))
    Date = Column(Date)
    SlotID = Column(Integer, ForeignKey("slot_lookup.SlotID"))
    FullDayLeave = Column(String(1))
    SlotLeave = Column(String(1))
    TotalAppointments = Column(Integer)
    BookedAppointments = Column(Integer)
    AvailableAppointments = Column(Integer)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    doctor = relationship("Doctors")
    slot = relationship("SlotLookup")

class Appointment(Base):
    __tablename__ = "appointment"

    AppointmentID = Column(Integer, primary_key=True, index=True)
    PatientID = Column(Integer, ForeignKey("patients.id"), nullable=False)
    DoctorID = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"), nullable=False)
    DCID = Column(Integer, ForeignKey("doctor_calendar.DCID"), nullable=False)
    payment_method = Column(String(50), default="Cash")

    AppointmentDate = Column(Date, nullable=False)
    AppointmentTime = Column(Time, nullable=False)
    Reason = Column(String(100), nullable=False)
    CheckinTime = Column(DateTime, nullable=True)
    Cancelled = Column(Boolean, nullable=False, default=False, server_default=sa.sql.expression.false())
    
    # ✅ Corrected from Integer → String
    TokenID = Column(String(20), nullable=True)

    AppointmentMode = Column(String(50), nullable=False)
    AppointmentStatus = Column(String(50), nullable=True, default="Scheduled")

    # Relationships
    patient = relationship("Patients", back_populates="appointments")
    doctor = relationship("Doctors", back_populates="appointments")
    facility = relationship("Facility", back_populates="appointments")
    calendar = relationship("DoctorCalendar")

class MedicalRecord(Base):
    __tablename__ = "medical_record"

    RecordID = Column(Integer, primary_key=True, index=True)
    PatientID = Column(Integer, ForeignKey("patients.id"))
    DoctorID = Column(Integer, ForeignKey("doctors.id"))
    AppointmentID = Column(Integer, ForeignKey("appointment.AppointmentID"))
    Diagnosis = Column(String(100))
    Treatment = Column(String(100))
    Medicine_Prescription = Column(String(100))
    Lab_Prescription = Column(String(100))
    RecordDate = Column(DateTime)
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    patient = relationship("Patients", back_populates="medical_records")
    doctor = relationship("Doctors", back_populates="medical_records")
    appointment = relationship("Appointment")
    facility = relationship("Facility")

class Billing(Base):
    __tablename__= "billing"

    BillID = Column(Integer, primary_key=True, index=True)
    AppointmentID = Column(Integer, ForeignKey("appointment.AppointmentID"))
    Amount = Column(Integer)
    BillDate = Column(DateTime)
    PaymentStatus = Column(String(20))
    PaymentMode = Column(String(100))
    TransactionID = Column(String(20))
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    appointment = relationship("Appointment")
    facility = relationship("Facility")

class MedicalDocument(Base):
    __tablename__= "medical_document"

    DocumentID = Column(Integer, primary_key=True, index=True)
    AppointmentID = Column(Integer, ForeignKey("appointment.AppointmentID"))
    PatientID = Column(Integer, ForeignKey("patients.id"))
    DoctorID = Column(Integer, ForeignKey("doctors.id"))
    DocumentType = Column(String(100))
    DocumentPath = Column(String(100))
    FacilityID = Column(Integer, ForeignKey("facility.FacilityID"))

    appointment = relationship("Appointment")
    patient = relationship("Patients", back_populates="medical_documents")
    doctor = relationship("Doctors", back_populates="medical_documents")
    facility = relationship("Facility")