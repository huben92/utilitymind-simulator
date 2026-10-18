"""Utilities transcribed from the 'Utility Manufaktur Velg Mobil' Miro board."""

AREAS = [
    ("Raw Material Warehouse", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Charging Area", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False), ("Natural Gas", False), ("Diesel", False)]),
    ("Melting Furnace", [("Natural Gas", True), ("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Rotary Degassing and Fluxing Machine (Online Molten Metal Treatment Unit)", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False), ("Natural Gas", False)]),
    ("Holding Furnace", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False), ("Natural Gas", False)]),
    ("Auto-Ladle / Dosing Unit", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Low Pressure Die Casting", [("Electricity", True), ("Compressed Air", True), ("Clean Water", True)]),
    ("Unloader Robot / Manipulator Arm", [("Electricity", True), ("Compressed Air", True), ("Clean Water", False)]),
    ("Cooling Tank / Air Quenching Station", [("Electricity", True), ("Clean Water", True), ("Compressed Air", False)]),
    ("Riser & Gate Cutting Machine (Gergaji Potong Otomatis)", [("Electricity", True), ("Compressed Air", True)]),
    ("Real-Time X-Ray Inspection Machine", [("Electricity", True), ("Compressed Air", False)]),
    ("Forging Press", [("Electricity", True), ("Clean Water", False)]),
    ("Trimming Press Machine", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Spinning / Rim Rolling Machine", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Continuous T6 Heat Treatment Furnace Line", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False), ("Natural Gas", False)]),
    ("Shot Blasting Machine", [("Electricity", True), ("Compressed Air", False)]),
    ("Washing & Pre-treatment Line", [("Electricity", True), ("Clean Water", True), ("Compressed Air", False), ("Natural Gas", False)]),
    ("Painting & Coating Line", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False), ("Natural Gas", False)]),
    ("Quality Control & Testing", [("Electricity", True), ("Clean Water", False), ("Compressed Air", False)]),
    ("Final Assembly", [("Electricity", True), ("Compressed Air", False)]),
    ("Packaging", [("Electricity", True), ("Compressed Air", False)]),
    ("Final Product Warehouse", [("Electricity", True)]),
]

METRICS = {
    "Electricity": {"unit": "kW", "min": 0, "max": 500, "default": 95},
    "Clean Water": {"unit": "m³/h", "min": 0, "max": 100, "default": 22},
    "Compressed Air": {"unit": "m³/h", "min": 0, "max": 150, "default": 38},
    "Natural Gas": {"unit": "m³/h", "min": 0, "max": 120, "default": 30},
    "Diesel": {"unit": "L/h", "min": 0, "max": 100, "default": 24},
}
