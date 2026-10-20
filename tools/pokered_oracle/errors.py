class OracleError(RuntimeError):
    """An actionable oracle setup, execution, or comparison failure."""


class OraclePrerequisiteError(OracleError):
    """A required local tool or deterministic emulator precondition is missing."""
