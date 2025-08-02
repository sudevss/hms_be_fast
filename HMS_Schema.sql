-- Modified schema with FacilityID in every table

CREATE TABLE USERMASTER (
    UserID INT PRIMARY KEY,
    UserName VARCHAR(50),
    Password VARCHAR(50),
    Role VARCHAR(20),
    FacilityID INT,
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE Facility (
    FacilityID INT PRIMARY KEY,
    FacilityName VARCHAR(50),
    FacilityAddress VARCHAR(50),
    TaxNumber VARCHAR(50)
);

CREATE TABLE PATIENT (
    PatientID INT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    DateOfBirth DATE,
    Age INT,
    Gender CHAR(1),
    ContactNumber VARCHAR(15),
    Addresss VARCHAR(100),
    Email VARCHAR(100),
    ABHA_ID VARCHAR(20),
    Pref_Facility INT,
    FacilityID INT, -- Added: Current facility association
    FOREIGN KEY (Pref_Facility) REFERENCES Facility(FacilityID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

schemas.py 

CREATE TABLE DOCTOR (
    DoctorID INT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    Specialization VARCHAR(50),
    ContactNumber VARCHAR(15),
    Email VARCHAR(50),
    ConsultationFee DECIMAL(10,2),
    -- Pref_Facility INT,
    FacilityID INT, -- Added: Current facility association
    -- FOREIGN KEY (Pref_Facility) REFERENCES Facility(FacilityID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)

CREATE TABLE Slot_Lookup (
    SlotID INT PRIMARY KEY,
    SlotSize VARCHAR(10),
    SlotStartTime TIME,
    SlotEndTime TIME,
    FacilityID INT, -- Added: Facility-specific slot configurations
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE DOCTOR_SCHEDULE (
    ScheduleID INT PRIMARY KEY,
    DoctorID INT,
    DayOfWeek VARCHAR(10),
    StartTime TIME,
    EndTime TIME,
    Slotsize VARCHAR(10),
    AppointmentsPerSlot INT,
    FacilityID INT, -- Already exists
    FOREIGN KEY (DoctorID) REFERENCES DOCTOR(DoctorID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE DOCTOR_CALENDAR (
    DCID INT PRIMARY KEY,
    DoctorID INT,
    Date DATE,
    SlotID INT,
    FullDayLeave CHAR(1),
    SlotLeave CHAR(1),
    TotalAppointments INT,
    BookedAppointments INT,
    AvailableAppointments INT,
    FacilityID INT, -- Fixed: Was inconsistent case (Facilityid)
    FOREIGN KEY (DoctorID) REFERENCES DOCTOR(DoctorID),
    FOREIGN KEY (SlotID) REFERENCES Slot_Lookup(SlotID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE APPOINTMENT (
    AppointmentID INT PRIMARY KEY,
    PatientID INT,
    DoctorID INT,
    FacilityID INT, -- Already exists
    DCID INT,
    AppointmentDate DATE,
    AppointmentTime TIME,
    Reason VARCHAR(100),
    CheckinTime DATETIME,
    Cancelled         BOOLEAN   NOT NULL DEFAULT 0,,
    TokenID INT,
    AppointmentMode VARCHAR(50),
    AppointmentStatus VARCHAR(50),
    FOREIGN KEY (PatientID) REFERENCES PATIENT(PatientID),
    FOREIGN KEY (DoctorID) REFERENCES DOCTOR(DoctorID),
    FOREIGN KEY (DCID) REFERENCES DOCTOR_CALENDAR(DCID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE MEDICAL_RECORD (
    RecordID INT PRIMARY KEY,
    PatientID INT,
    DoctorID INT,
    AppointmentID INT,
    Diagnosis VARCHAR(100),
    Treatment VARCHAR(100),
    Medicine_Prescription VARCHAR(100),
    Lab_Prescription VARCHAR(100),
    RecordDate DATE,
    FacilityID INT, -- Added: Track which facility created the record
    FOREIGN KEY (PatientID) REFERENCES PATIENT(PatientID),
    FOREIGN KEY (DoctorID) REFERENCES DOCTOR(DoctorID),
    FOREIGN KEY (AppointmentID) REFERENCES APPOINTMENT(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE BILLING (
    BillID INT PRIMARY KEY,
    AppointmentID INT,
    Amount DECIMAL(10,2),
    BillDate DATE,
    PaymentStatus VARCHAR(20),
    PaymentMode VARCHAR(100),
    TransactionID VARCHAR(20),
    FacilityID INT, -- Added: Track which facility processed the billing
    FOREIGN KEY (AppointmentID) REFERENCES APPOINTMENT(AppointmentID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);

CREATE TABLE MEDICAL_DOCUMENT (
    DocumentID INT PRIMARY KEY,
    AppointmentID INT,
    PatientID INT,
    DoctorID INT,
    DocumentType VARCHAR(100),
    DocumentPath VARCHAR(100),
    FacilityID INT, -- Added: Track which facility owns the document
    FOREIGN KEY (AppointmentID) REFERENCES APPOINTMENT(AppointmentID),
    FOREIGN KEY (PatientID) REFERENCES PATIENT(PatientID),
    FOREIGN KEY (DoctorID) REFERENCES DOCTOR(DoctorID),
    FOREIGN KEY (FacilityID) REFERENCES Facility(FacilityID)
);