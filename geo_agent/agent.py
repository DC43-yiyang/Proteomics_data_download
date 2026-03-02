import logging

from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)


class Agent:
    """Orchestrates a pipeline of Skills.

    The agent does not contain business logic. It:
    1. Maintains an ordered list of skills
    2. Runs them sequentially, passing a shared PipelineContext
    3. Handles SkillError (log and continue) vs unexpected exceptions (abort)
    """

    def __init__(self):
        self._skills: list[Skill] = []

    def register(self, skill: Skill) -> "Agent":
        """Add a skill to the pipeline. Returns self for chaining."""
        self._skills.append(skill)
        logger.info(f"Registered skill: {skill.name}")
        return self

    def run(self, context: PipelineContext) -> PipelineContext:
        """Execute all skills in order."""
        for skill in self._skills:
            logger.info(f"--- Running skill: {skill.name} ---")
            try:
                context = skill.execute(context)
            except SkillError as e:
                logger.error(f"Skill '{skill.name}' failed: {e}")
                context.errors.append(f"{skill.name}: {e}")
            except Exception:
                logger.exception(f"Unexpected error in skill '{skill.name}'")
                raise

        return context
