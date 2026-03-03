"""Constant reference data for properties, cost centers, and mappings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Property:
    name: str
    property_type: str  # "hotel" | "restaurant"
    short_code: str
    cost_center: str
    drive_folder: str
    slack_channel: str


# ── Property Registry ─────────────────────────────────────────────────────

PROPERTIES: list[Property] = [
    Property("Hôtel Le Cèdre",       "hotel",      "HLC", "CC-01", "CC-01_LeCedre",           "#hotel-lecedre"),
    Property("Hôtel des Arènes",     "hotel",      "HDA", "CC-02", "CC-02_DesArenes",          "#hotel-desarenes"),
    Property("Villa Margot",          "hotel",      "VMA", "CC-03", "CC-03_VillaMargot",        "#hotel-villamargot"),
    Property("Le Refuge Urbain",     "hotel",      "LRU", "CC-04", "CC-04_RefugeUrbain",       "#hotel-refugeurbain"),
    Property("Hôtel Bastide Sud",    "hotel",      "HBS", "CC-05", "CC-05_BastideSud",         "#hotel-bastidesud"),
    Property("Maison Colette",       "hotel",      "MCO", "CC-06", "CC-06_MaisonColette",      "#hotel-maisoncolette"),
    Property("Restaurant Le Patio",  "restaurant", "RLP", "CC-07", "CC-07_LePatio",            "#restaurant-lepatio"),
    Property("Brasserie des Halles", "restaurant", "BDH", "CC-08", "CC-08_BrasserieDesHalles", "#brasserie-deshalles"),
]

# ── Lookup helpers ─────────────────────────────────────────────────────────

PROPERTIES_BY_CC: dict[str, Property] = {p.cost_center: p for p in PROPERTIES}
PROPERTIES_BY_CODE: dict[str, Property] = {p.short_code: p for p in PROPERTIES}

COST_CENTER_FOLDERS: dict[str, str] = {p.cost_center: p.drive_folder for p in PROPERTIES}
CC_SLACK_CHANNELS: dict[str, str] = {p.cost_center: p.slack_channel for p in PROPERTIES}


# ── GL Account Reference ──────────────────────────────────────────────────

GL_ACCOUNTS: dict[str, str] = {
    "607100": "Achats de marchandises — Alimentation & Boissons",
    "615000": "Entretien et réparations",
    "606400": "Fournitures de linge et blanchisserie",
    "626000": "Frais postaux et télécommunications",
    "606100": "Énergie (électricité, gaz)",
    "616000": "Assurances",
    "626700": "Logiciels et abonnements",
    "606200": "Fournitures de nettoyage",
    "623100": "Publicité et marketing",
    "622000": "Honoraires juridiques et comptables",
}

# GL codes where VAT is expected to be exempt (0%)
VAT_EXEMPT_GL_CODES: set[str] = {"616000"}

# GL codes where mixed VAT rates are common
MIXED_VAT_GL_CODES: set[str] = {"607100"}


# ── VAT Rates (France) ────────────────────────────────────────────────────

STANDARD_VAT_RATES: dict[str, float] = {
    "standard": 0.20,
    "intermediate": 0.10,
    "reduced": 0.055,
    "super_reduced": 0.021,
    "exempt": 0.0,
}


# ── Property Email Map ────────────────────────────────────────────────────
# Populated during onboarding with actual property addresses.
# Used by cost_center_router to detect CC from email headers.

PROPERTY_EMAIL_MAP: dict[str, str] = {
    # "lecedre@example.com": "CC-01",
    # "desarenes@example.com": "CC-02",
    # ... filled per property on hiring
}
