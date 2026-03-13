"""Load and validate YAML form definitions from the forms/ directory.

Each hackathon has a YAML file in ``forms/`` that declares a multi-step
registration form.  This module parses that YAML into typed dataclasses and
provides helpers for conditional step evaluation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── Project root — resolved relative to this file ───────────────────

_FORMS_DIR = Path(__file__).resolve().parents[3] / "forms"

# ── Countries (ISO 3166-1 alpha-2 codes) ────────────────────────────

COUNTRIES: list[dict[str, str]] = [
    {"label": "Afghanistan", "value": "AF"},
    {"label": "Albania", "value": "AL"},
    {"label": "Algeria", "value": "DZ"},
    {"label": "Andorra", "value": "AD"},
    {"label": "Angola", "value": "AO"},
    {"label": "Antigua and Barbuda", "value": "AG"},
    {"label": "Argentina", "value": "AR"},
    {"label": "Armenia", "value": "AM"},
    {"label": "Australia", "value": "AU"},
    {"label": "Austria", "value": "AT"},
    {"label": "Azerbaijan", "value": "AZ"},
    {"label": "Bahamas", "value": "BS"},
    {"label": "Bahrain", "value": "BH"},
    {"label": "Bangladesh", "value": "BD"},
    {"label": "Barbados", "value": "BB"},
    {"label": "Belarus", "value": "BY"},
    {"label": "Belgium", "value": "BE"},
    {"label": "Belize", "value": "BZ"},
    {"label": "Benin", "value": "BJ"},
    {"label": "Bhutan", "value": "BT"},
    {"label": "Bolivia", "value": "BO"},
    {"label": "Bosnia and Herzegovina", "value": "BA"},
    {"label": "Botswana", "value": "BW"},
    {"label": "Brazil", "value": "BR"},
    {"label": "Brunei", "value": "BN"},
    {"label": "Bulgaria", "value": "BG"},
    {"label": "Burkina Faso", "value": "BF"},
    {"label": "Burundi", "value": "BI"},
    {"label": "Cabo Verde", "value": "CV"},
    {"label": "Cambodia", "value": "KH"},
    {"label": "Cameroon", "value": "CM"},
    {"label": "Canada", "value": "CA"},
    {"label": "Central African Republic", "value": "CF"},
    {"label": "Chad", "value": "TD"},
    {"label": "Chile", "value": "CL"},
    {"label": "China", "value": "CN"},
    {"label": "Colombia", "value": "CO"},
    {"label": "Comoros", "value": "KM"},
    {"label": "Congo (Brazzaville)", "value": "CG"},
    {"label": "Congo (Kinshasa)", "value": "CD"},
    {"label": "Costa Rica", "value": "CR"},
    {"label": "Croatia", "value": "HR"},
    {"label": "Cuba", "value": "CU"},
    {"label": "Cyprus", "value": "CY"},
    {"label": "Czech Republic", "value": "CZ"},
    {"label": "Denmark", "value": "DK"},
    {"label": "Djibouti", "value": "DJ"},
    {"label": "Dominica", "value": "DM"},
    {"label": "Dominican Republic", "value": "DO"},
    {"label": "Ecuador", "value": "EC"},
    {"label": "Egypt", "value": "EG"},
    {"label": "El Salvador", "value": "SV"},
    {"label": "Equatorial Guinea", "value": "GQ"},
    {"label": "Eritrea", "value": "ER"},
    {"label": "Estonia", "value": "EE"},
    {"label": "Eswatini", "value": "SZ"},
    {"label": "Ethiopia", "value": "ET"},
    {"label": "Fiji", "value": "FJ"},
    {"label": "Finland", "value": "FI"},
    {"label": "France", "value": "FR"},
    {"label": "Gabon", "value": "GA"},
    {"label": "Gambia", "value": "GM"},
    {"label": "Georgia", "value": "GE"},
    {"label": "Germany", "value": "DE"},
    {"label": "Ghana", "value": "GH"},
    {"label": "Greece", "value": "GR"},
    {"label": "Grenada", "value": "GD"},
    {"label": "Guatemala", "value": "GT"},
    {"label": "Guinea", "value": "GN"},
    {"label": "Guinea-Bissau", "value": "GW"},
    {"label": "Guyana", "value": "GY"},
    {"label": "Haiti", "value": "HT"},
    {"label": "Honduras", "value": "HN"},
    {"label": "Hungary", "value": "HU"},
    {"label": "Iceland", "value": "IS"},
    {"label": "India", "value": "IN"},
    {"label": "Indonesia", "value": "ID"},
    {"label": "Iran", "value": "IR"},
    {"label": "Iraq", "value": "IQ"},
    {"label": "Ireland", "value": "IE"},
    {"label": "Israel", "value": "IL"},
    {"label": "Italy", "value": "IT"},
    {"label": "Ivory Coast", "value": "CI"},
    {"label": "Jamaica", "value": "JM"},
    {"label": "Japan", "value": "JP"},
    {"label": "Jordan", "value": "JO"},
    {"label": "Kazakhstan", "value": "KZ"},
    {"label": "Kenya", "value": "KE"},
    {"label": "Kiribati", "value": "KI"},
    {"label": "Kosovo", "value": "XK"},
    {"label": "Kuwait", "value": "KW"},
    {"label": "Kyrgyzstan", "value": "KG"},
    {"label": "Laos", "value": "LA"},
    {"label": "Latvia", "value": "LV"},
    {"label": "Lebanon", "value": "LB"},
    {"label": "Lesotho", "value": "LS"},
    {"label": "Liberia", "value": "LR"},
    {"label": "Libya", "value": "LY"},
    {"label": "Liechtenstein", "value": "LI"},
    {"label": "Lithuania", "value": "LT"},
    {"label": "Luxembourg", "value": "LU"},
    {"label": "Madagascar", "value": "MG"},
    {"label": "Malawi", "value": "MW"},
    {"label": "Malaysia", "value": "MY"},
    {"label": "Maldives", "value": "MV"},
    {"label": "Mali", "value": "ML"},
    {"label": "Malta", "value": "MT"},
    {"label": "Marshall Islands", "value": "MH"},
    {"label": "Mauritania", "value": "MR"},
    {"label": "Mauritius", "value": "MU"},
    {"label": "Mexico", "value": "MX"},
    {"label": "Micronesia", "value": "FM"},
    {"label": "Moldova", "value": "MD"},
    {"label": "Monaco", "value": "MC"},
    {"label": "Mongolia", "value": "MN"},
    {"label": "Montenegro", "value": "ME"},
    {"label": "Morocco", "value": "MA"},
    {"label": "Mozambique", "value": "MZ"},
    {"label": "Myanmar", "value": "MM"},
    {"label": "Namibia", "value": "NA"},
    {"label": "Nauru", "value": "NR"},
    {"label": "Nepal", "value": "NP"},
    {"label": "Netherlands", "value": "NL"},
    {"label": "New Zealand", "value": "NZ"},
    {"label": "Nicaragua", "value": "NI"},
    {"label": "Niger", "value": "NE"},
    {"label": "Nigeria", "value": "NG"},
    {"label": "North Korea", "value": "KP"},
    {"label": "North Macedonia", "value": "MK"},
    {"label": "Norway", "value": "NO"},
    {"label": "Oman", "value": "OM"},
    {"label": "Pakistan", "value": "PK"},
    {"label": "Palau", "value": "PW"},
    {"label": "Palestine", "value": "PS"},
    {"label": "Panama", "value": "PA"},
    {"label": "Papua New Guinea", "value": "PG"},
    {"label": "Paraguay", "value": "PY"},
    {"label": "Peru", "value": "PE"},
    {"label": "Philippines", "value": "PH"},
    {"label": "Poland", "value": "PL"},
    {"label": "Portugal", "value": "PT"},
    {"label": "Qatar", "value": "QA"},
    {"label": "Romania", "value": "RO"},
    {"label": "Russia", "value": "RU"},
    {"label": "Rwanda", "value": "RW"},
    {"label": "Saint Kitts and Nevis", "value": "KN"},
    {"label": "Saint Lucia", "value": "LC"},
    {"label": "Saint Vincent and the Grenadines", "value": "VC"},
    {"label": "Samoa", "value": "WS"},
    {"label": "San Marino", "value": "SM"},
    {"label": "Sao Tome and Principe", "value": "ST"},
    {"label": "Saudi Arabia", "value": "SA"},
    {"label": "Senegal", "value": "SN"},
    {"label": "Serbia", "value": "RS"},
    {"label": "Seychelles", "value": "SC"},
    {"label": "Sierra Leone", "value": "SL"},
    {"label": "Singapore", "value": "SG"},
    {"label": "Slovakia", "value": "SK"},
    {"label": "Slovenia", "value": "SI"},
    {"label": "Solomon Islands", "value": "SB"},
    {"label": "Somalia", "value": "SO"},
    {"label": "South Africa", "value": "ZA"},
    {"label": "South Korea", "value": "KR"},
    {"label": "South Sudan", "value": "SS"},
    {"label": "Spain", "value": "ES"},
    {"label": "Sri Lanka", "value": "LK"},
    {"label": "Sudan", "value": "SD"},
    {"label": "Suriname", "value": "SR"},
    {"label": "Sweden", "value": "SE"},
    {"label": "Switzerland", "value": "CH"},
    {"label": "Syria", "value": "SY"},
    {"label": "Taiwan", "value": "TW"},
    {"label": "Tajikistan", "value": "TJ"},
    {"label": "Tanzania", "value": "TZ"},
    {"label": "Thailand", "value": "TH"},
    {"label": "Timor-Leste", "value": "TL"},
    {"label": "Togo", "value": "TG"},
    {"label": "Tonga", "value": "TO"},
    {"label": "Trinidad and Tobago", "value": "TT"},
    {"label": "Tunisia", "value": "TN"},
    {"label": "Turkey", "value": "TR"},
    {"label": "Turkmenistan", "value": "TM"},
    {"label": "Tuvalu", "value": "TV"},
    {"label": "Uganda", "value": "UG"},
    {"label": "Ukraine", "value": "UA"},
    {"label": "United Arab Emirates", "value": "AE"},
    {"label": "United Kingdom", "value": "GB"},
    {"label": "United States", "value": "US"},
    {"label": "Uruguay", "value": "UY"},
    {"label": "Uzbekistan", "value": "UZ"},
    {"label": "Vanuatu", "value": "VU"},
    {"label": "Vatican City", "value": "VA"},
    {"label": "Venezuela", "value": "VE"},
    {"label": "Vietnam", "value": "VN"},
    {"label": "Yemen", "value": "YE"},
    {"label": "Zambia", "value": "ZM"},
    {"label": "Zimbabwe", "value": "ZW"},
]


# ── Dataclasses ─────────────────────────────────────────────────────


@dataclass
class FormField:
    """A single input field within a form step."""

    id: str
    type: str  # text, static_select, checkboxes
    label: str
    required: bool = False
    multiline: bool = False
    options: list[dict[str, str]] | None = None
    options_from: str | None = None


@dataclass
class FormStep:
    """One step (page) in the multi-step registration modal."""

    id: str
    title: str
    step_type: str = "form"  # "form" or "statement"
    text: str | None = None
    condition: dict[str, str] | None = None  # {"field": "...", "equals": "..."}
    fields: list[FormField] = dc_field(default_factory=list)


@dataclass
class FormDefinition:
    """The full parsed form for a hackathon."""

    hackathon: str
    steps: list[FormStep]


# ── Parsing ─────────────────────────────────────────────────────────


def _parse_field(raw: dict[str, Any]) -> FormField:
    """Parse a single field dict from the YAML into a :class:`FormField`."""
    return FormField(
        id=raw["id"],
        type=raw["type"],
        label=raw["label"],
        required=raw.get("required", False),
        multiline=raw.get("multiline", False),
        options=raw.get("options"),
        options_from=raw.get("options_from"),
    )


def _parse_step(raw: dict[str, Any]) -> FormStep:
    """Parse a single step dict from the YAML into a :class:`FormStep`."""
    step_type = raw.get("type", "form")
    fields = [_parse_field(f) for f in raw.get("fields", [])]
    return FormStep(
        id=raw["id"],
        title=raw["title"],
        step_type=step_type,
        text=raw.get("text"),
        condition=raw.get("condition"),
        fields=fields,
    )


def load_form(yaml_path: str | Path) -> FormDefinition:
    """Load and parse a YAML form definition from *yaml_path*.

    Raises :class:`FileNotFoundError` if the path does not exist and
    :class:`ValueError` if the YAML is structurally invalid.
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Form YAML not found: {path}")

    with path.open() as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "hackathon" not in data or "steps" not in data:
        raise ValueError(f"Invalid form YAML — must contain 'hackathon' and 'steps': {path}")

    steps = [_parse_step(s) for s in data["steps"]]
    form = FormDefinition(hackathon=data["hackathon"], steps=steps)
    logger.info("Loaded form '%s' with %d steps from %s.", form.hackathon, len(steps), path)
    return form


def load_form_by_hackathon(hackathon_id: str) -> FormDefinition:
    """Find and load the form YAML for *hackathon_id*.

    Searches the project-level ``forms/`` directory for a file whose
    ``hackathon`` key matches *hackathon_id*.  Also tries
    ``forms/{hackathon_id}.yaml`` as a fast-path.

    Raises :class:`FileNotFoundError` if no matching form is found.
    """
    # Fast path: try the conventional filename first.
    candidate = _FORMS_DIR / f"{hackathon_id}.yaml"
    if candidate.exists():
        form = load_form(candidate)
        if form.hackathon == hackathon_id:
            return form

    # Slow path: scan all YAML files in the directory.
    for path in sorted(_FORMS_DIR.glob("*.yaml")):
        try:
            form = load_form(path)
            if form.hackathon == hackathon_id:
                return form
        except (ValueError, yaml.YAMLError):
            logger.warning("Skipping invalid form file: %s", path, exc_info=True)
            continue

    raise FileNotFoundError(f"No form YAML found for hackathon '{hackathon_id}' in {_FORMS_DIR}")


# ── Condition evaluation ────────────────────────────────────────────


def _step_condition_met(step: FormStep, answers: dict[str, str]) -> bool:
    """Return ``True`` if *step*'s condition is satisfied (or absent).

    A condition is a dict ``{"field": "<field_id>", "equals": "<value>"}``
    that checks whether the user's previous answer for that field matches.
    """
    if step.condition is None:
        return True
    field_id = step.condition["field"]
    expected = step.condition["equals"]
    return answers.get(field_id) == expected


def get_applicable_steps(form: FormDefinition, answers: dict[str, str]) -> list[FormStep]:
    """Return only steps whose conditions are met given current *answers*.

    Unconditional steps are always included.  Steps with a ``condition``
    key are included only when the referenced answer matches the expected
    value.
    """
    return [step for step in form.steps if _step_condition_met(step, answers)]
