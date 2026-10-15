"""Stable item vocabulary. IDs are permanent: never renumber, never reuse. Excel row numbers mean nothing here."""

MATERIALS = {
    "M01": ("EA", "Post, Type A terminal / corner / gate"),
    "M02": ("EA", "Post, Type A line"),
    "M03": ("EA", "Post, Type B terminal"),
    "M04": ("EA", "Post, Type B line"),
    "M05": ("LF", "Top rail"),
    "M06": ("LF", "Mid rail / brace rail, Type A"),
    "M07": ("EA", "Rail sleeve / coupling"),
    "M08": ("EA", "Truss rod with turnbuckle, fence braces"),
    "M09": ("EA", "Brace band, terminal-side"),
    "M10": ("EA", "Brace band, line-post side"),
    "M11": ("EA", "Rail end cup / rail end band"),
    "M12": ("EA", "Tension bar, Type A"),
    "M13": ("EA", "Tension bar, Type B"),
    "M14": ("EA", "Tension band, 2-7/8 in post"),
    "M15": ("EA", "Tension band, 2-3/8 in post"),
    "M16": ("EA", "Post cap, 2-7/8 in"),
    "M17": ("EA", "Post cap, 2-3/8 in"),
    "M18": ("EA", "Post cap, 1-7/8 in"),
    "M19": ("LF", "Chain link fabric, 10 ft"),
    "M20": ("LF", "Chain link fabric, 42 in"),
    "M21": ("LF", "Gate leaf fabric"),
    "M22": ("LF", "Transom fabric above gate header"),
    "M23": ("LF", "Bottom tension wire"),
    "M24": ("EA", "Fabric tie, 2-3/8 in post (Type A line)"),
    "M25": ("EA", "Fabric tie, 1-7/8 in post (Type B line)"),
    "M26": ("EA", "Fabric tie, 1-5/8 in rail"),
    "M27": ("EA", "Tension wire tie / hog ring"),
    "M28": ("LF", "Gate frame pipe"),
    "M29": ("EA", "Gate frame elbow"),
    "M30": ("EA", "Gate frame tee"),
    "M31": ("EA", "Truss rod, gate leaf, adjustable"),
    "M32": ("EA", "Gate hinge, 180 degree"),
    "M33": ("EA", "Gate latch, industrial fork with padlock eye"),
    "M34": ("EA", "Gate hold-back / stop"),
    "M35": ("LF", "Header rail"),
    "M36": ("EA", "Tension bar, gate leaf"),
    "M37": ("EA", "Tension band, 1-7/8 in frame"),
    "M38": ("LF", "Windscreen"),
    "M39": ("EA", "Cable tie, UV-resistant nylon"),
    "M40": ("CU YD", "Ready-mix concrete"),
    "M42": ("LF", "Fence guard, UV-stabilized polyethylene, on Type B top rail"),
    "M43": ("EA", "Gate center drop rod, double-leaf gate"),
    "M44": ("EA", "Gate ground socket, for center drop rod"),
}

# Subcontracted / purchased services priced per unit. Not materials: no sales tax is applied to them.
SERVICES = {
    "S01": ("EA", "Core drilling through pavement and base, per footing hole"),
}

# Material items incorporated into the Work (eligible for an owner's sales-tax exemption). Tools, machinery, equipment and
# non-incorporated supplies are NOT materials in this catalog; they live in Equipment/Mobilization and are never tax-exempted here.
INCORPORATED = frozenset(MATERIALS)

DRIVERS = {
    "D01": ("LF", "Type A net fence length"),
    "D02": ("LF", "Type B (divider) fence length"),
    "D03": ("EA", "Posts to set, all types"),
    "D04": ("EA", "Footing holes to drill, all types"),
    "D05": ("CU YD", "Concrete placed"),
    "D06": ("LF", "Top rail to install"),
    "D07": ("LF", "Fabric to hang, all types"),
    "D08": ("EA", "Braces (truss rod + brace rail)"),
    "D09": ("EA", "Gates to hang"),
    "D10": ("LF", "Windscreen to install"),
    "D11": ("LF", "Tension wire to install"),
    "D12": ("LF", "Layout / stakeout length (gross perimeter + dividers)"),
}

# IDs that existed once and must never be priced again. M41 (bagged concrete) double-counted M40.
RETIRED = {"M41": "Bagged concrete was an alternate to M40 and double-counted concrete; M40 is the sole concrete supply item."}

UNITS = ("EA", "LF", "CU YD")
BASE = "BASE"


def uom(key):
    """Canonical unit for a material item_id or labor driver_key, or None if the key is unknown."""
    row = MATERIALS.get(key) or SERVICES.get(key) or DRIVERS.get(key)
    return row[0] if row else None


def is_material(key):
    return key in MATERIALS


def is_service(key):
    return key in SERVICES


def is_driver(key):
    return key in DRIVERS
