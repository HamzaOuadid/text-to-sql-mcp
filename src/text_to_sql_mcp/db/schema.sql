-- Synthetic municipal open-data schema: building permits, inspections,
-- code violations, licensing and complaints, modeled on real city
-- open-data portals (NYC DOB permits/violations, Chicago building permits).
-- 12 tables, deliberately overlapping column names across tables
-- (status, type, name, issue_date, ...) to exercise the AST validator's
-- schema-grounding and column-resolution logic. See db/seed.py for the
-- deterministic data generator and README for why this is synthetic
-- rather than a live pull from a real portal.

PRAGMA foreign_keys = ON;

CREATE TABLE departments (
    department_id   INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    budget          REAL NOT NULL,
    head_count      INTEGER NOT NULL
);

CREATE TABLE employees (
    employee_id     INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    department_id   INTEGER NOT NULL REFERENCES departments(department_id),
    role            TEXT NOT NULL,
    hire_date       TEXT NOT NULL,
    salary          REAL NOT NULL
);

CREATE TABLE owners (
    owner_id        INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    is_corporation  INTEGER NOT NULL,
    contact_email   TEXT
);

CREATE TABLE zones (
    zone_id         INTEGER PRIMARY KEY,
    borough         TEXT NOT NULL,
    zone_type       TEXT NOT NULL,
    description     TEXT
);

CREATE TABLE properties (
    property_id     INTEGER PRIMARY KEY,
    address         TEXT NOT NULL,
    borough         TEXT NOT NULL,
    zip_code        TEXT NOT NULL,
    owner_id        INTEGER NOT NULL REFERENCES owners(owner_id),
    zone_id         INTEGER NOT NULL REFERENCES zones(zone_id),
    year_built      INTEGER,
    property_type   TEXT NOT NULL
);

CREATE TABLE contractors (
    contractor_id   INTEGER PRIMARY KEY,
    business_name   TEXT NOT NULL,
    license_number  TEXT NOT NULL,
    license_status  TEXT NOT NULL,
    contact_email   TEXT
);

CREATE TABLE licenses (
    license_id      INTEGER PRIMARY KEY,
    contractor_id   INTEGER NOT NULL REFERENCES contractors(contractor_id),
    license_type    TEXT NOT NULL,
    issue_date      TEXT NOT NULL,
    expiration_date TEXT NOT NULL,
    status          TEXT NOT NULL
);

-- Large table (by row count) -- used to exercise the missing-WHERE check.
CREATE TABLE permits (
    permit_id       INTEGER PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(property_id),
    contractor_id   INTEGER NOT NULL REFERENCES contractors(contractor_id),
    permit_type     TEXT NOT NULL,
    issue_date      TEXT NOT NULL,
    expiration_date TEXT,
    status          TEXT NOT NULL,
    work_description TEXT
);

CREATE TABLE inspections (
    inspection_id   INTEGER PRIMARY KEY,
    permit_id       INTEGER NOT NULL REFERENCES permits(permit_id),
    inspector_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    inspection_date TEXT NOT NULL,
    result          TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE violations (
    violation_id    INTEGER PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(property_id),
    inspection_id   INTEGER REFERENCES inspections(inspection_id),
    violation_code  TEXT NOT NULL,
    description     TEXT,
    issue_date      TEXT NOT NULL,
    status          TEXT NOT NULL,
    fine_amount     REAL NOT NULL
);

-- Large table (by row count) -- used to exercise the missing-WHERE check.
CREATE TABLE complaints (
    complaint_id    INTEGER PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(property_id),
    complaint_type  TEXT NOT NULL,
    date_received   TEXT NOT NULL,
    status          TEXT NOT NULL,
    priority        TEXT NOT NULL
);

CREATE TABLE payments (
    payment_id      INTEGER PRIMARY KEY,
    violation_id    INTEGER NOT NULL REFERENCES violations(violation_id),
    amount          REAL NOT NULL,
    payment_date    TEXT NOT NULL,
    method          TEXT NOT NULL
);

CREATE INDEX idx_permits_property ON permits(property_id);
CREATE INDEX idx_permits_contractor ON permits(contractor_id);
CREATE INDEX idx_inspections_permit ON inspections(permit_id);
CREATE INDEX idx_violations_property ON violations(property_id);
CREATE INDEX idx_complaints_property ON complaints(property_id);
CREATE INDEX idx_payments_violation ON payments(violation_id);
