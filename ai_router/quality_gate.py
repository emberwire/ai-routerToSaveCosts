import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class QualityFloor:
    """The minimum effort_level and whether a heavy (non-light) model is
    required for a prompt, independent of what any classifier returned.

    Ratified 2026-08-25 (SPEC-ai-engineering.md Sec.0): quality is always
    priority, then cost. A floor only ever raises a classification result;
    nothing in this module is permitted to lower one.
    """
    min_effort: int
    require_heavy_model: bool
    reason: str


class QualityGate:
    """Fixes A13 (SPEC-ai-engineering.md): the fast path matched a
    verb-and-noun prefix and routed to the cheapest model regardless of what
    the rest of the prompt named -

        "fix syntax across the entire auth module"
        "remove unused code from the crypto signing path"
        "correct spelling in the PPM offering document"
        "git commit the migration that drops the users table"

    all matched a trivial-edit pattern and were dispatched at effort 1 on
    the cheapest model. This cannot be fixed by improving classification,
    because the fast path exists specifically to skip it.

    Every classification path - fast path, Gemini, heuristic fallback -
    clamps through this gate before returning a result. Two independent
    checks, either one forces the ceiling:

    1. `sensitivity_override` - breadth, destructive, sensitive-subsystem or
       compliance signals in the prompt text, regardless of what intent it
       turns out to have. Checked *before* classification runs, so it can
       also gate whether the fast path is allowed to fire at all.
    2. A per-intent floor, applied once intent is known.
    """

    # Wide blast radius named explicitly. "fix syntax across the entire auth
    # module" is not the same request as "fix typo in auth.py". Includes the
    # hyphen/space-flexible -wide family and "each"/"globally", found missing
    # 2026-08-25 by adversarial verification: "fix typo system-wide" and
    # "fix spelling globally" reproduced A13 verbatim through the original
    # closed list. A closed word list is always going to have edges; this is
    # not a claim of completeness, only of "wider than the last gap found".
    _BREADTH = re.compile(
        r"(?i)\b(all|every|everywhere|across|entire|throughout|whole|codebase|each|global(ly)?)\b"
        r"|\b(system|repo|repository|org|organization|company)[-\s]?wide\b"
    )

    # Verbs that destroy or overwrite state. Rare enough in ordinary
    # single-file work that they escalate on their own, independent of
    # whatever else the prompt says. Inflections are enumerated explicitly
    # rather than matched with \w* - the first version matched "dropdown"
    # as a hit on "drop", found by the same verification pass.
    _DESTRUCTIVE = re.compile(
        r"(?i)\b(drop(s|ped|ping)?|delete[sd]?|deleting"
        r"|truncat(e|es|ed|ing)|purg(e|es|ed|ing)|overwrit(e|es|ing|ten)"
        r"|wipe[sd]?|wiping|eras(e|es|ed|ing)|nuk(e|es|ed|ing))\b"
        r"|force[- ]push|reset\s+--hard|\brm\s+-rf\b"
    )

    # A sensitive subsystem noun is only a signal when paired with a
    # structural/scope noun nearby - "auth.py" stays cheap, "auth module"
    # and "the crypto signing path" do not. Matching the noun alone would
    # disqualify ordinary single-file work like "fix typo in auth.py".
    # "billing" added 2026-08-25 - financially sensitive, missing from the
    # first pass.
    _DOMAIN = r"auth|crypto|signing|payment|billing|secret|credential|migration|production|prod"
    _SCOPE = r"module|service|system|pipeline|path|layer|flow|subsystem|infrastructure|database|table|cache|environment"
    _DOMAIN_PLUS_SCOPE = re.compile(
        rf"(?i)\b({_DOMAIN})\b.{{0,25}}\b({_SCOPE})\b|\b({_SCOPE})\b.{{0,25}}\b({_DOMAIN})\b"
    )

    # Firm-specific compliance vocabulary. Rare and high-stakes enough to
    # escalate standalone, unlike the generic dev nouns above.
    _COMPLIANCE = re.compile(
        r"(?i)\b(ppm|ddq|cim|ein|reg\s*d|blue\s*sky|cap\s*table|offering|counsel|investor)\b"
        r"|lp\s+agreement"
    )

    # A genuine fast-path task is short. Past this, "fix typo" at the start
    # of the sentence is no longer evidence the rest of it is trivial too.
    MAX_FAST_PATH_WORDS = 10

    # Applied once intent is known. EXECUTE_ONLY has no floor beyond what
    # the fast path or heuristic already computed - a genuinely trivial
    # match should stay cheap. These never lower an existing value, only
    # raise one that came in below them.
    _INTENT_FLOOR = {
        "PREP_AND_EXECUTE": 3,
        "RESEARCH_ONLY": 2,
        "EXECUTE_ONLY": 1,
    }

    @classmethod
    def sensitivity_override(cls, prompt: str) -> Optional[QualityFloor]:
        """Intent-independent. If any of these trip, nothing about this
        prompt may route at the cheapest tier, no matter what intent or
        engine classification eventually settles on."""
        if cls._BREADTH.search(prompt):
            return QualityFloor(5, True, "prompt names broad scope (all/every/across/entire/...)")
        if cls._DESTRUCTIVE.search(prompt):
            return QualityFloor(5, True, "prompt names a destructive or overwriting operation")
        if cls._DOMAIN_PLUS_SCOPE.search(prompt):
            return QualityFloor(5, True, "prompt names a sensitive subsystem, not a single file")
        if cls._COMPLIANCE.search(prompt):
            return QualityFloor(5, True, "prompt names compliance-sensitive material")
        return None

    @classmethod
    def fast_path_eligible(cls, prompt: str) -> bool:
        """Gates the fast path itself, before any pattern match is even
        attempted. A regex match on the opening words was the whole bug -
        it is not sufficient on its own any more."""
        if len(prompt.split()) > cls.MAX_FAST_PATH_WORDS:
            return False
        return cls.sensitivity_override(prompt) is None

    @classmethod
    def floor_for(cls, prompt: str, intent: str) -> QualityFloor:
        """The floor a completed classification must clamp up to. The
        sensitivity override always wins over the per-intent floor - it is
        never softened by what the classifier decided the intent was."""
        override = cls.sensitivity_override(prompt)
        if override:
            return override
        return QualityFloor(cls._INTENT_FLOOR.get(intent, 1), False, f"{intent} intent floor")

    @staticmethod
    def light_and_heavy_model(engine: str, config) -> Tuple[str, str]:
        """The cheap and adequate model for an engine, so `apply` can swap
        one for the other when the floor requires it. Codex has no distinct
        light tier in this codebase today, so both resolve to the same
        model and the swap is a no-op."""
        if engine == "claude":
            return "claude-haiku-4-5-20251001", config.claude_model
        if engine == "gemini":
            return config.gemini_model, config.gemini_exec_model
        return config.codex_model, config.codex_model

    @classmethod
    def apply(
        cls,
        prompt: str,
        intent: str,
        effort_level: int,
        suggested_model: str,
        engine: str,
        config,
    ) -> Tuple[int, str, Optional[str]]:
        """Clamp a completed classification up to the floor. Never lowers
        anything the classifier already returned - only raises effort or
        swaps a light model for the engine's heavy one when the floor
        requires it and the classifier under-shot.

        Returns (effort_level, suggested_model, reason) - reason is None
        when nothing changed, so callers can fold it into their own
        reasoning string only when it's actually relevant.
        """
        floor = cls.floor_for(prompt, intent)
        light_model, heavy_model = cls.light_and_heavy_model(engine, config)

        new_effort = max(effort_level, floor.min_effort)
        new_model = suggested_model
        if floor.require_heavy_model and suggested_model == light_model:
            new_model = heavy_model

        changed = (new_effort != effort_level) or (new_model != suggested_model)
        return new_effort, new_model, (floor.reason if changed else None)
