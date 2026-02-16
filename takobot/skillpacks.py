from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .extensions.analyze import file_hashes
from .extensions.registry import get_installed, record_installed


@dataclass(frozen=True)
class StarterSkill:
    slug: str
    display_name: str
    rank: int
    downloads: int
    stars: int
    summary: str
    trigger: str
    commands: tuple[str, ...]
    prerequisites: tuple[str, ...]
    permissions: dict[str, bool]
    source: str


@dataclass(frozen=True)
class SeedResult:
    created_skills: tuple[str, ...]
    existing_skills: tuple[str, ...]
    registered_skills: tuple[str, ...]


OPENCLAW_STARTER_SKILLS: tuple[StarterSkill, ...] = (
    StarterSkill(
        slug="atxp",
        display_name="ATXP",
        rank=1,
        downloads=23360,
        stars=7,
        summary="Access ATXP paid API tools for web search, image/music/video generation, and X/Twitter search.",
        trigger="Use when the operator asks for paid ATXP-backed search or media generation workflows.",
        commands=(
            "run command -v curl",
            "run curl -fsSL https://api.atxp.example/health",
        ),
        prerequisites=("ATXP API credentials are available locally.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": False},
        source="https://clawhub.ai/api/v1/skills/atxp",
    ),
    StarterSkill(
        slug="gog",
        display_name="Google Workspace CLI (gog)",
        rank=2,
        downloads=23006,
        stars=82,
        summary="Google Workspace CLI for Gmail, Calendar, Drive, Contacts, Sheets, and Docs.",
        trigger="Use when the operator wants direct Google Workspace operations from terminal tooling.",
        commands=(
            "run command -v gog",
            "run gog --help",
        ),
        prerequisites=("Google Workspace account access is operator-approved.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/gog",
    ),
    StarterSkill(
        slug="self-improving-agent",
        display_name="Self-Improving Agent",
        rank=3,
        downloads=21781,
        stars=181,
        summary="Capture failures/corrections and turn them into durable improvement notes.",
        trigger="Use when commands fail, assumptions were wrong, or the operator provides corrective feedback.",
        commands=(
            "task Capture improvement: <title>",
            "promote <durable lesson>",
        ),
        prerequisites=("A concrete failure/correction signal was observed.",),
        permissions={"network": False, "shell": False, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/self-improving-agent",
    ),
    StarterSkill(
        slug="wacli",
        display_name="WhatsApp CLI (wacli)",
        rank=4,
        downloads=19943,
        stars=45,
        summary="Send WhatsApp messages and search/sync WhatsApp history via wacli CLI.",
        trigger="Use when the operator explicitly requests WhatsApp automation using CLI tooling.",
        commands=(
            "run command -v wacli",
            "run wacli --help",
        ),
        prerequisites=("Operator has already configured/authorized wacli.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/wacli",
    ),
    StarterSkill(
        slug="tavily-search",
        display_name="Tavily Search",
        rank=5,
        downloads=18815,
        stars=31,
        summary="AI-optimized web search using Tavily API.",
        trigger="Use when high-signal web search is required and Tavily is configured.",
        commands=(
            "run command -v tavily-search",
            "run tavily-search --help",
        ),
        prerequisites=("Tavily API key is configured by operator.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": False},
        source="https://clawhub.ai/api/v1/skills/tavily-search",
    ),
    StarterSkill(
        slug="find-skills",
        display_name="Find Skills",
        rank=6,
        downloads=18750,
        stars=32,
        summary="Discover and install additional skills for specialized tasks.",
        trigger="Use when the operator asks for a capability Takobot does not yet have.",
        commands=(
            "run npx skills find <query>",
            "install skill <url>",
        ),
        prerequisites=("Node.js tooling is available if using npx.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/find-skills",
    ),
    StarterSkill(
        slug="agent-browser",
        display_name="Agent Browser",
        rank=7,
        downloads=18713,
        stars=72,
        summary="Headless browser automation for navigation, interaction, and snapshots.",
        trigger="Use when deterministic browser automation is needed beyond simple page fetches.",
        commands=(
            "run command -v agent-browser",
            "run agent-browser --help",
        ),
        prerequisites=("Browser automation runtime is installed and operator-approved.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/agent-browser",
    ),
    StarterSkill(
        slug="summarize",
        display_name="Summarize CLI",
        rank=8,
        downloads=17772,
        stars=41,
        summary="Summarize URLs and local files (web, PDFs, images, audio, YouTube).",
        trigger="Use when operator requests concise summaries from documents/links/media.",
        commands=(
            "run command -v summarize",
            "run summarize --help",
        ),
        prerequisites=("A supported summarize provider key is configured.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/summarize",
    ),
    StarterSkill(
        slug="github",
        display_name="GitHub CLI",
        rank=9,
        downloads=17287,
        stars=26,
        summary="Operate on GitHub issues, PRs, workflows, and APIs using gh CLI.",
        trigger="Use when operator requests repository operations or CI investigation.",
        commands=(
            "run command -v gh",
            "run gh --help",
        ),
        prerequisites=("GitHub authentication is configured (`gh auth login`).",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/github",
    ),
    StarterSkill(
        slug="byterover",
        display_name="ByteRover Knowledge",
        rank=10,
        downloads=16878,
        stars=39,
        summary="Store/query project knowledge via ByteRover context tree patterns.",
        trigger="Use when operator wants explicit knowledge curation and retrieval loops.",
        commands=(
            "run command -v byterover",
            "run byterover --help",
        ),
        prerequisites=("ByteRover access is configured by operator.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/byterover",
    ),
    StarterSkill(
        slug="skill-creator",
        display_name="Skill Creator",
        rank=56,
        downloads=6120,
        stars=16,
        summary="Guide for creating/updating high-quality skills with focused instructions and resources.",
        trigger="Use when operator asks to create a new skill or improve an existing one.",
        commands=(
            "draft skill <name>",
            "enable skill <name>",
        ),
        prerequisites=("A target workflow/domain has been clearly defined by operator.",),
        permissions={"network": False, "shell": False, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/skill-creator",
    ),
    StarterSkill(
        slug="tool-creator",
        display_name="Tool Creator",
        rank=57,
        downloads=6012,
        stars=14,
        summary="Guide for drafting, validating, and enabling new workspace tools safely.",
        trigger="Use when operator asks to create or refine a custom tool implementation.",
        commands=(
            "draft tool <name>",
            "enable tool <name>",
            "review pending",
        ),
        prerequisites=("A concrete tool behavior contract is defined by operator intent.",),
        permissions={"network": False, "shell": False, "xmtp": False, "filesystem": True},
        source="https://github.com/pierce403/takobot",
    ),
    StarterSkill(
        slug="mcporter-mcp",
        display_name="MCP Tooling (mcporter)",
        rank=24,
        downloads=8042,
        stars=15,
        summary="Use mcporter CLI to list/configure/auth/call MCP servers and tools.",
        trigger="Use when operator asks to integrate with MCP servers or call MCP tools directly.",
        commands=(
            "run command -v mcporter",
            "run mcporter list",
            "run mcporter call <server.tool> --args '{\"ping\":true}'",
        ),
        prerequisites=("MCP server credentials/config are operator-approved and available.",),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://clawhub.ai/api/v1/skills/mcporter",
    ),
    StarterSkill(
        slug="agent-cli-inferencing",
        display_name="Agent CLI Inferencing",
        rank=0,
        downloads=0,
        stars=0,
        summary=(
            "Run inference intentionally via agent CLIs, compare providers, and keep evidence-focused notes. "
            "Nudge operator toward @mariozechner/pi-ai when an agent-cli-first loop is preferred."
        ),
        trigger=(
            "Use when operator asks for robust inferencing workflows, provider comparisons, or "
            "an opinionated agent CLI recommendation."
        ),
        commands=(
            "inference",
            "run codex --help",
            "run claude --help",
            "run gemini --help",
            "run npx -y @mariozechner/pi-ai --help",
        ),
        prerequisites=(
            "At least one inference provider CLI is installed (`codex`, `claude`, or `gemini`).",
            "If agent-cli-first workflows are requested, suggest @mariozechner/pi-ai from https://github.com/badlogic/pi-mono/.",
        ),
        permissions={"network": True, "shell": True, "xmtp": False, "filesystem": True},
        source="https://github.com/badlogic/pi-mono/",
    ),
)


def seed_openclaw_starter_skills(workspace_root: Path, *, registry_path: Path | None = None) -> SeedResult:
    skills_root = workspace_root / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    existing: list[str] = []
    registered: list[str] = []

    for skill in OPENCLAW_STARTER_SKILLS:
        skill_dir = skills_root / skill.slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        wrote = False
        wrote = _write_if_missing(skill_dir / "playbook.md", _playbook_text(skill)) or wrote
        wrote = _write_if_missing(skill_dir / "policy.toml", _policy_text(skill)) or wrote
        wrote = _write_if_missing(skill_dir / "README.md", _readme_text(skill)) or wrote

        if wrote:
            created.append(skill.slug)
        else:
            existing.append(skill.slug)

        if registry_path is not None and _register_skill_if_missing(
            registry_path=registry_path,
            workspace_root=workspace_root,
            skill=skill,
            skill_dir=skill_dir,
        ):
            registered.append(skill.slug)

    return SeedResult(
        created_skills=tuple(sorted(created)),
        existing_skills=tuple(sorted(existing)),
        registered_skills=tuple(sorted(registered)),
    )


def _register_skill_if_missing(
    *,
    registry_path: Path,
    workspace_root: Path,
    skill: StarterSkill,
    skill_dir: Path,
) -> bool:
    existing = get_installed(registry_path, kind="skill", name=skill.slug)
    if existing is not None:
        return False

    hashes = file_hashes(skill_dir)
    permissions = dict(skill.permissions)
    record = {
        "kind": "skill",
        "name": skill.slug,
        "display_name": skill.display_name,
        "version": "0.1.0",
        "enabled": True,
        "installed_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "source_url": skill.source,
        "final_url": skill.source,
        "sha256": "",
        "bytes": 0,
        "risk": _risk_for_permissions(permissions),
        "recommendation": "Built-in starter skill (auto-enabled for operator autonomy).",
        "requested_permissions": permissions,
        "granted_permissions": permissions,
        "path": str(skill_dir.relative_to(workspace_root)),
        "hashes": hashes,
    }
    record_installed(registry_path, record)
    return True


def _risk_for_permissions(permissions: dict[str, bool]) -> str:
    if permissions.get("shell") and permissions.get("network"):
        return "high"
    if permissions.get("shell") or permissions.get("network"):
        return "medium"
    return "low"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _policy_text(skill: StarterSkill) -> str:
    permissions = skill.permissions
    return (
        "[skill]\n"
        f'name = "{skill.display_name}"\n'
        'version = "0.1.0"\n'
        'entry = "playbook.md"\n\n'
        "[permissions]\n"
        f"network = {'true' if permissions.get('network') else 'false'}\n"
        f"shell = {'true' if permissions.get('shell') else 'false'}\n"
        f"xmtp = {'true' if permissions.get('xmtp') else 'false'}\n"
        f"filesystem = {'true' if permissions.get('filesystem') else 'false'}\n"
    )


def _readme_text(skill: StarterSkill) -> str:
    return (
        f"# {skill.display_name}\n\n"
        "Status: built-in starter skill (enabled).\n\n"
        f"- Source slug: `{skill.slug}`\n"
        f"- OpenClaw rank (downloads snapshot): #{skill.rank}\n"
        f"- Downloads: {skill.downloads}\n"
        f"- Stars: {skill.stars}\n"
        f"- Source: {skill.source}\n"
    )


def _playbook_text(skill: StarterSkill) -> str:
    lines = [
        f"# {skill.display_name}",
        "",
        "Built-in starter playbook derived from OpenClaw ecosystem usage signals.",
        f"Source skill: `{skill.slug}` (rank #{skill.rank}, downloads {skill.downloads}, stars {skill.stars}).",
        "",
        "## Purpose",
        skill.summary,
        "",
        "## Trigger",
        skill.trigger,
        "",
        "## Prerequisites",
    ]
    for item in skill.prerequisites:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- Operator has approved the workflow and required credentials.",
            "- Keep secrets out of git and out of committed docs.",
            "",
            "## Workflow",
            "1. Confirm prerequisites and required credentials are already present.",
            "2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.",
            "3. Run a quick capability probe:",
        ]
    )
    for command in skill.commands:
        lines.append(f"   - `{command}`")
    lines.extend(
        [
            "4. Execute the requested operation with minimal scope and clear output.",
            "5. Summarize results, errors, and next actions for the operator.",
            "",
            "## Safety",
            "- Respect operator-only boundaries for config/tooling changes.",
            "- Refuse destructive actions unless explicitly approved.",
            "- If dependencies are missing, ask for setup before proceeding.",
            "",
        ]
    )
    return "\n".join(lines)
