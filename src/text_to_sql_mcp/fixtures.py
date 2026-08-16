"""The labelled 20-30 question evaluation set (spec section 6 / milestone
M4), spanning easy/medium/hard difficulty and flagging join-heavy
questions for separate accuracy tracking (spec section 9).

Each question's `expected_sql` is treated as the gold query: at eval time
it is executed directly against the civic database to produce the
expected rows, which are then compared against whatever the system
actually returned for the natural-language question. This avoids
hand-maintaining expected numeric answers that would drift if the seed
data ever changes.

One question (`is_ambiguous=True`) is deliberately unanswerable with a
single confident query -- see the README and `service.ask()` for how
ambiguity is surfaced instead of silently picking one interpretation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Difficulty = Literal["easy", "medium", "hard"]


class EvalQuestion(BaseModel):
    id: int
    nl_question: str
    expected_sql: str | None
    difficulty: Difficulty
    is_join_heavy: bool = False
    is_ambiguous: bool = False


QUESTIONS: list[EvalQuestion] = [
    # ---- easy -------------------------------------------------------
    EvalQuestion(
        id=1,
        nl_question="How many permits are there in total?",
        expected_sql="SELECT COUNT(*) AS count FROM permits",
        difficulty="easy",
    ),
    EvalQuestion(
        id=2,
        nl_question="How many properties are there?",
        expected_sql="SELECT COUNT(*) AS count FROM properties",
        difficulty="easy",
    ),
    EvalQuestion(
        id=3,
        nl_question="List all departments.",
        expected_sql="SELECT * FROM departments",
        difficulty="easy",
    ),
    EvalQuestion(
        id=4,
        nl_question="How many contractors have an active license status?",
        expected_sql="SELECT COUNT(*) AS count FROM contractors WHERE license_status = 'Active'",
        difficulty="easy",
    ),
    EvalQuestion(
        id=5,
        nl_question="What is the total budget across all departments?",
        expected_sql="SELECT SUM(budget) AS total_budget FROM departments",
        difficulty="easy",
    ),
    EvalQuestion(
        id=6,
        nl_question="How many owners are corporations?",
        expected_sql="SELECT COUNT(*) AS count FROM owners WHERE is_corporation = 1",
        difficulty="easy",
    ),
    EvalQuestion(
        id=7,
        nl_question="How many violations have status 'Open'?",
        expected_sql="SELECT COUNT(*) AS count FROM violations WHERE status = 'Open'",
        difficulty="easy",
    ),
    EvalQuestion(
        id=8,
        nl_question="List all zones in the Bronx.",
        expected_sql="SELECT * FROM zones WHERE borough = 'Bronx'",
        difficulty="easy",
    ),
    # ---- medium -------------------------------------------------------
    EvalQuestion(
        id=9,
        nl_question="How many permits are there for each permit type?",
        expected_sql=(
            "SELECT permit_type, COUNT(*) AS permit_count FROM permits "
            "GROUP BY permit_type ORDER BY permit_count DESC"
        ),
        difficulty="medium",
    ),
    EvalQuestion(
        id=10,
        nl_question="What is the average fine amount for violations?",
        expected_sql="SELECT AVG(fine_amount) AS avg_fine FROM violations",
        difficulty="medium",
    ),
    EvalQuestion(
        id=11,
        nl_question="How many complaints were received for each complaint type?",
        expected_sql=(
            "SELECT complaint_type, COUNT(*) AS complaint_count FROM complaints "
            "GROUP BY complaint_type ORDER BY complaint_count DESC"
        ),
        difficulty="medium",
    ),
    EvalQuestion(
        id=12,
        nl_question="List the business names of contractors whose license status is 'Suspended'.",
        expected_sql="SELECT business_name FROM contractors WHERE license_status = 'Suspended'",
        difficulty="medium",
    ),
    EvalQuestion(
        id=13,
        nl_question="What are the first and last names of employees in the Department of Buildings?",
        expected_sql=(
            "SELECT e.first_name, e.last_name FROM employees e "
            "JOIN departments d ON e.department_id = d.department_id "
            "WHERE d.name = 'Department of Buildings'"
        ),
        difficulty="medium",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=14,
        nl_question="How many permits does each contractor hold?",
        expected_sql=(
            "SELECT c.business_name, COUNT(*) AS permit_count FROM permits p "
            "JOIN contractors c ON p.contractor_id = c.contractor_id "
            "GROUP BY c.business_name ORDER BY permit_count DESC"
        ),
        difficulty="medium",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=15,
        nl_question="What is the total amount collected across all payments?",
        expected_sql="SELECT SUM(amount) AS total_paid FROM payments",
        difficulty="medium",
    ),
    EvalQuestion(
        id=16,
        nl_question="How many properties are in the Brooklyn borough?",
        expected_sql="SELECT COUNT(*) AS count FROM properties WHERE borough = 'Brooklyn'",
        difficulty="medium",
    ),
    EvalQuestion(
        id=17,
        nl_question="List the top 5 zones by number of properties in them.",
        expected_sql=(
            "SELECT z.zone_id, z.borough, COUNT(*) AS property_count FROM properties p "
            "JOIN zones z ON p.zone_id = z.zone_id "
            "GROUP BY z.zone_id, z.borough ORDER BY property_count DESC LIMIT 5"
        ),
        difficulty="medium",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=18,
        nl_question="How many inspections resulted in 'Failed'?",
        expected_sql="SELECT COUNT(*) AS count FROM inspections WHERE result = 'Failed'",
        difficulty="medium",
    ),
    # ---- hard -------------------------------------------------------
    EvalQuestion(
        id=19,
        nl_question="Which properties have more than 3 open violations?",
        expected_sql=(
            "SELECT pr.property_id, pr.address, COUNT(*) AS open_violations "
            "FROM violations v JOIN properties pr ON v.property_id = pr.property_id "
            "WHERE v.status = 'Open' "
            "GROUP BY pr.property_id, pr.address HAVING COUNT(*) > 3"
        ),
        difficulty="hard",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=20,
        nl_question="List contractors who have at least one permit that resulted in a failed inspection.",
        expected_sql=(
            "SELECT DISTINCT c.business_name FROM contractors c "
            "JOIN permits p ON p.contractor_id = c.contractor_id "
            "JOIN inspections i ON i.permit_id = p.permit_id "
            "WHERE i.result = 'Failed'"
        ),
        difficulty="hard",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=21,
        nl_question="What is the total amount paid against violations for properties in Manhattan?",
        expected_sql=(
            "SELECT SUM(pay.amount) AS total_paid FROM payments pay "
            "JOIN violations v ON pay.violation_id = v.violation_id "
            "JOIN properties pr ON v.property_id = pr.property_id "
            "WHERE pr.borough = 'Manhattan'"
        ),
        difficulty="hard",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=22,
        nl_question="Which employees have conducted more than 50 inspections?",
        expected_sql=(
            "SELECT e.first_name, e.last_name, COUNT(*) AS inspection_count "
            "FROM inspections i JOIN employees e ON i.inspector_id = e.employee_id "
            "GROUP BY e.employee_id, e.first_name, e.last_name HAVING COUNT(*) > 50"
        ),
        difficulty="hard",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=23,
        nl_question=(
            "List property addresses that have both an open violation and an "
            "emergency-priority complaint."
        ),
        expected_sql=(
            "SELECT DISTINCT address FROM properties WHERE property_id IN "
            "(SELECT property_id FROM violations WHERE status = 'Open') "
            "AND property_id IN "
            "(SELECT property_id FROM complaints WHERE priority = 'Emergency')"
        ),
        difficulty="hard",
        is_join_heavy=True,
    ),
    EvalQuestion(
        id=24,
        nl_question="What percentage of permits currently have status 'Completed'?",
        expected_sql=(
            "SELECT ROUND(100.0 * SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) "
            "/ COUNT(*), 2) AS pct_completed FROM permits"
        ),
        difficulty="hard",
    ),
    # ---- ambiguous (documented handling, not silently guessed) --------
    EvalQuestion(
        id=25,
        nl_question="Show me the recent activity.",
        expected_sql=None,
        difficulty="hard",
        is_ambiguous=True,
    ),
]
