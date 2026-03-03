
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Date, Integer, String, ForeignKey, DateTime, Time, Boolean, Numeric, func, CheckConstraint, Index, UniqueConstraint, Text,LargeBinary
from database import Base
import sqlalchemy as sa

class Facility(Base):
    __tablename__ = "facility"

    facility_id = Column(Integer, primary_key=True, index=True)
    FacilityName = Column(String(200), nullable=False)
    FacilityAddress = Column(String(500))
    ABDM_NHFR_ID = Column(String(100))
    TaxNumber = Column(String(50))
    phone_number = Column(String(20))
    email = Column(String(255))
    # Logo fields
    logo_filename = Column(String(255))
    logo_blob = Column(LargeBinary)

    # Relationships
    users = relationship("UserMaster", back_populates="facility")
    patients = relationship("Patients", back_populates="facility")
    doctors = relationship("Doctors", back_populates="facility")
    doctor_schedules = relationship("DoctorSchedule", back_populates="facility")
    booked_slots = relationship("DoctorBookedSlots", back_populates="facility")
    appointments = relationship("Appointment", back_populates="facility")
    templates = relationship("Template", back_populates="facility")
    drugs = relationship("DrugMaster", back_populates="facility")
    symptoms = relationship("SymptomMaster", back_populates="facility")
    lab_tests = relationship("LabMaster", back_populates="facility")
    diagnosis_symptoms = relationship("DiagnosisSymptoms", back_populates="facility")
    diagnosis_prescriptions = relationship("DiagnosisPrescription", back_populates="facility")
    diagnosis_lab_tests = relationship("DiagnosisLabTests", back_populates="facility")
    diagnosis_procedures = relationship("DiagnosisProcedures", back_populates="facility")
    patient_diagnoses = relationship("PatientDiagnosis", back_populates="facility")
    patient_reports = relationship("PatientReports", back_populates="facility")

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
    patient_diagnoses = relationship("PatientDiagnosis", foreign_keys="[PatientDiagnosis.doctor_id]", back_populates="doctor")

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
    patient_diagnoses = relationship("PatientDiagnosis", back_populates="patient")

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
    is_review = Column(Boolean, default=False, nullable=True)

    # Relationships
    patient = relationship("Patients", back_populates="appointments")
    doctor = relationship("Doctors", back_populates="appointments")
    facility = relationship("Facility", back_populates="appointments")
    booked_slot = relationship("DoctorBookedSlots", back_populates="appointments")
    patient_diagnoses = relationship("PatientDiagnosis", back_populates="appointment")

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



# ==================== MASTER TABLES ====================

class Template(Base):
    """Master template table for diagnosis templates"""
    __tablename__ = "template"
    
    template_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    template_name = Column(String(255), nullable=False)
    template_type = Column(String(50), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    deleted_by = Column(Integer, ForeignKey("doctors.id"))
    deleted_at = Column(DateTime)
    
    # Relationships
    facility = relationship("Facility")
    symptoms = relationship("SymptomTemplate", back_populates="template", cascade="all, delete-orphan")
    prescriptions = relationship("PrescriptionTemplate", back_populates="template", cascade="all, delete-orphan")
    lab_tests = relationship("LabTemplate", back_populates="template", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_template_facility", "facility_id"),
        Index("idx_template_type", "template_type"),
        Index("idx_template_active", "is_active"),
        Index("idx_template_deleted", "is_deleted"),
        Index("idx_template_name_facility", "template_name", "facility_id", "is_deleted", unique=True),
        CheckConstraint("LENGTH(template_name) >= 3", name="chk_template_name_length"),
        CheckConstraint("LENGTH(template_type) >= 2", name="chk_template_type_length"),
    )


class DrugMaster(Base):
    """Master table for all medicines/drugs"""
    __tablename__ = "drug_master"
    
    medicine_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    medicine_name = Column(String(255), nullable=False, index=True)
    generic_name = Column(String(255))
    strength = Column(String(100))
    medicine_type = Column(String(100))
    composition_text = Column(Text)
    price = Column(Numeric(10, 2))
    manufacturer = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    deleted_by = Column(Integer, ForeignKey("doctors.id"))
    deleted_at = Column(DateTime)
    
    # Relationships
    facility = relationship("Facility")
    prescription_templates = relationship("PrescriptionTemplate", back_populates="medicine")
    diagnosis_prescriptions = relationship("DiagnosisPrescription", back_populates="medicine")
    
    __table_args__ = (
        Index("idx_drug_facility", "facility_id"),
        Index("idx_drug_name", "medicine_name"),
        Index("idx_drug_generic", "generic_name"),
        Index("idx_drug_deleted", "is_deleted"),
        CheckConstraint("LENGTH(medicine_name) >= 2", name="chk_medicine_name_length"),
        CheckConstraint("price IS NULL OR price >= 0", name="chk_drug_price_positive"),
    )


class SymptomMaster(Base):
    """Master table for all symptoms"""
    __tablename__ = "symptom_master"
    
    symptom_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    symptom_name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    deleted_by = Column(Integer, ForeignKey("doctors.id"))
    deleted_at = Column(DateTime)
    
    # Relationships
    facility = relationship("Facility")
    symptom_templates = relationship("SymptomTemplate", back_populates="symptom")
    diagnosis_symptoms = relationship("DiagnosisSymptoms", back_populates="symptom")
    
    __table_args__ = (
        Index("idx_symptom_facility", "facility_id"),
        Index("idx_symptom_deleted", "is_deleted"),
        Index("idx_symptom_name_facility", "symptom_name", "facility_id", "is_deleted", unique=True),
        CheckConstraint("LENGTH(symptom_name) >= 2", name="chk_symptom_name_length"),
    )


class LabMaster(Base):
    """Master table for all lab tests"""
    __tablename__ = "lab_master"
    
    test_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    test_name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    prerequisite_text = Column(Text)
    price = Column(Numeric(10, 2))
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    deleted_by = Column(Integer, ForeignKey("doctors.id"))
    deleted_at = Column(DateTime)
    
    # Relationships
    facility = relationship("Facility")
    lab_templates = relationship("LabTemplate", back_populates="test")
    diagnosis_lab_tests = relationship("DiagnosisLabTests", back_populates="test")
    
    __table_args__ = (
        Index("idx_lab_facility", "facility_id"),
        Index("idx_lab_deleted", "is_deleted"),
        Index("idx_lab_name_facility", "test_name", "facility_id", "is_deleted", unique=True),
        CheckConstraint("LENGTH(test_name) >= 2", name="chk_test_name_length"),
        CheckConstraint("price IS NULL OR price >= 0", name="chk_lab_price_positive"),
    )


# ==================== TEMPLATE JUNCTION TABLES ====================

class SymptomTemplate(Base):
    """Links symptoms to templates"""
    __tablename__ = "symptom_template"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("template.template_id", ondelete="CASCADE"), nullable=False)
    symptom_id = Column(Integer, ForeignKey("symptom_master.symptom_id"), nullable=False)
    default_duration_days = Column(Integer)
    default_remarks = Column(Text)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    template = relationship("Template", back_populates="symptoms")
    symptom = relationship("SymptomMaster", back_populates="symptom_templates")
    
    __table_args__ = (
        Index("idx_symptom_template", "template_id", "symptom_id", unique=True),
        CheckConstraint("default_duration_days IS NULL OR default_duration_days > 0", name="chk_symptom_duration_positive"),
    )


class PrescriptionTemplate(Base):
    """Links medicines to templates with dosage info"""
    __tablename__ = "prescription_template"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("template.template_id", ondelete="CASCADE"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("drug_master.medicine_id"), nullable=False)
    morning_dosage = Column(String(50))
    afternoon_dosage = Column(String(50))
    night_dosage = Column(String(50))
    food_timing = Column(String(50))
    duration_days = Column(Integer)
    special_instructions = Column(Text)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    template = relationship("Template", back_populates="prescriptions")
    medicine = relationship("DrugMaster", back_populates="prescription_templates")
    
    __table_args__ = (
        Index("idx_prescription_template", "template_id", "medicine_id", unique=True),
        CheckConstraint("duration_days IS NULL OR duration_days > 0", name="chk_prescription_duration_positive"),
    )


class LabTemplate(Base):
    """Links lab tests to templates"""
    __tablename__ = "lab_template"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("template.template_id", ondelete="CASCADE"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_master.test_id"), nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    template = relationship("Template", back_populates="lab_tests")
    test = relationship("LabMaster", back_populates="lab_templates")
    
    __table_args__ = (
        Index("idx_lab_template", "template_id", "test_id", unique=True),
    )


# ==================== ACTUAL DIAGNOSIS DATA TABLES ====================

class DiagnosisSymptoms(Base):
    """Actual symptoms recorded for a patient diagnosis"""
    __tablename__ = "diagnosis_symptoms"
    
    patient_symptom_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    diagnosis_id = Column(Integer, ForeignKey("patient_diagnosis.diagnosis_id", ondelete="CASCADE"), nullable=False)
    symptom_id = Column(Integer, ForeignKey("symptom_master.symptom_id"), nullable=True)
    free_text_symptom = Column(String(255), nullable=True)  # ← new field
    duration_days = Column(Integer)
    remarks = Column(Text)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    diagnosis = relationship("PatientDiagnosis", back_populates="symptoms")
    symptom = relationship("SymptomMaster", back_populates="diagnosis_symptoms")
    
    __table_args__ = (
        Index("idx_diagnosis_symptom", "diagnosis_id", "symptom_id"),
        Index("idx_diagnosis_symptom_facility", "facility_id"),
        CheckConstraint("duration_days IS NULL OR duration_days > 0", name="chk_diagnosis_symptom_duration_positive"),
        CheckConstraint(
            "symptom_id IS NOT NULL OR free_text_symptom IS NOT NULL",
            name="chk_symptom_id_or_free_text"  # ← ensures at least one is provided
        ),
    )


class DiagnosisPrescription(Base):
    """Actual prescriptions for a patient diagnosis"""
    __tablename__ = "diagnosis_prescription"
    
    prescription_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    diagnosis_id = Column(Integer, ForeignKey("patient_diagnosis.diagnosis_id", ondelete="CASCADE"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("drug_master.medicine_id"), nullable=False)
    morning_dosage = Column(String(50))
    afternoon_dosage = Column(String(50))
    night_dosage = Column(String(50))
    food_timing = Column(String(50))
    duration_days = Column(Integer)
    special_instructions = Column(Text)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    diagnosis = relationship("PatientDiagnosis", back_populates="prescriptions")
    medicine = relationship("DrugMaster", back_populates="diagnosis_prescriptions")
    
    __table_args__ = (
        Index("idx_diagnosis_prescription", "diagnosis_id", "medicine_id"),
        Index("idx_diagnosis_prescription_facility", "facility_id"),
        CheckConstraint("duration_days IS NULL OR duration_days > 0", name="chk_diagnosis_prescription_duration_positive"),
    )


class DiagnosisLabTests(Base):
    """Actual lab tests ordered for a patient diagnosis"""
    __tablename__ = "diagnosis_lab_tests"
    
    lab_test_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    diagnosis_id = Column(Integer, ForeignKey("patient_diagnosis.diagnosis_id", ondelete="CASCADE"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_master.test_id"), nullable=False)
    prerequisite_text = Column(Text)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    diagnosis = relationship("PatientDiagnosis", back_populates="lab_tests")
    test = relationship("LabMaster", back_populates="diagnosis_lab_tests")
    
    __table_args__ = (
        Index("idx_diagnosis_lab_test", "diagnosis_id", "test_id"),
        Index("idx_diagnosis_lab_test_facility", "facility_id"),
    )


class DiagnosisProcedures(Base):
    """Procedures recommended/performed for a patient diagnosis"""
    __tablename__ = "diagnosis_procedures"
    
    procedure_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    diagnosis_id = Column(Integer, ForeignKey("patient_diagnosis.diagnosis_id", ondelete="CASCADE"), nullable=False)
    procedure_text = Column(Text, nullable=False)
    price = Column(Numeric(10, 2))
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    diagnosis = relationship("PatientDiagnosis", back_populates="procedures")
    
    __table_args__ = (
        Index("idx_diagnosis_procedure", "diagnosis_id"),
        Index("idx_diagnosis_procedure_facility", "facility_id"),
        CheckConstraint("LENGTH(procedure_text) >= 5", name="chk_procedure_text_length"),
        CheckConstraint("price IS NULL OR price >= 0", name="chk_procedure_price_positive"),
    )


# ==================== UPDATED PATIENT DIAGNOSIS TABLE ====================

class PatientDiagnosis(Base):
    """Updated patient diagnosis table"""
    __tablename__ = "patient_diagnosis"
    
    diagnosis_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointment.appointment_id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    
    # Vitals
    vital_bp = Column(String(50))
    vital_hr = Column(String(50))
    vital_temp = Column(String(50))
    vital_spo2 = Column(String(50))
    height = Column(String(50))
    weight = Column(String(50))
    
    # Chief complaint and template info
    chief_complaint = Column(Text)
    template_id = Column(Integer, ForeignKey("template.template_id"))
    
    # Follow-up
    followup_date = Column(Date)
    
    # Soft delete
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    deleted_by = Column(Integer, ForeignKey("doctors.id"))
    deleted_at = Column(DateTime)
    
    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    appointment = relationship("Appointment")
    doctor = relationship("Doctors",foreign_keys=[doctor_id])
    template = relationship("Template")
    
    # One-to-many relationships with actual diagnosis data
    symptoms = relationship("DiagnosisSymptoms", back_populates="diagnosis", cascade="all, delete-orphan")
    prescriptions = relationship("DiagnosisPrescription", back_populates="diagnosis", cascade="all, delete-orphan")
    lab_tests = relationship("DiagnosisLabTests", back_populates="diagnosis", cascade="all, delete-orphan")
    procedures = relationship("DiagnosisProcedures", back_populates="diagnosis", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_patient_diagnosis_date", "patient_id", "date"),
        Index("idx_facility_patient", "facility_id", "patient_id"),
        Index("idx_diagnosis_doctor", "doctor_id", "date"),
        Index("idx_diagnosis_deleted", "is_deleted"),
        CheckConstraint("followup_date IS NULL OR followup_date > date", name="chk_followup_after_diagnosis"),
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
    file_title = Column(String, nullable=True)
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


class HMSParams(Base):
    """HMS Parameters table for storing system configuration parameters"""
    __tablename__ = "hms_params"
    
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), primary_key=True)
    param_name = Column(String(100), primary_key=True)
    param_value = Column(String(500), nullable=False)
    
    # Relationship
    facility = relationship("Facility")
    
    __table_args__ = (
        Index("idx_hms_params_facility", "facility_id"),
        Index("idx_hms_params_name", "param_name"),
        CheckConstraint("LENGTH(param_name) >= 2", name="chk_param_name_length"),
    )
# ==================== BILLING TABLES ====================
# Add these classes to model.py before the last line
# ==================== BILLING TABLES ====================

class LabBill(Base):
    """Lab test bills"""
    __tablename__ = "lab_bill"
    
    lab_bill_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    token_number = Column(String(20), nullable=False)
    token_date = Column(Date, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    bill_date = Column(Date, nullable=False, default=func.current_date())
    subtotal = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    paid_amount = Column(Numeric(10, 2), default=0)
    payment_status = Column(String(20), default='Pending')  # Pending, Partial, Paid
    payment_method = Column(String(50))
    payment_date = Column(DateTime)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    items = relationship("LabBillItem", back_populates="lab_bill", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_lab_bill_token", "facility_id", "token_number", "token_date"),
        Index("idx_lab_bill_patient", "patient_id"),
        Index("idx_lab_bill_date", "bill_date"),
        Index("idx_lab_bill_status", "payment_status"),
        CheckConstraint("payment_status IN ('Pending','Partial','Paid')", name="chk_lab_payment_status"),
        CheckConstraint("subtotal >= 0", name="chk_lab_subtotal_positive"),
        CheckConstraint("total_amount >= 0", name="chk_lab_total_positive"),
        CheckConstraint("paid_amount >= 0", name="chk_lab_paid_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_lab_discount_range"),
    )


class LabBillItem(Base):
    """Individual items in a lab bill"""
    __tablename__ = "lab_bill_item"
    
    lab_bill_item_id = Column(Integer, primary_key=True, index=True)
    lab_bill_id = Column(Integer, ForeignKey("lab_bill.lab_bill_id", ondelete="CASCADE"), nullable=False)
    test_id = Column(Integer, ForeignKey("lab_master.test_id"), nullable=False)
    test_name = Column(String(255), nullable=False)
    remarks = Column(Text)  # e.g., "Empty Stomach"
    price = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    final_price = Column(Numeric(10, 2), nullable=False)
    
    # Relationships
    lab_bill = relationship("LabBill", back_populates="items")
    test = relationship("LabMaster")
    
    __table_args__ = (
        Index("idx_lab_bill_item", "lab_bill_id", "test_id"),
        CheckConstraint("price >= 0", name="chk_lab_item_price_positive"),
        CheckConstraint("final_price >= 0", name="chk_lab_item_final_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_lab_item_discount_range"),
    )


class PharmacyBill(Base):
    """Pharmacy/medicine bills"""
    __tablename__ = "pharmacy_bill"
    
    pharmacy_bill_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    token_number = Column(String(20), nullable=False)
    token_date = Column(Date, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    bill_date = Column(Date, nullable=False, default=func.current_date())
    subtotal = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    paid_amount = Column(Numeric(10, 2), default=0)
    payment_status = Column(String(20), default='Pending')  # Pending, Partial, Paid
    payment_method = Column(String(50))
    payment_date = Column(DateTime)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    items = relationship("PharmacyBillItem", back_populates="pharmacy_bill", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_pharmacy_bill_token", "facility_id", "token_number", "token_date"),
        Index("idx_pharmacy_bill_patient", "patient_id"),
        Index("idx_pharmacy_bill_date", "bill_date"),
        Index("idx_pharmacy_bill_status", "payment_status"),
        CheckConstraint("payment_status IN ('Pending','Partial','Paid')", name="chk_pharmacy_payment_status"),
        CheckConstraint("subtotal >= 0", name="chk_pharmacy_subtotal_positive"),
        CheckConstraint("total_amount >= 0", name="chk_pharmacy_total_positive"),
        CheckConstraint("paid_amount >= 0", name="chk_pharmacy_paid_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_pharmacy_discount_range"),
    )


class PharmacyBillItem(Base):
    """Individual items in a pharmacy bill"""
    __tablename__ = "pharmacy_bill_item"
    
    pharmacy_bill_item_id = Column(Integer, primary_key=True, index=True)
    pharmacy_bill_id = Column(Integer, ForeignKey("pharmacy_bill.pharmacy_bill_id", ondelete="CASCADE"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("drug_master.medicine_id"), nullable=False)
    medicine_name = Column(String(255), nullable=False)
    generic_name = Column(String(255))
    strength = Column(String(100))
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    final_price = Column(Numeric(10, 2), nullable=False)
    
    # Dosage information
    dosage_info = Column(String(50))  # e.g., "M-A-N" (Morning-Afternoon-Night)
    food_timing = Column(String(50))  # e.g., "After Food"
    duration_days = Column(Integer)
    
    # Relationships
    pharmacy_bill = relationship("PharmacyBill", back_populates="items")
    medicine = relationship("DrugMaster")
    
    __table_args__ = (
        Index("idx_pharmacy_bill_item", "pharmacy_bill_id", "medicine_id"),
        CheckConstraint("quantity > 0", name="chk_pharmacy_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="chk_pharmacy_item_price_positive"),
        CheckConstraint("total_price >= 0", name="chk_pharmacy_item_total_positive"),
        CheckConstraint("final_price >= 0", name="chk_pharmacy_item_final_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_pharmacy_item_discount_range"),
        CheckConstraint("duration_days IS NULL OR duration_days > 0", name="chk_pharmacy_item_duration_positive"),
    )


class ProcedureBill(Base):
    """Procedure bills"""
    __tablename__ = "procedure_bill"
    
    procedure_bill_id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facility.facility_id"), nullable=False)
    token_number = Column(String(20), nullable=False)
    token_date = Column(Date, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    bill_date = Column(Date, nullable=False, default=func.current_date())
    subtotal = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    paid_amount = Column(Numeric(10, 2), default=0)
    payment_status = Column(String(20), default='Pending')  # Pending, Partial, Paid
    payment_method = Column(String(50))
    payment_date = Column(DateTime)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("doctors.id"))
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    facility = relationship("Facility")
    patient = relationship("Patients")
    items = relationship("ProcedureBillItem", back_populates="procedure_bill", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_procedure_bill_token", "facility_id", "token_number", "token_date"),
        Index("idx_procedure_bill_patient", "patient_id"),
        Index("idx_procedure_bill_date", "bill_date"),
        Index("idx_procedure_bill_status", "payment_status"),
        CheckConstraint("payment_status IN ('Pending','Partial','Paid')", name="chk_procedure_payment_status"),
        CheckConstraint("subtotal >= 0", name="chk_procedure_subtotal_positive"),
        CheckConstraint("total_amount >= 0", name="chk_procedure_total_positive"),
        CheckConstraint("paid_amount >= 0", name="chk_procedure_paid_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_procedure_discount_range"),
    )


class ProcedureBillItem(Base):
    """Individual items in a procedure bill"""
    __tablename__ = "procedure_bill_item"
    
    procedure_bill_item_id = Column(Integer, primary_key=True, index=True)
    procedure_bill_id = Column(Integer, ForeignKey("procedure_bill.procedure_bill_id", ondelete="CASCADE"), nullable=False)
    procedure_text = Column(Text, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    final_price = Column(Numeric(10, 2), nullable=False)
    
    # Relationships
    procedure_bill = relationship("ProcedureBill", back_populates="items")
    
    __table_args__ = (
        Index("idx_procedure_bill_item", "procedure_bill_id"),
        CheckConstraint("price >= 0", name="chk_procedure_item_price_positive"),
        CheckConstraint("final_price >= 0", name="chk_procedure_item_final_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="chk_procedure_item_discount_range"),
        CheckConstraint("LENGTH(procedure_text) >= 5", name="chk_procedure_item_text_length"),
    )