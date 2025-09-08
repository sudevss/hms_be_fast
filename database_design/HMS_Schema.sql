-- =====================================================
-- Healthcare Management System Database Schema (updated)
-- Generated from SQLAlchemy models
-- =====================================================

-- CREATE DATABASE healthcare_system;
-- USE healthcare_system;

-- =====================================================
-- 1. FACILITY
-- =====================================================
CREATE TABLE facility (
    FacilityID      INTEGER NOT NULL AUTO_INCREMENT,
    FacilityName    VARCHAR(200) NOT NULL,
    FacilityAddress VARCHAR(500),
    ABDM_NHFR_ID    VARCHAR(100),
    TaxNumber       VARCHAR(50),
    PRIMARY KEY (FacilityID),
    INDEX idx_facility_id (FacilityID)
);

-- =====================================================
-- 2. DOCTORS
-- =====================================================
CREATE TABLE doctors (
    id              INTEGER NOT NULL AUTO_INCREMENT,
    firstname       VARCHAR(100) NOT NULL,
    lastname        VARCHAR(100) NOT NULL,
    specialization  VARCHAR(100),
    phone_number    VARCHAR(20),
    email           VARCHAR(200),
    consultation_fee DECIMAL(10,2),
    ABDM_NHPR_id    VARCHAR(100),
    FacilityID      INTEGER NOT NULL,
    gender          VARCHAR(10),
    age             INTEGER,
    experience      INTEGER,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    INDEX idx_doctors_firstname (firstname),
    INDEX idx_doctors_lastname (lastname),
    INDEX idx_doctors_email (email),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 3. PATIENTS
-- =====================================================
CREATE TABLE patients (
    id                  INTEGER NOT NULL AUTO_INCREMENT,
    firstname           VARCHAR(100) NOT NULL,
    lastname            VARCHAR(100) NOT NULL,
    dob                 DATE,
    age                 INTEGER,
    contact_number      VARCHAR(20) NOT NULL,
    address             VARCHAR(200),
    gender              VARCHAR(10),
    ABDM_ABHA_id        VARCHAR(50),
    email_id            VARCHAR(200) NOT NULL,
    disease             VARCHAR(200),
    room_id             INTEGER,
    payment_status      INTEGER DEFAULT 0,
    order_id            VARCHAR(50),
    amount              INTEGER DEFAULT 0,
    FacilityID          INTEGER NOT NULL,
    payment_method      VARCHAR(50) DEFAULT 'Cash',
    is_paid             BOOLEAN DEFAULT FALSE,
    last_visited_doctor_id INTEGER,
    last_visited_date   DATE,
    PRIMARY KEY (id),
    INDEX idx_patients_firstname (firstname),
    INDEX idx_patients_lastname (lastname),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (last_visited_doctor_id) REFERENCES doctors(id)
);

-- =====================================================
-- 4. USERMASTER
-- =====================================================
CREATE TABLE usermaster (
    UserID      INTEGER NOT NULL AUTO_INCREMENT,
    UserName    VARCHAR(50) NOT NULL,
    Password    VARCHAR(100) NOT NULL,
    Role        VARCHAR(20) NOT NULL,
    FacilityID  INTEGER NOT NULL,
    PRIMARY KEY (UserID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 5. ADMIN
-- =====================================================
CREATE TABLE admin (
    username    VARCHAR(50) NOT NULL,
    hashed_pass VARCHAR(255),
    FacilityID  INTEGER,
    PRIMARY KEY (username),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 6. DOCTOR_SCHEDULE
-- =====================================================
CREATE TABLE doctor_schedule (
    Facility_id     INTEGER NOT NULL,
    Doctor_id       INTEGER NOT NULL,
    Start_Date      DATE    NOT NULL,
    End_Date        DATE    NOT NULL,
    WeekDay         VARCHAR(10) NOT NULL,
    Window_Num      INTEGER NOT NULL,
    Slot_Start_Time TIME    NOT NULL,
    Slot_End_Time   TIME    NOT NULL,
    PRIMARY KEY (Facility_id, Doctor_id, Start_Date, End_Date, WeekDay, Window_Num),
    FOREIGN KEY (Facility_id) REFERENCES facility(FacilityID),
    FOREIGN KEY (Doctor_id) REFERENCES doctors(id)
);

-- =====================================================
-- 7. DOCTOR_BOOKED_SLOTS
-- =====================================================
CREATE TABLE doctor_booked_slots (
    DCID          INTEGER NOT NULL AUTO_INCREMENT,
    Doctor_id     INTEGER NOT NULL,
    Facility_id   INTEGER NOT NULL,
    Slot_date     DATE    NOT NULL,
    Start_Time    TIME    NOT NULL,
    End_Time      TIME    NOT NULL,
    Booked_status VARCHAR(20) NOT NULL DEFAULT 'Not Booked',
    PRIMARY KEY (DCID),
    INDEX idx_doctor_facility_date (Doctor_id, Facility_id, Slot_date),
    UNIQUE KEY unique_doctor_slot (Doctor_id, Facility_id, Slot_date, Start_Time),
    CONSTRAINT check_time_order     CHECK (Start_Time < End_Time),
    CONSTRAINT check_booked_status  CHECK (Booked_status IN ('Booked','Not Booked')),
    FOREIGN KEY (Doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (Facility_id) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 8. APPOINTMENT
-- =====================================================
CREATE TABLE appointment (
    AppointmentID    INTEGER NOT NULL AUTO_INCREMENT,
    PatientID        INTEGER NOT NULL,
    DoctorID         INTEGER NOT NULL,
    FacilityID       INTEGER NOT NULL,
    DCID             INTEGER NOT NULL,
    payment_method   VARCHAR(50) DEFAULT 'Cash',
    AppointmentDate  DATE NOT NULL,
    AppointmentTime  TIME NOT NULL,
    Reason           VARCHAR(200) NOT NULL,
    CheckinTime      DATETIME,
    Cancelled        BOOLEAN NOT NULL DEFAULT FALSE,
    TokenID          VARCHAR(20),
    AppointmentMode  VARCHAR(50) NOT NULL,
    AppointmentStatus VARCHAR(50) NOT NULL DEFAULT 'Scheduled',
    PRIMARY KEY (AppointmentID),
    INDEX idx_patient_date (PatientID, AppointmentDate),
    INDEX idx_doctor_date (DoctorID, AppointmentDate),
    INDEX idx_facility_date (FacilityID, AppointmentDate),
    CONSTRAINT uq_token_facility_date UNIQUE (TokenID, FacilityID, AppointmentDate),
    CONSTRAINT check_appointment_mode   CHECK (AppointmentMode IN ('a','A','w','W')),
    CONSTRAINT check_appointment_status CHECK (AppointmentStatus IN ('Scheduled','Completed','Cancelled')),
    CONSTRAINT check_payment_method     CHECK (payment_method IN ('Cash','Debit Card','Credit Card','UPI','Net Banking')),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (DCID) REFERENCES doctor_booked_slots(DCID)
);

-- =====================================================
-- 9. MEDICAL_RECORD
-- =====================================================
CREATE TABLE medical_record (
    RecordID            INTEGER NOT NULL AUTO_INCREMENT,
    PatientID           INTEGER NOT NULL,
    DoctorID            INTEGER NOT NULL,
    AppointmentID       INTEGER,
    Diagnosis           VARCHAR(500),
    Treatment           VARCHAR(500),
    Medicine_Prescription VARCHAR(1000),
    Lab_Prescription    VARCHAR(1000),
    RecordDate          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FacilityID          INTEGER NOT NULL,
    PRIMARY KEY (RecordID),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 10. BILLING
-- =====================================================
CREATE TABLE billing (
    BillID        INTEGER NOT NULL AUTO_INCREMENT,
    AppointmentID INTEGER NOT NULL,
    Amount        INTEGER NOT NULL,
    BillDate      DATETIME DEFAULT CURRENT_TIMESTAMP,
    PaymentStatus VARCHAR(20) NOT NULL,
    PaymentMode   VARCHAR(100),
    TransactionID VARCHAR(50),
    FacilityID    INTEGER NOT NULL,
    PRIMARY KEY (BillID),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- =====================================================
-- 11. MEDICAL_DOCUMENT
-- =====================================================
CREATE TABLE medical_document (
    DocumentID   INTEGER NOT NULL AUTO_INCREMENT,
    AppointmentID INTEGER,
    PatientID     INTEGER,
    DoctorID      INTEGER,
    DocumentType  VARCHAR(100),
    DocumentPath  VARCHAR(255),
    FacilityID    INTEGER,
    PRIMARY KEY (DocumentID),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);