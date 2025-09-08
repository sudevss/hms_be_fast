-- Healthcare Management System Database Schema
-- Generated from SQLAlchemy models

-- Create database (uncomment if needed)
-- CREATE DATABASE healthcare_system;
-- USE healthcare_system;

-- =====================================================
-- 1. FACILITY TABLE (Root table)
-- =====================================================
CREATE TABLE facility (
    FacilityID INTEGER NOT NULL AUTO_INCREMENT,
    FacilityName VARCHAR(200) NOT NULL,
    FacilityAddress VARCHAR(500),
    ABDM_NHFR_ID VARCHAR(100),
    TaxNumber VARCHAR(50),
    PRIMARY KEY (FacilityID),
    INDEX idx_facility_id (FacilityID)
);

-- =====================================================
-- 2. DOCTORS TABLE
-- =====================================================
CREATE TABLE doctors (
    id INTEGER NOT NULL AUTO_INCREMENT,
    firstname VARCHAR(100) NOT NULL,
    lastname VARCHAR(100) NOT NULL,
    specialization VARCHAR(100),
    phone_number VARCHAR(20),
    email VARCHAR(200),
    consultation_fee DECIMAL(10, 2),
    ABDM_NHPR_id VARCHAR(100),
    FacilityID INTEGER NOT NULL,
    gender VARCHAR(10),
    age INTEGER,
    experience INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    INDEX idx_doctors_id (id),
    INDEX idx_doctors_firstname (firstname),
    INDEX idx_doctors_lastname (lastname),
    INDEX idx_doctors_email (email),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 3. PATIENTS TABLE
-- =====================================================
CREATE TABLE patients (
    id INTEGER NOT NULL AUTO_INCREMENT,
    firstname VARCHAR(100) NOT NULL,
    lastname VARCHAR(100) NOT NULL,
    dob DATE,
    age INTEGER,
    contact_number VARCHAR(20) NOT NULL,
    address VARCHAR(200),
    gender VARCHAR(10),
    ABDM_ABHA_id VARCHAR(50),
    email_id VARCHAR(200) NOT NULL,
    disease VARCHAR(200),
    room_id INTEGER,
    payment_status INTEGER DEFAULT 0,
    order_id VARCHAR(50),
    amount INTEGER DEFAULT 0,
    FacilityID INTEGER NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    is_paid BOOLEAN DEFAULT FALSE,
    last_visited_doctor_id INTEGER,
    last_visited_date DATE,
    PRIMARY KEY (id),
    INDEX idx_patients_id (id),
    INDEX idx_patients_firstname (firstname),
    INDEX idx_patients_lastname (lastname),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (last_visited_doctor_id) REFERENCES doctors(id)
);

-- =====================================================
-- 4. USERMASTER TABLE
-- =====================================================
CREATE TABLE usermaster (
    UserID INTEGER NOT NULL AUTO_INCREMENT,
    UserName VARCHAR(50) NOT NULL,
    Password VARCHAR(100) NOT NULL,
    Role VARCHAR(20) NOT NULL,
    FacilityID INTEGER NOT NULL,
    PRIMARY KEY (UserID),
    INDEX idx_usermaster_id (UserID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 5. ADMIN TABLE
-- =====================================================
CREATE TABLE admin (
    username VARCHAR(50) NOT NULL,
    hashed_pass VARCHAR(255),
    FacilityID INTEGER,
    PRIMARY KEY (username),
    INDEX idx_admin_username (username),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 6. DOCTOR SCHEDULE TABLE
-- =====================================================
CREATE TABLE doctor_schedule (
    Facility_id INTEGER NOT NULL,
    Doctor_id INTEGER NOT NULL,
    Start_Date DATE NOT NULL,
    End_Date DATE NOT NULL,
    WeekDay VARCHAR(10) NOT NULL,
    Window_Num INTEGER NOT NULL,
    Slot_Start_Time TIME NOT NULL,
    Slot_End_Time TIME NOT NULL,
    PRIMARY KEY (Facility_id, Doctor_id, Start_Date, End_Date, WeekDay, Window_Num),
    FOREIGN KEY (Facility_id) REFERENCES facility(FacilityID),
    FOREIGN KEY (Doctor_id) REFERENCES doctors(id)
);

-- =====================================================
-- 7. DOCTOR BOOKED SLOTS TABLE
-- =====================================================
CREATE TABLE doctor_booked_slots (
    DCID INTEGER NOT NULL AUTO_INCREMENT,
    Doctor_id INTEGER NOT NULL,
    Facility_id INTEGER NOT NULL,
    Slot_date DATE NOT NULL,
    Start_Time TIME NOT NULL,
    End_Time TIME NOT NULL,
    Booked_status VARCHAR(20) NOT NULL DEFAULT 'Not Booked',
    PRIMARY KEY (DCID),
    INDEX idx_doctor_booked_slots_id (DCID),
    INDEX idx_doctor_booked_slots_doctor (Doctor_id),
    INDEX idx_doctor_booked_slots_facility (Facility_id),
    INDEX idx_doctor_booked_slots_date (Slot_date),
    INDEX idx_doctor_facility_date (Doctor_id, Facility_id, Slot_date),
    UNIQUE KEY unique_doctor_slot (Doctor_id, Facility_id, Slot_date, Start_Time),
    CONSTRAINT check_time_order CHECK (Start_Time < End_Time),
    CONSTRAINT check_booked_status CHECK (Booked_status IN ('Booked', 'Not Booked')),
    FOREIGN KEY (Doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (Facility_id) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 8. APPOINTMENT TABLE
-- =====================================================
CREATE TABLE appointment (
    AppointmentID INTEGER NOT NULL AUTO_INCREMENT,
    PatientID INTEGER NOT NULL,
    DoctorID INTEGER NOT NULL,
    FacilityID INTEGER NOT NULL,
    DCID INTEGER NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    AppointmentDate DATE NOT NULL,
    AppointmentTime TIME NOT NULL,
    Reason VARCHAR(200) NOT NULL,
    CheckinTime DATETIME,
    Cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    TokenID VARCHAR(20) UNIQUE,
    AppointmentMode VARCHAR(50) NOT NULL,
    AppointmentStatus VARCHAR(50) NOT NULL DEFAULT 'Scheduled',
    PRIMARY KEY (AppointmentID),
    INDEX idx_appointment_id (AppointmentID),
    INDEX idx_appointment_patient (PatientID),
    INDEX idx_appointment_doctor (DoctorID),
    INDEX idx_appointment_facility (FacilityID),
    INDEX idx_appointment_dcid (DCID),
    INDEX idx_appointment_date (AppointmentDate),
    INDEX idx_patient_date (PatientID, AppointmentDate),
    INDEX idx_doctor_date (DoctorID, AppointmentDate),
    INDEX idx_facility_date (FacilityID, AppointmentDate),
    CONSTRAINT check_appointment_mode CHECK (AppointmentMode IN ('a', 'A', 'w', 'W')),
    CONSTRAINT check_appointment_status CHECK (AppointmentStatus IN ('Scheduled', 'Completed', 'Cancelled')),
    CONSTRAINT check_payment_method CHECK (payment_method IN ('Cash', 'Debit Card', 'Credit Card', 'UPI', 'Net Banking')),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (DCID) REFERENCES doctor_booked_slots(DCID)
);

-- =====================================================
-- 9. MEDICAL RECORD TABLE
-- =====================================================
CREATE TABLE medical_record (
    RecordID INTEGER NOT NULL AUTO_INCREMENT,
    PatientID INTEGER NOT NULL,
    DoctorID INTEGER NOT NULL,
    AppointmentID INTEGER,
    Diagnosis VARCHAR(500),
    Treatment VARCHAR(500),
    Medicine_Prescription VARCHAR(1000),
    Lab_Prescription VARCHAR(1000),
    RecordDate DATETIME DEFAULT CURRENT_TIMESTAMP,
    FacilityID INTEGER NOT NULL,
    PRIMARY KEY (RecordID),
    INDEX idx_medical_record_id (RecordID),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 10. BILLING TABLE
-- =====================================================
CREATE TABLE billing (
    BillID INTEGER NOT NULL AUTO_INCREMENT,
    AppointmentID INTEGER NOT NULL,
    Amount INTEGER NOT NULL,
    BillDate DATETIME DEFAULT CURRENT_TIMESTAMP,
    PaymentStatus VARCHAR(20) NOT NULL,
    PaymentMode VARCHAR(100),
    TransactionID VARCHAR(50),
    FacilityID INTEGER NOT NULL,
    PRIMARY KEY (BillID),
    INDEX idx_billing_id (BillID),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 11. MEDICAL DOCUMENT TABLE
-- =====================================================
CREATE TABLE medical_document (
    DocumentID INTEGER NOT NULL AUTO_INCREMENT,
    AppointmentID INTEGER,
    PatientID INTEGER,
    DoctorID INTEGER,
    DocumentType VARCHAR(100),
    DocumentPath VARCHAR(255),
    FacilityID INTEGER,
    PRIMARY KEY (DocumentID),
    INDEX idx_medical_document_id (DocumentID),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- SAMPLE DATA INSERTION (Optional)
-- =====================================================
-- Uncomment to insert sample data

-- INSERT INTO facility (FacilityName, FacilityAddress, ABDM_NHFR_ID, TaxNumber) 
-- VALUES ('City General Hospital', '123 Main St, City', 'NHFR001', 'TAX001');

-- INSERT INTO doctors (firstname, lastname, specialization, phone_number, email, consultation_fee, FacilityID, gender, age, experience)
-- VALUES ('John', 'Doe', 'Cardiology', '1234567890', 'john.doe@hospital.com', 500.00, 1, 'Male', 45, 20);

-- INSERT INTO patients (firstname, lastname, contact_number, email_id, FacilityID, gender, age)
-- VALUES ('Jane', 'Smith', '9876543210', 'jane.smith@email.com', 1, 'Female', 35);

-- =====================================================
-- NOTES:
-- =====================================================
-- 1. All foreign key constraints are properly defined
-- 2. Indexes are created for primary keys and frequently queried columns
-- 3. Check constraints ensure data integrity
-- 4. Default values are set where specified in the SQLAlchemy models
-- 5. AUTO_INCREMENT is used for primary keys
-- 6. Unique constraints are properly defined
-- 7. Composite primary keys are handled correctly