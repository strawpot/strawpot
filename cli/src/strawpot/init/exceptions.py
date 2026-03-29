"""Exception hierarchy for strawpot init.

All 11 named exceptions from the design's error registry.
"""

from __future__ import annotations


class StrawpotInitError(Exception):
    """Base exception for strawpot init."""


class InvalidTemplateCondition(StrawpotInitError):
    """Malformed condition in YAML template."""


class UnknownConditionVariable(StrawpotInitError):
    """Template condition references answer key that doesn't exist."""


class YAMLParseError(StrawpotInitError):
    """Invalid YAML in archetype template."""


class DirectoryNotFound(StrawpotInitError):
    """User-specified component path doesn't exist."""


class ExistingCLAUDEMD(StrawpotInitError):
    """Component already has a CLAUDE.md."""


class BrokenInlineMetadata(StrawpotInitError):
    """User edits/deletes <!-- strawpot:meta --> block."""


class NoMatchingArchetype(StrawpotInitError):
    """'Other' selected, no archetype matches."""


class WritePermissionDenied(StrawpotInitError):
    """Can't write to component directory."""


class QuestionnaireAbort(StrawpotInitError):
    """User hits Ctrl+C mid-questionnaire."""


class CrossComponentRefMissing(StrawpotInitError):
    """Template references component that user didn't select."""


class LargeDirectoryScan(StrawpotInitError):
    """Auto-suggest scans repo with 200+ directories."""
