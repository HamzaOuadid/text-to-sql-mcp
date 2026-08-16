"""Deterministic synthetic-data generator for the civic demo database, and
schema setup for the small app-metadata database (eval_questions,
query_log).

Why synthetic instead of a live pull from a real city open-data portal:
see the README's "Risks / Open Questions" section -- in short, this keeps
`init-db` fully offline and reproducible (no network dependency in tests
or CI, no data-licensing questions to resolve before publishing), while
still modeling a genuinely non-trivial, ambiguous, real-world-shaped
schema (12 tables, overlapping column names, realistic row-count skew).
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

SCHEMA_SQL_PATH = Path(__file__).with_name("schema.sql")

SEED = 42

BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
ZONE_TYPES = ["Residential", "Commercial", "Mixed Use", "Industrial", "Historic District"]
PROPERTY_TYPES = ["Single Family", "Multi Family", "Condo", "Office", "Retail", "Warehouse"]
FIRST_NAMES = [
    "James", "Maria", "Robert", "Linda", "Michael", "Patricia", "David", "Jennifer",
    "William", "Elizabeth", "Carlos", "Aisha", "Wei", "Fatima", "John", "Susan",
    "Daniel", "Karen", "Anthony", "Nancy", "Priya", "Omar", "Chen", "Grace",
]
LAST_NAMES = [
    "Smith", "Johnson", "Garcia", "Rodriguez", "Williams", "Brown", "Jones", "Miller",
    "Davis", "Martinez", "Chen", "Patel", "Kim", "Lopez", "Nguyen", "Khan",
    "Wilson", "Anderson", "Thomas", "Moore",
]
STREET_NAMES = [
    "Main St", "Broadway", "Park Ave", "5th Ave", "Elm St", "Oak St", "Maple Ave",
    "Washington St", "Lexington Ave", "Church St", "River Rd", "Court St",
    "Franklin Ave", "Union Sq", "Grand St", "Bedford Ave",
]
DEPARTMENTS = [
    ("Department of Buildings", 42_000_000, 210),
    ("Department of Housing Preservation", 31_500_000, 160),
    ("Fire Prevention Bureau", 18_200_000, 95),
    ("Environmental Health", 12_800_000, 70),
    ("Code Enforcement", 9_600_000, 55),
    ("Zoning & Planning", 7_400_000, 40),
]
EMPLOYEE_ROLES = ["Inspector", "Senior Inspector", "Plan Examiner", "Field Supervisor", "Clerk"]
LICENSE_TYPES = ["General Contractor", "Electrical", "Plumbing", "HVAC", "Demolition", "Elevator"]
LICENSE_STATUSES = ["Active", "Expired", "Suspended", "Revoked"]
PERMIT_TYPES = [
    "New Building", "Alteration Type 1", "Alteration Type 2", "Alteration Type 3",
    "Demolition", "Electrical", "Plumbing", "Sign", "Sidewalk Shed", "Fence",
]
PERMIT_STATUSES = ["Issued", "In Progress", "Completed", "Expired", "Revoked", "On Hold"]
INSPECTION_RESULTS = ["Passed", "Failed", "Partial Pass", "No Access", "Rescheduled"]
VIOLATION_CODES = [
    "V-101 Fire Egress", "V-204 Illegal Conversion", "V-305 Electrical Hazard",
    "V-410 Structural Defect", "V-512 No Permit", "V-618 Elevator Safety",
    "V-720 Plumbing Hazard", "V-825 Occupancy Overload",
]
VIOLATION_STATUSES = ["Open", "Resolved", "In Litigation", "Dismissed"]
COMPLAINT_TYPES = [
    "Illegal Construction", "No Permit Work", "Structural Damage", "Elevator Outage",
    "Heating Complaint", "Noise Complaint", "Water Leak", "Gas Leak", "Unsafe Scaffold",
]
COMPLAINT_STATUSES = ["Open", "Under Review", "Closed", "Referred"]
PRIORITIES = ["Low", "Medium", "High", "Emergency"]
PAYMENT_METHODS = ["Credit Card", "Check", "ACH", "Money Order"]

# Row counts. permits and complaints are deliberately well above the
# default large-table threshold (500) to exercise the missing-WHERE check
# in a realistic way; everything else stays comfortably below it.
N_EMPLOYEES = 45
N_OWNERS = 180
N_ZONES = 25
N_PROPERTIES = 350
N_CONTRACTORS = 70
N_LICENSES = 90
N_PERMITS = 2600
N_INSPECTIONS = 2000
N_VIOLATIONS = 550
N_COMPLAINTS = 2400
N_PAYMENTS = 420


def _rand_date(rng: random.Random, start_year: int = 2019, end_year: int = 2026) -> str:
    year = rng.randint(start_year, end_year)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_civic_db(path: Path, seed: int = SEED, force: bool = False) -> None:
    """Create and populate the civic demo database at `path`.

    Deterministic given `seed` -- re-running with the same seed produces
    byte-identical row contents (though not necessarily an identical
    SQLite file, since page layout/ordering isn't guaranteed).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not force:
            return
        path.unlink()

    rng = random.Random(seed)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))

        # departments
        conn.executemany(
            "INSERT INTO departments (department_id, name, budget, head_count) "
            "VALUES (?, ?, ?, ?)",
            [(i + 1, *d) for i, d in enumerate(DEPARTMENTS)],
        )

        # employees
        employees = []
        for i in range(1, N_EMPLOYEES + 1):
            employees.append(
                (
                    i,
                    rng.choice(FIRST_NAMES),
                    rng.choice(LAST_NAMES),
                    rng.randint(1, len(DEPARTMENTS)),
                    rng.choice(EMPLOYEE_ROLES),
                    _rand_date(rng, 2012, 2025),
                    round(rng.uniform(48_000, 125_000), 2),
                )
            )
        conn.executemany(
            "INSERT INTO employees (employee_id, first_name, last_name, department_id, "
            "role, hire_date, salary) VALUES (?, ?, ?, ?, ?, ?, ?)",
            employees,
        )
        inspector_ids = [e[0] for e in employees if "Inspector" in e[4]]
        if not inspector_ids:
            inspector_ids = [e[0] for e in employees]

        # owners
        owners = []
        for i in range(1, N_OWNERS + 1):
            is_corp = rng.random() < 0.35
            if is_corp:
                name = f"{rng.choice(LAST_NAMES)} {rng.choice(['Holdings', 'Realty', 'Properties', 'Group', 'LLC'])}"
            else:
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            owners.append((i, name, int(is_corp), f"owner{i}@example.com"))
        conn.executemany(
            "INSERT INTO owners (owner_id, name, is_corporation, contact_email) "
            "VALUES (?, ?, ?, ?)",
            owners,
        )

        # zones
        zones = []
        for i in range(1, N_ZONES + 1):
            zones.append(
                (
                    i,
                    rng.choice(BOROUGHS),
                    rng.choice(ZONE_TYPES),
                    f"Zone {i} planning district",
                )
            )
        conn.executemany(
            "INSERT INTO zones (zone_id, borough, zone_type, description) VALUES (?, ?, ?, ?)",
            zones,
        )

        # properties
        properties = []
        for i in range(1, N_PROPERTIES + 1):
            properties.append(
                (
                    i,
                    f"{rng.randint(1, 999)} {rng.choice(STREET_NAMES)}",
                    rng.choice(BOROUGHS),
                    f"{rng.randint(10001, 11499)}",
                    rng.randint(1, N_OWNERS),
                    rng.randint(1, N_ZONES),
                    rng.randint(1890, 2024),
                    rng.choice(PROPERTY_TYPES),
                )
            )
        conn.executemany(
            "INSERT INTO properties (property_id, address, borough, zip_code, owner_id, "
            "zone_id, year_built, property_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            properties,
        )

        # contractors
        contractors = []
        for i in range(1, N_CONTRACTORS + 1):
            contractors.append(
                (
                    i,
                    f"{rng.choice(LAST_NAMES)} {rng.choice(['Construction', 'Contracting', 'Builders', 'Electric', 'Plumbing Co'])}",
                    f"LIC-{100000 + i}",
                    rng.choice(LICENSE_STATUSES),
                    f"contractor{i}@example.com",
                )
            )
        conn.executemany(
            "INSERT INTO contractors (contractor_id, business_name, license_number, "
            "license_status, contact_email) VALUES (?, ?, ?, ?, ?)",
            contractors,
        )

        # licenses
        licenses = []
        for i in range(1, N_LICENSES + 1):
            issue = _rand_date(rng, 2015, 2024)
            licenses.append(
                (
                    i,
                    rng.randint(1, N_CONTRACTORS),
                    rng.choice(LICENSE_TYPES),
                    issue,
                    _rand_date(rng, 2025, 2027),
                    rng.choice(LICENSE_STATUSES),
                )
            )
        conn.executemany(
            "INSERT INTO licenses (license_id, contractor_id, license_type, issue_date, "
            "expiration_date, status) VALUES (?, ?, ?, ?, ?, ?)",
            licenses,
        )

        # permits (large table)
        permits = []
        for i in range(1, N_PERMITS + 1):
            permits.append(
                (
                    i,
                    rng.randint(1, N_PROPERTIES),
                    rng.randint(1, N_CONTRACTORS),
                    rng.choice(PERMIT_TYPES),
                    _rand_date(rng),
                    _rand_date(rng, 2025, 2028),
                    rng.choice(PERMIT_STATUSES),
                    f"{rng.choice(PERMIT_TYPES)} work at property {rng.randint(1, N_PROPERTIES)}",
                )
            )
        conn.executemany(
            "INSERT INTO permits (permit_id, property_id, contractor_id, permit_type, "
            "issue_date, expiration_date, status, work_description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            permits,
        )

        # inspections
        inspections = []
        for i in range(1, N_INSPECTIONS + 1):
            inspections.append(
                (
                    i,
                    rng.randint(1, N_PERMITS),
                    rng.choice(inspector_ids),
                    _rand_date(rng),
                    rng.choice(INSPECTION_RESULTS),
                    None if rng.random() < 0.6 else "Follow-up scheduled",
                )
            )
        conn.executemany(
            "INSERT INTO inspections (inspection_id, permit_id, inspector_id, "
            "inspection_date, result, notes) VALUES (?, ?, ?, ?, ?, ?)",
            inspections,
        )

        # violations
        violations = []
        for i in range(1, N_VIOLATIONS + 1):
            violations.append(
                (
                    i,
                    rng.randint(1, N_PROPERTIES),
                    rng.randint(1, N_INSPECTIONS) if rng.random() < 0.7 else None,
                    rng.choice(VIOLATION_CODES),
                    "Violation observed during inspection or complaint follow-up.",
                    _rand_date(rng),
                    rng.choice(VIOLATION_STATUSES),
                    round(rng.uniform(150, 25000), 2),
                )
            )
        conn.executemany(
            "INSERT INTO violations (violation_id, property_id, inspection_id, "
            "violation_code, description, issue_date, status, fine_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            violations,
        )

        # complaints (large table)
        complaints = []
        for i in range(1, N_COMPLAINTS + 1):
            complaints.append(
                (
                    i,
                    rng.randint(1, N_PROPERTIES),
                    rng.choice(COMPLAINT_TYPES),
                    _rand_date(rng),
                    rng.choice(COMPLAINT_STATUSES),
                    rng.choice(PRIORITIES),
                )
            )
        conn.executemany(
            "INSERT INTO complaints (complaint_id, property_id, complaint_type, "
            "date_received, status, priority) VALUES (?, ?, ?, ?, ?, ?)",
            complaints,
        )

        # payments (against violations)
        payments = []
        violation_ids = [v[0] for v in violations]
        rng.shuffle(violation_ids)
        for i, vio_id in enumerate(violation_ids[:N_PAYMENTS], start=1):
            payments.append(
                (
                    i,
                    vio_id,
                    round(rng.uniform(50, 25000), 2),
                    _rand_date(rng),
                    rng.choice(PAYMENT_METHODS),
                )
            )
        conn.executemany(
            "INSERT INTO payments (payment_id, violation_id, amount, payment_date, method) "
            "VALUES (?, ?, ?, ?, ?)",
            payments,
        )

        conn.commit()
    finally:
        conn.close()


APP_DB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eval_questions (
    id                  INTEGER PRIMARY KEY,
    nl_question         TEXT NOT NULL,
    expected_sql        TEXT,
    expected_answer     TEXT,
    difficulty          TEXT NOT NULL,
    is_join_heavy       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS query_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    nl_question         TEXT NOT NULL,
    generated_sql       TEXT,
    validation_ok       INTEGER NOT NULL,
    rejection_reason    TEXT,
    execution_time_ms   REAL,
    llm_backend         TEXT
);
"""


def init_app_db(path: Path, force: bool = False) -> None:
    """Create the small app-metadata database (eval_questions, query_log).

    Kept as a *separate* SQLite file from the civic dataset so the civic
    connection used to actually run generated queries can be opened
    strictly read-only (see execution.py) without also needing write
    access for logging.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and force:
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(APP_DB_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
