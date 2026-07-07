"""Master-data lists that power the dropdown + autocomplete (<datalist>) fields
across the forms. Demo content — edit freely. Injected into every template as `md`."""

COMPANIES = [
    "T-Group Automotive", "T-Group Textile", "T-Group Real Estate", "T-Group Holding",
]

SITES = [
    "Head Office", "Textile Factory", "Central Warehouse", "Real Estate Office",
    "Automotive Showroom", "Logistics Hub", "Spinning Plant", "Dyeing Plant",
]

DEPARTMENTS = [
    "IT", "IT Security", "Facilities", "Warehouse", "Production", "Executive",
    "Internal Audit", "Finance", "HR", "Operations", "Procurement", "Maintenance",
    "Sales", "Quality", "Logistics", "R&D",
]

LOCATIONS = [
    "Floor 1", "Floor 2", "Floor 3", "Server Room", "Reception", "Data Center",
    "Warehouse Bay A", "Warehouse Bay B", "Production Line A", "Production Line B",
    "Meeting Room", "Executive Suite", "Loading Dock", "Workshop",
]

BRANDS = [
    "Dell", "HP", "HPE", "Lenovo", "Cisco", "Ubiquiti", "Aruba", "APC", "Canon",
    "Zebra", "Samsung", "Apple", "Microsoft", "Fortinet", "Synology", "Epson",
    "Brother", "Logitech", "Kyocera", "Eaton", "TP-Link", "Huawei",
]

MODELS = [
    "OptiPlex 7010", "EliteBook 840", "ThinkPad X1", "PowerEdge R750", "Catalyst 9200",
    "LaserJet M428", "Smart-UPS 3000", "UDM Pro", "6100 Switch", "imageRUNNER C3226",
    "ZT411", "iPhone 14", "Surface Pro", "PowerVault ME5",
]

# Demo people for requester / custodian autocomplete (includes the seeded users).
PEOPLE = [
    "Omar Khaled", "Sara Nabil", "Youssef Adel", "Mona Fathy", "Hassan Ali",
    "Layla Mansour", "Karim Saad", "Nour Tarek", "Ahmed ElGohary", "Mohamed Salah",
    "Aya Hassan", "Tarek Nabil", "Dina Farouk", "Khaled Mostafa", "Rana Adel",
    "Yasmin Ali", "Amr Zaki", "Heba Sami", "Mostafa Kamal", "Salma Hany",
    "Mahmoud Fawzy", "Nada Sherif", "Islam Gamal", "Passant Adham", "Ziad Hesham",
]


def as_dict():
    return {
        "companies": COMPANIES, "sites": SITES, "departments": DEPARTMENTS,
        "locations": LOCATIONS, "brands": BRANDS, "models": MODELS, "people": PEOPLE,
    }
