import re

PATTERNS = [
    r"P(\d{2,4})",  # P101, P205
    r"phong[_\s\-]?(\d+)",  # phong_101
    r"room[_\s\-]?(\d+)",  # room_101
    r"^(\d{2,4})\.",  # 101.jpg
    r"[_\-](\d{2,4})[_\-\.]",  # abc_101.jpg
]


def extract_room_number(filename: str) -> str | None:
    filename_lower = filename.lower()
    for pattern in PATTERNS:
        match = re.search(pattern, filename_lower)
        if match:
            return match.group(1)
    return None
