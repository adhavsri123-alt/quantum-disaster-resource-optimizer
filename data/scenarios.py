"""
scenarios.py
------------
Pre-defined and randomly-generated emergency scenario sets for the QDO
simulation.  All random generation uses a fixed seed so results are
fully reproducible.

A "scenario" is a named collection of simultaneous emergencies drawn
from a larger pool, representing what might actually happen on campus
during a crisis.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from data.campus import LOCATIONS

# ---------------------------------------------------------------------------
# Emergency type catalogue
# ---------------------------------------------------------------------------

EMERGENCY_TYPES = {
    "fire": {
        "label": "Fire",
        "base_severity": 8,
        "base_people_affected": (10, 50),
        "ambulances_required": (1, 3),
        "rescue_teams_required": (1, 2),
        "medical_supplies_required": (10, 30),
        "medical_personnel_required": (2, 6),
        "color": "#FF4444",
    },
    "medical_emergency": {
        "label": "Medical Emergency",
        "base_severity": 7,
        "base_people_affected": (1, 10),
        "ambulances_required": (1, 2),
        "rescue_teams_required": (0, 1),
        "medical_supplies_required": (5, 20),
        "medical_personnel_required": (2, 4),
        "color": "#FF8800",
    },
    "accident": {
        "label": "Accident",
        "base_severity": 6,
        "base_people_affected": (2, 15),
        "ambulances_required": (1, 2),
        "rescue_teams_required": (0, 1),
        "medical_supplies_required": (5, 15),
        "medical_personnel_required": (1, 3),
        "color": "#FFBB00",
    },
    "flood_infrastructure": {
        "label": "Flood / Infrastructure Emergency",
        "base_severity": 9,
        "base_people_affected": (20, 100),
        "ambulances_required": (0, 2),
        "rescue_teams_required": (2, 3),
        "medical_supplies_required": (15, 40),
        "medical_personnel_required": (3, 8),
        "color": "#4488FF",
    },
}


# ---------------------------------------------------------------------------
# Emergency dataclass
# ---------------------------------------------------------------------------

@dataclass
class Emergency:
    """Represents a single active emergency event."""
    id: str
    location_id: str
    emergency_type: str                  # key into EMERGENCY_TYPES
    severity: int                        # 1–10 scale
    people_affected: int
    ambulances_required: int
    rescue_teams_required: int
    medical_supplies_required: int
    medical_personnel_required: int
    description: str = ""
    reported_at_minute: float = 0.0      # simulation clock when reported

    # -----------------------------------------------------------------------
    @property
    def location_name(self) -> str:
        return LOCATIONS[self.location_id].name

    @property
    def type_label(self) -> str:
        return EMERGENCY_TYPES[self.emergency_type]["label"]

    @property
    def type_color(self) -> str:
        return EMERGENCY_TYPES[self.emergency_type]["color"]

    @property
    def priority_score(self) -> float:
        """
        Composite priority: higher is more urgent.
        Combines severity and scale of impact.
        """
        return self.severity * 0.7 + (self.people_affected / 10.0) * 0.3

    def resource_summary(self) -> Dict[str, int]:
        return {
            "ambulances": self.ambulances_required,
            "rescue_teams": self.rescue_teams_required,
            "medical_supplies": self.medical_supplies_required,
            "medical_personnel": self.medical_personnel_required,
        }

    def __repr__(self) -> str:
        return (
            f"Emergency(id={self.id!r}, type={self.emergency_type!r}, "
            f"location={self.location_id!r}, severity={self.severity}, "
            f"people={self.people_affected})"
        )


# ---------------------------------------------------------------------------
# Resource dataclass
# ---------------------------------------------------------------------------

@dataclass
class ResourcePool:
    """Total available emergency resources on campus."""
    ambulances: int = 5
    rescue_teams: int = 3
    medical_supplies: int = 100
    medical_personnel: int = 25

    def as_dict(self) -> Dict[str, int]:
        return {
            "ambulances": self.ambulances,
            "rescue_teams": self.rescue_teams,
            "medical_supplies": self.medical_supplies,
            "medical_personnel": self.medical_personnel,
        }

    def __repr__(self) -> str:
        return (
            f"ResourcePool(ambulances={self.ambulances}, "
            f"rescue_teams={self.rescue_teams}, "
            f"medical_supplies={self.medical_supplies}, "
            f"medical_personnel={self.medical_personnel})"
        )


# ---------------------------------------------------------------------------
# Scenario dataclass
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """A named snapshot of simultaneous campus emergencies."""
    name: str
    description: str
    emergencies: List[Emergency]
    blocked_routes: List[tuple] = field(default_factory=list)
    seed: int = 42

    def __repr__(self) -> str:
        return (
            f"Scenario(name={self.name!r}, "
            f"emergencies={len(self.emergencies)}, "
            f"blocked_routes={self.blocked_routes})"
        )


# ---------------------------------------------------------------------------
# Emergency generator
# ---------------------------------------------------------------------------

def _make_emergency(
    eid: str,
    location_id: str,
    emergency_type: str,
    rng: random.Random,
    severity_override: Optional[int] = None,
    reported_at: float = 0.0,
) -> Emergency:
    """
    Construct an Emergency by sampling resource requirements from the
    catalogue ranges using the provided RNG instance.
    """
    meta = EMERGENCY_TYPES[emergency_type]

    severity = severity_override if severity_override is not None else rng.randint(
        max(1, meta["base_severity"] - 2),
        min(10, meta["base_severity"] + 2),
    )

    people = rng.randint(*meta["base_people_affected"])
    ambulances = rng.randint(*meta["ambulances_required"])
    rescue = rng.randint(*meta["rescue_teams_required"])
    supplies = rng.randint(*meta["medical_supplies_required"])
    personnel = rng.randint(*meta["medical_personnel_required"])

    type_label = meta["label"]
    loc_name = LOCATIONS[location_id].name

    return Emergency(
        id=eid,
        location_id=location_id,
        emergency_type=emergency_type,
        severity=severity,
        people_affected=people,
        ambulances_required=ambulances,
        rescue_teams_required=rescue,
        medical_supplies_required=supplies,
        medical_personnel_required=personnel,
        description=f"{type_label} at {loc_name} — severity {severity}/10, "
                    f"{people} people affected.",
        reported_at_minute=reported_at,
    )


# ---------------------------------------------------------------------------
# Pre-defined scenarios
# ---------------------------------------------------------------------------

def get_scenario_alpha(seed: int = 42) -> Scenario:
    """
    Scenario ALPHA – Multi-incident crisis:
    A fire at the Hostel A, a medical emergency at the cafeteria, and a
    vehicle accident near the Admin Block occur simultaneously.
    """
    rng = random.Random(seed)
    emergencies = [
        _make_emergency("E001", "hostel_a",      "fire",              rng, severity_override=9),
        _make_emergency("E002", "cafeteria",      "medical_emergency", rng, severity_override=7),
        _make_emergency("E003", "admin_block",    "accident",          rng, severity_override=5),
    ]
    return Scenario(
        name="ALPHA",
        description=(
            "Three simultaneous incidents: fire at Hostel A, "
            "medical emergency at Cafeteria, accident near Admin Block."
        ),
        emergencies=emergencies,
        blocked_routes=[],
        seed=seed,
    )


def get_scenario_beta(seed: int = 42) -> Scenario:
    """
    Scenario BETA – Flood + cascading emergencies:
    A flood hits the Sports Complex cutting off a road; injuries occur at
    Hostel B and a fire breaks out at the Library.
    """
    rng = random.Random(seed)
    emergencies = [
        _make_emergency("E001", "sports_complex", "flood_infrastructure", rng, severity_override=9),
        _make_emergency("E002", "hostel_b",        "medical_emergency",    rng, severity_override=8),
        _make_emergency("E003", "library",          "fire",                rng, severity_override=7),
        _make_emergency("E004", "academic_block",   "accident",            rng, severity_override=4),
    ]
    return Scenario(
        name="BETA",
        description=(
            "Flood at Sports Complex (route blocked), injuries at Hostel B, "
            "fire at Library, and an accident at Academic Block."
        ),
        emergencies=emergencies,
        blocked_routes=[("hostel_b", "sports_complex")],
        seed=seed,
    )


def get_scenario_gamma(seed: int = 42) -> Scenario:
    """
    Scenario GAMMA – Mass-casualty event:
    A structural collapse at the Academic Block causes a mass-casualty
    event; secondary fires break out at the Cafeteria and Hostel A.
    """
    rng = random.Random(seed)
    emergencies = [
        _make_emergency("E001", "academic_block", "flood_infrastructure", rng, severity_override=10),
        _make_emergency("E002", "cafeteria",       "fire",                rng, severity_override=8),
        _make_emergency("E003", "hostel_a",         "fire",               rng, severity_override=6),
        _make_emergency("E004", "main_gate",         "accident",           rng, severity_override=5),
        _make_emergency("E005", "hostel_b",          "medical_emergency",  rng, severity_override=7),
    ]
    return Scenario(
        name="GAMMA",
        description=(
            "Mass-casualty structural collapse at Academic Block; "
            "secondary fires at Cafeteria and Hostel A; "
            "accident at Main Gate; injuries at Hostel B."
        ),
        emergencies=emergencies,
        blocked_routes=[("academic_block", "cafeteria"), ("main_gate", "cafeteria")],
        seed=seed,
    )


def generate_random_scenario(
    name: str = "RANDOM",
    num_emergencies: int = 3,
    seed: int = 42,
) -> Scenario:
    """
    Produce a fully random scenario with `num_emergencies` incidents
    placed at distinct campus locations using `seed` for reproducibility.
    """
    rng = random.Random(seed)
    loc_ids = list(LOCATIONS.keys())
    chosen_locs = rng.sample(loc_ids, k=min(num_emergencies, len(loc_ids)))
    e_types = list(EMERGENCY_TYPES.keys())

    emergencies: List[Emergency] = []
    for i, loc_id in enumerate(chosen_locs):
        etype = rng.choice(e_types)
        reported = rng.uniform(0, 5)  # reported within first 5 sim minutes
        em = _make_emergency(
            eid=f"E{i + 1:03d}",
            location_id=loc_id,
            emergency_type=etype,
            rng=rng,
            reported_at=round(reported, 2),
        )
        emergencies.append(em)

    # Randomly block 0-1 routes
    all_edges = [("hostel_a", "hostel_b"), ("hostel_b", "sports_complex"),
                 ("cafeteria", "academic_block"), ("library", "hostel_a")]
    blocked = rng.sample(all_edges, k=rng.randint(0, 1))

    return Scenario(
        name=name,
        description=f"Randomly generated scenario (seed={seed}, n={num_emergencies}).",
        emergencies=emergencies,
        blocked_routes=blocked,
        seed=seed,
    )


def get_scenario_stress(seed: int = 42) -> Scenario:
    """
    Scenario STRESS – Extreme Resource Contention:
    A distant emergency at Sports Complex (E001, severity 9, 3 ambulances req) has slightly
    higher severity score, leading greedy priority ordering to allocate 3 out of 5 available
    ambulances to the distant location (4.29 min travel time). This leaves only 2 ambulances for
    three nearby high-severity emergencies (E002, E003, E004). QUBO considers response-time
    delays and severity-weighted coverage globally, choosing to allocate ambulances to the nearby
    incidents to minimize total response delay and maximize critical coverage.
    """
    rng = random.Random(seed)
    emergencies = [
        Emergency(
            id="E001",
            location_id="sports_complex",
            emergency_type="flood_infrastructure",
            severity=9,
            people_affected=15,
            ambulances_required=3,
            rescue_teams_required=2,
            medical_supplies_required=25,
            medical_personnel_required=4,
            description="Major infrastructure flood at Sports Complex (distant location, 4.29 min travel time).",
            reported_at_minute=0.0,
        ),
        Emergency(
            id="E002",
            location_id="admin_block",
            emergency_type="medical_emergency",
            severity=8,
            people_affected=25,
            ambulances_required=2,
            rescue_teams_required=1,
            medical_supplies_required=15,
            medical_personnel_required=3,
            description="Severe medical emergency at Admin Block (0.75 min from depot).",
            reported_at_minute=0.0,
        ),
        Emergency(
            id="E003",
            location_id="cafeteria",
            emergency_type="fire",
            severity=8,
            people_affected=25,
            ambulances_required=2,
            rescue_teams_required=1,
            medical_supplies_required=20,
            medical_personnel_required=4,
            description="Kitchen fire at Cafeteria (1.59 min from depot).",
            reported_at_minute=0.0,
        ),
        Emergency(
            id="E004",
            location_id="academic_block",
            emergency_type="medical_emergency",
            severity=8,
            people_affected=25,
            ambulances_required=2,
            rescue_teams_required=1,
            medical_supplies_required=15,
            medical_personnel_required=3,
            description="Structural collapse at Academic Block (2.01 min from depot).",
            reported_at_minute=0.0,
        ),
        Emergency(
            id="E005",
            location_id="hostel_a",
            emergency_type="accident",
            severity=6,
            people_affected=10,
            ambulances_required=1,
            rescue_teams_required=0,
            medical_supplies_required=10,
            medical_personnel_required=2,
            description="Vehicle collision near Hostel A (3.63 min from depot).",
            reported_at_minute=0.0,
        ),
    ]
    return Scenario(
        name="STRESS",
        description=(
            "Extreme resource contention test: distant flood vs. "
            "multiple nearby high-severity incidents competing for scarce ambulances."
        ),
        emergencies=emergencies,
        blocked_routes=[("hostel_a", "sports_complex")],
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Scenario registry  (easy lookup by name)
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY: Dict[str, callable] = {
    "alpha":  get_scenario_alpha,
    "beta":   get_scenario_beta,
    "gamma":  get_scenario_gamma,
    "stress": get_scenario_stress,
}


def get_scenario(name: str, seed: int = 42) -> Scenario:
    """
    Retrieve a scenario by name.  Raises KeyError for unknown names.
    """
    key = name.lower()
    if key not in SCENARIO_REGISTRY:
        raise KeyError(
            f"Unknown scenario '{name}'. Available: {list(SCENARIO_REGISTRY.keys())}"
        )
    return SCENARIO_REGISTRY[key](seed=seed)


# Default resources used throughout the application
DEFAULT_RESOURCES = ResourcePool(
    ambulances=5,
    rescue_teams=3,
    medical_supplies=100,
    medical_personnel=25,
)
