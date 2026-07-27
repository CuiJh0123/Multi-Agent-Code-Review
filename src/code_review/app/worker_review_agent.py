from code_review.domain.models import ReviewShard, ShardReviewResult
from code_review.domain.prompt_builder import PromptBuilder
from code_review.domain.structured_finding_parser import StructuredFindingParser
from code_review.infrastructure.llm.base import LlmClient


class WorkerReviewAgent:
    """Review one shard through the LLM client."""

    def __init__(self, prompt_builder: PromptBuilder, llm_client: LlmClient) -> None:
        self._prompt_builder = prompt_builder
        self._llm_client = llm_client
        self._finding_parser = StructuredFindingParser()

    def review(self, shard: ReviewShard) -> ShardReviewResult:
        prompt = self._prompt_builder.build_for_shard(shard)
        review_content = self._llm_client.chat(prompt)
        summary, findings, warnings = self._finding_parser.parse(review_content, shard)
        return ShardReviewResult(
            shard=shard,
            review_content=review_content,
            success=True,
            structured_summary=summary,
            structured_findings=findings,
            parser_warnings=warnings,
        )
