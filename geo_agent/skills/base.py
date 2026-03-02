from abc import ABC, abstractmethod

from geo_agent.models.context import PipelineContext


class Skill(ABC):
    """Base class for all pipeline skills.

    Skills are stateless processors. Each skill reads from and writes to
    a shared PipelineContext, providing type safety and IDE autocompletion.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable skill name for logging."""
        ...

    @abstractmethod
    def execute(self, context: PipelineContext) -> PipelineContext:
        """Run this skill's logic.

        Args:
            context: Typed pipeline context carrying data through the pipeline.

        Returns:
            The same context, enriched with this skill's outputs.

        Raises:
            SkillError: If the skill fails in a recoverable way.
        """
        ...


class SkillError(Exception):
    """Raised when a skill encounters a recoverable error."""
    pass
