-- Database Schema SQL

-- Facility table
CREATE TABLE facility (
    FacilityID INTEGER PRIMARY KEY,
    FacilityName VARCHAR(200),
    FacilityAddress VARCHAR(500),
    ABDM_NHFR_ID VARCHAR(100),
    TaxNumber VARCHAR(50)
);

-- UserMaster table
CREATE TABLE usermaster (
    UserID INTEGER PRIMARY KEY,
    UserName VARCHAR(50),
    Password VARCHAR(50),
    Role VARCHAR(20),
    FacilityID INTEGER,
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- Admin table
CREATE TABLE admin (
    username VARCHAR PRIMARY KEY,
    hashed_pass VARCHAR,
    FacilityID INTEGER,
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- Doctors table
CREATE TABLE doctors (
    id INTEGER PRIMARY KEY,
    firstname VARCHAR NOT NULL,
    lastname VARCHAR NOT NULL,
    specialization VARCHAR,
    phone_number VARCHAR,
    email VARCHAR,
    consultation_fee DECIMAL(10,2),
    ABDM_NHPR_id VARCHAR,
    FacilityID INTEGER,
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- Patients table
CREATE TABLE patients (
    id INTEGER PRIMARY KEY,
    firstname VARCHAR NOT NULL,
    lastname VARCHAR NOT NULL,
    dob DATE,
    age INTEGER,
    contact_number VARCHAR NOT NULL,
    address VARCHAR,
    gender VARCHAR(1),
    ABDM_ABHA_id VARCHAR,
    email_id VARCHAR NOT NULL,
    disease VARCHAR,
    room_id INTEGER,
    payment_status INTEGER DEFAULT 0,
    order_id VARCHAR DEFAULT NULL,
    amount INTEGER DEFAULT 0,
    FacilityID INTEGER,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    is_paid BOOLEAN DEFAULT FALSE,
    last_visited_doctor_id INTEGER,
    last_visited_date DATE,
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (last_visited_doctor_id) REFERENCES doctors(id)
);

-- SlotLookup table
CREATE TABLE slot_lookup (
    SlotID INTEGER PRIMARY KEY,
    SlotSize VARCHAR(10),
    SlotStartTime TIME,
    SlotEndTime TIME,
    FacilityID INTEGER,
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- DoctorSchedule table
CREATE TABLE doctor_schedule (
    ScheduleID INTEGER PRIMARY KEY,
    DoctorID INTEGER,
    DayOfWeek VARCHAR(10),
    StartTime VARCHAR,
    EndTime VARCHAR,
    Slotsize VARCHAR(10),
    AppointmentsPerSlot INTEGER,
    FacilityID INTEGER,
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- DoctorCalendar table
CREATE TABLE doctor_calendar (
    DCID INTEGER PRIMARY KEY,
    DoctorID INTEGER,
    Date DATE,
    SlotID INTEGER,
    FullDayLeave VARCHAR(1),
    SlotLeave VARCHAR(1),
    TotalAppointments INTEGER,
    BookedAppointments INTEGER,
    AvailableAppointments INTEGER,
    FacilityID INTEGER,
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (SlotID) REFERENCES slot_lookup(SlotID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- Appointment table
CREATE TABLE appointment (
    AppointmentID INTEGER PRIMARY KEY,
    PatientID INTEGER NOT NULL,
    DoctorID INTEGER NOT NULL,
    FacilityID INTEGER NOT NULL,
    DCID INTEGER NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    AppointmentDate DATE NOT NULL,
    AppointmentTime TIME NOT NULL,
    Reason VARCHAR(100) NOT NULL,
    CheckinTime DATETIME,
    Cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    TokenID VARCHAR(20),
    AppointmentMode VARCHAR(50) NOT NULL,
    AppointmentStatus VARCHAR(50) DEFAULT 'Scheduled',
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID),
    FOREIGN KEY (DCID) REFERENCES doctor_calendar(DCID)
);

-- MedicalRecord table
CREATE TABLE medical_record (
    RecordID INTEGER PRIMARY KEY,
    PatientID INTEGER,
    DoctorID INTEGER,
    AppointmentID INTEGER,
    Diagnosis VARCHAR(100),
    Treatment VARCHAR(100),
    Medicine_Prescription VARCHAR(100),
    Lab_Prescription VARCHAR(100),
    RecordDate DATETIME,
    FacilityID INTEGER,
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- Billing table
CREATE TABLE billing (
    BillID INTEGER PRIMARY KEY,
    AppointmentID INTEGER,
    Amount INTEGER,
    BillDate DATETIME,
    PaymentStatus VARCHAR(20),
    PaymentMode VARCHAR(100),
    TransactionID VARCHAR(20),
    FacilityID INTEGER,
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);

-- MedicalDocument table
CREATE TABLE medical_document (
    DocumentID INTEGER PRIMARY KEY,
    AppointmentID INTEGER,
    PatientID INTEGER,
    DoctorID INTEGER,
    DocumentType VARCHAR(100),
    DocumentPath VARCHAR(100),
    FacilityID INTEGER,
    FOREIGN KEY (AppointmentID) REFERENCES appointment(AppointmentID),
    FOREIGN KEY (PatientID) REFERENCES patients(id),
    FOREIGN KEY (DoctorID) REFERENCES doctors(id),
    FOREIGN KEY (FacilityID) REFERENCES facility(FacilityID)
);