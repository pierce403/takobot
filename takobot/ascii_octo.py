from __future__ import annotations

from .life_stage import LifeStage, life_stage_from_name


STAGE_OCTO_ART: dict[LifeStage, str] = {
    LifeStage.HATCHLING: (
        "   o\n"
        "  >o<\n"
        "  / \\\n"
        " tiny hatchling"
    ),
    LifeStage.CHILD: (
        "      o\n"
        "    .-\"\"-.\n"
        "   /  o o  \\\n"
        "   |   ^   |\n"
        "   |  ---  |\n"
        "    \\_____/\n"
        "  _/ /| |\\  _\\\n"
        " /__/_|_|_\\__\\\n"
        " curious child"
    ),
    LifeStage.TEEN: (
        "   >>  o   <<\n"
        "   .-~~~~~~-.\n"
        "  /  o   o   \\\n"
        "  |    ><    |\n"
        "  |  .----.  |\n"
        "   \\______/\n"
        " _/\\_/\\_/\\_/\\_\n"
        "/__\\/__\\/__\\/__\\\n"
        " skeptical teen"
    ),
    LifeStage.ADULT: (
        "        o\n"
        "     .-\"\"\"\"-.\n"
        "    /   O  O   \\\n"
        "    |    ><    |\n"
        "    |  \\____/  |\n"
        "     \\________/\n"
        "   _/\\/\\_/\\_/\\_/\\_\n"
        "  /__/__/__/__/__/__\\\n"
        "      [_____]\n"
        "   strategic adult"
    ),
}


def octopus_ascii_for_stage(stage_name: str, *, frame: int = 0) -> str:
    stage = life_stage_from_name(stage_name)
    art = STAGE_OCTO_ART.get(stage) or STAGE_OCTO_ART[LifeStage.HATCHLING]
    bubble_offsets = (2, 4, 3, 5)
    bubble = " " * bubble_offsets[frame % len(bubble_offsets)] + "o"
    return f"{bubble}\n{art}"
