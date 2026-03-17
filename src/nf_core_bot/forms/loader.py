"""Load and validate YAML form definitions from the hackathons/ directory.

Each hackathon has a YAML file in ``hackathons/`` that declares a multi-step
registration form.  This module parses that YAML into typed dataclasses and
provides helpers for conditional step evaluation.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── Project root — resolved relative to this file ───────────────────

_FORMS_DIR = Path(__file__).resolve().parents[3] / "hackathons"

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

# value → label lookup for O(1) country label resolution.
COUNTRY_LABELS: dict[str, str] = {c["value"]: c["label"] for c in COUNTRIES}

# ── Validation constants ────────────────────────────────────────────

VALID_STATUSES = frozenset({"draft", "open", "closed", "archived"})
_REQUIRED_METADATA = ("hackathon", "title", "status", "channel", "url", "date_start", "date_end", "steps")

_CHANNEL_URL_RE = re.compile(r"https?://[a-z]+\.slack\.com/archives/(C[A-Z0-9]+)")
_CHANNEL_ID_RE = re.compile(r"^C[A-Z0-9]+$")


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_channel_id(value: str) -> str:
    """Extract Slack channel ID from a URL or raw ID.

    Accepts:
      - https://nfcore.slack.com/archives/C0ACF0TPF5E
      - C0ACF0TPF5E
    Returns the channel ID string.
    Raises ValueError if the format is not recognized.
    """
    m = _CHANNEL_URL_RE.match(value)
    if m:
        return m.group(1)
    if _CHANNEL_ID_RE.match(value):
        return value
    raise ValueError(f"Unrecognised Slack channel format: {value!r}")


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
    title: str
    status: str  # draft | open | closed | archived
    channel_id: str  # Always the raw ID (C...), parsed from URL or raw ID
    url: str
    date_start: str  # YYYY-MM-DD
    date_end: str  # YYYY-MM-DD
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

    if not isinstance(data, dict):
        raise ValueError(f"Invalid form YAML — expected a mapping: {path}")

    missing = [key for key in _REQUIRED_METADATA if key not in data]
    if missing:
        raise ValueError(f"Invalid form YAML — missing required fields {missing}: {path}")

    # Validate status
    status = data["status"]
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r} in {path} — must be one of {sorted(VALID_STATUSES)}")

    # Validate dates
    for date_key in ("date_start", "date_end"):
        try:
            datetime.date.fromisoformat(str(data[date_key]))
        except ValueError as exc:
            raise ValueError(f"Invalid {date_key} {data[date_key]!r} in {path}: {exc}") from exc

    # Parse channel
    channel_id = _parse_channel_id(str(data["channel"]))

    steps = [_parse_step(s) for s in data["steps"]]
    form = FormDefinition(
        hackathon=data["hackathon"],
        title=data["title"],
        status=status,
        channel_id=channel_id,
        url=data["url"],
        date_start=str(data["date_start"]),
        date_end=str(data["date_end"]),
        steps=steps,
    )
    logger.info("Loaded form '%s' with %d steps from %s.", form.hackathon, len(steps), path)
    return form


def load_form_by_hackathon(hackathon_id: str) -> FormDefinition:
    """Find and load the form YAML for *hackathon_id*.

    Searches the project-level ``hackathons/`` directory for a file whose
    ``hackathon`` key matches *hackathon_id*.  Also tries
    ``hackathons/{hackathon_id}.yaml`` as a fast-path.

    Raises :class:`FileNotFoundError` if no matching form is found.
    """
    # Fast path: try the conventional filename first.
    candidate = _FORMS_DIR / f"{hackathon_id}.yaml"
    tried_candidate = False
    if candidate.exists():
        tried_candidate = True
        form = load_form(candidate)
        if form.hackathon == hackathon_id:
            return form

    # Slow path: scan all YAML files in the directory.
    for path in sorted(_FORMS_DIR.glob("*.yaml")):
        if tried_candidate and path.resolve() == candidate.resolve():
            continue
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


# ── Metadata helpers ────────────────────────────────────────────────


def _form_to_dict(form: FormDefinition) -> dict[str, str]:
    """Convert a FormDefinition to a dict for backward compatibility.

    Returns dict with keys: hackathon_id, title, status, channel_id, url, date_start, date_end.
    Note: uses 'hackathon_id' as key (not 'hackathon') for compatibility with existing callers.
    """
    return {
        "hackathon_id": form.hackathon,
        "title": form.title,
        "status": form.status,
        "channel_id": form.channel_id,
        "url": form.url,
        "date_start": form.date_start,
        "date_end": form.date_end,
    }


def list_all_forms() -> list[dict[str, str]]:
    """Scan the hackathons/ directory and return metadata for all hackathon forms.

    Returns a list of dicts sorted by date_start descending (most recent first).
    Silently skips YAML files that fail to parse (logs a warning).
    """
    results: list[dict[str, str]] = []
    for path in sorted(_FORMS_DIR.glob("*.yaml")):
        try:
            form = load_form(path)
            results.append(_form_to_dict(form))
        except Exception:
            logger.warning("Skipping unparseable form file: %s", path, exc_info=True)
            continue
    results.sort(key=lambda d: d["date_start"], reverse=True)
    return results


def get_active_form() -> dict[str, str] | None:
    """Find the hackathon form with status='open'.

    Returns a dict with hackathon metadata, or None if no form has status 'open'.
    """
    for entry in list_all_forms():
        if entry["status"] == "open":
            return entry
    return None


def get_form_metadata(hackathon_id: str) -> dict[str, str] | None:
    """Load metadata for a specific hackathon by ID.

    Returns a dict, or None if no matching form YAML exists.
    """
    try:
        form = load_form_by_hackathon(hackathon_id)
        return _form_to_dict(form)
    except FileNotFoundError:
        return None
