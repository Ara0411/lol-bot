"""LoL 닉네임 파싱: '이름/티어/포지션' 형식."""

from dataclasses import dataclass


# 매칭은 긴 키부터 시도해야 GM이 G로, 다이아몬드가 다이아로 잡히지 않음
TIER_BASES: list[tuple[str, int, bool]] = [
    ("그랜드마스터", 8000, True),
    ("다이아몬드", 6000, False),
    ("CHALL", 9000, True),
    ("챌린저", 9000, True),
    ("플래티넘", 4000, False),
    ("에메랄드", 5000, False),
    ("마스터", 7000, True),
    ("다이아", 6000, False),
    ("브론즈", 1000, False),
    ("아이언", 500, False),
    ("에메", 5000, False),
    ("플레", 4000, False),
    ("실버", 2000, False),
    ("골드", 3000, False),
    ("GM", 8000, True),
    ("C", 9000, True),
    ("M", 7000, True),
    ("D", 6000, False),
    ("E", 5000, False),
    ("P", 4000, False),
    ("G", 3000, False),
    ("S", 2000, False),
    ("B", 1000, False),
    ("I", 500, False),
]
TIER_BASES.sort(key=lambda x: -len(x[0]))


POS_MAP: dict[str, str] = {
    # 영문 → 영문 캐노니컬
    "TOP": "TOP", "TOPLANE": "TOP",
    "JUG": "JG", "JUNGLE": "JG", "JG": "JG",
    "MID": "MID",
    "ADC": "AD", "AD": "AD", "BOT": "AD", "BOTTOM": "AD",
    "SUP": "SUP", "SUPPORT": "SUP", "SUPP": "SUP",
    # 한글 → 영문 캐노니컬
    "탑": "TOP",
    "정글": "JG",
    "미드": "MID",
    "원딜": "AD",
    "서폿": "SUP", "서포터": "SUP",
}


# 그룹 표시용 정규화 — 모든 별칭을 하나의 캐노니컬 이름으로 묶음
TIER_KEY_TO_NAME: dict[str, str] = {
    "챌린저": "챌린저", "CHALL": "챌린저", "C": "챌린저",
    "그랜드마스터": "그랜드마스터", "GM": "그랜드마스터",
    "마스터": "마스터", "M": "마스터",
    "다이아몬드": "다이아", "다이아": "다이아", "D": "다이아",
    "에메랄드": "에메랄드", "에메": "에메랄드", "E": "에메랄드",
    "플래티넘": "플래티넘", "플레": "플래티넘", "P": "플래티넘",
    "골드": "골드", "G": "골드",
    "실버": "실버", "S": "실버",
    "브론즈": "브론즈", "B": "브론즈",
    "아이언": "아이언", "I": "아이언",
}


# 정렬 우선순위 (높을수록 상위 티어) — LP 많은 마스터가 그마 위로 가는 걸 방지
TIER_ORDER_MAP: dict[str, int] = {
    "챌린저": 10,
    "그랜드마스터": 9,
    "마스터": 8,
    "다이아": 7,
    "에메랄드": 6,
    "플래티넘": 5,
    "골드": 4,
    "실버": 3,
    "브론즈": 2,
    "아이언": 1,
}


# 표시용 영문 축약
TIER_SHORT: dict[str, str] = {
    "챌린저": "C",
    "그랜드마스터": "GM",
    "마스터": "M",
    "다이아": "D",
    "에메랄드": "E",
    "플래티넘": "P",
    "골드": "G",
    "실버": "S",
    "브론즈": "B",
    "아이언": "I",
}


@dataclass
class ParsedNickname:
    name: str
    tier_raw: str
    tier_name: str
    tier_order: int
    tier_short: str
    tier_number: int
    tier_score: int
    positions: list[str]
    is_valid: bool

    @property
    def positions_display(self) -> str:
        return ", ".join(self.positions)

    @property
    def tier_display(self) -> str:
        """영문 축약형 표시: 'C', 'M350', 'D1' 등."""
        if self.tier_number > 0:
            return f"{self.tier_short}{self.tier_number}"
        return self.tier_short


def _parse_tier(tier_text: str) -> tuple[str, int | None, str, int, str, int]:
    text = tier_text.strip().upper()
    if not text:
        return tier_text.strip(), None, "", 0, "", 0
    for key, base, is_high in TIER_BASES:
        ukey = key.upper()
        if text.startswith(ukey):
            tail = text[len(ukey):].strip()
            digits = "".join(c for c in tail if c.isdigit())
            num = int(digits) if digits else 0
            tier_name = TIER_KEY_TO_NAME.get(key, key)
            tier_order = TIER_ORDER_MAP.get(tier_name, 0)
            tier_short = TIER_SHORT.get(tier_name, "")
            if is_high:
                return tier_text.strip(), base + num, tier_name, tier_order, tier_short, num
            return tier_text.strip(), base + (5 - num) * 100, tier_name, tier_order, tier_short, num
    return tier_text.strip(), None, "", 0, "", 0


def _parse_positions(text: str) -> list[str]:
    text = text.replace(",", ".").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(".") if p.strip()]
    return [POS_MAP.get(p.upper(), p) for p in parts]


def parse_nickname(nick: str) -> ParsedNickname:
    nick = nick.strip()
    parts = nick.split("/")
    if len(parts) < 3:
        return ParsedNickname(
            name=nick, tier_raw="", tier_name="", tier_order=0,
            tier_short="", tier_number=0,
            tier_score=0, positions=[], is_valid=False,
        )

    name = "/".join(parts[:-2]).strip()
    tier_text = parts[-2].strip()
    pos_text = parts[-1].strip()

    tier_raw, tier_score, tier_name, tier_order, tier_short, tier_number = _parse_tier(tier_text)
    positions = _parse_positions(pos_text)

    if tier_score is None or not positions:
        return ParsedNickname(
            name=nick, tier_raw="", tier_name="", tier_order=0,
            tier_short="", tier_number=0,
            tier_score=0, positions=[], is_valid=False,
        )

    return ParsedNickname(
        name=name,
        tier_raw=tier_raw,
        tier_name=tier_name,
        tier_order=tier_order,
        tier_short=tier_short,
        tier_number=tier_number,
        tier_score=tier_score,
        positions=positions,
        is_valid=True,
    )


if __name__ == "__main__":
    import sys

    CASES = [
        ("맞다이전문유부남/E2/TOP.MID.SUP", "맞다이전문유부남", 5300, ["TOP", "MID", "SUP"], True),
        ("심술 두꺼비/에메랄드2/원딜, 미드", "심술 두꺼비", 5300, ["AD", "MID"], True),
        ("완댕이/M350/미드.탑", "완댕이", 7350, ["MID", "TOP"], True),
        ("석이/G3/SUP", "석이", 3200, ["SUP"], True),
        ("정도/다이아1/JG.MID", "정도", 6400, ["JG", "MID"], True),
        ("프로/C/MID", "프로", 9000, ["MID"], True),
        ("그냥닉네임", "그냥닉네임", 0, [], False),
        ("이름/E2", "이름/E2", 0, [], False),
        ("a/b/E2/TOP", "a/b", 5300, ["TOP"], True),
    ]

    passed = failed = 0
    for nick, exp_name, exp_score, exp_pos, exp_valid in CASES:
        p = parse_nickname(nick)
        ok = (
            p.name == exp_name
            and p.tier_score == exp_score
            and p.positions == exp_pos
            and p.is_valid == exp_valid
        )
        if ok:
            passed += 1
            print(f"PASS  {nick!r}")
        else:
            failed += 1
            print(f"FAIL  {nick!r}")
            print(f"  expected: name={exp_name!r} score={exp_score} pos={exp_pos} valid={exp_valid}")
            print(f"  actual:   name={p.name!r} score={p.tier_score} pos={p.positions} valid={p.is_valid}")

    print()
    print(f"{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
