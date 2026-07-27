from code_review.app.master_review_agent import MasterReviewAgent
from code_review.app.worker_review_agent import WorkerReviewAgent
from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.call_chain_resolver import CallChainResolver
from code_review.domain.context_planner import ContextPlanner
from code_review.domain.diff_summary_builder import DiffSummaryBuilder
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.java_method_diff_slicer import JavaMethodDiffSlicer
from code_review.domain.models import ReviewRequest, ReviewResult, ReviewWorkspace
from code_review.domain.prompt_builder import PromptBuilder
from code_review.domain.risk_scorer import RiskScorer
from code_review.domain.slicing_decision_policy import SlicingDecisionPolicy
from code_review.infrastructure.git.diff_slicer_tool import DiffSlicerTool
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.git.local_workspace_resolver import LocalWorkspaceResolver
from code_review.infrastructure.llm.base import LlmClient
from code_review.infrastructure.profile_loader import ReviewProfileLoader
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter


class ReviewPipeline:
    """编排一次代码评审任务。

    这一层对应 Java 版 main 方法里的主流程，但不直接关心 git、HTTP、文件写入的细节。
    """

    def __init__(
        self,
        diff_provider: GitDiffProvider,
        prompt_builder: PromptBuilder,
        llm_client: LlmClient,
        report_writer: MarkdownReportWriter,
    ) -> None:
        self._diff_provider = diff_provider
        self._prompt_builder = prompt_builder
        self._llm_client = llm_client
        self._report_writer = report_writer
        self._section_parser = FileDiffSectionParser()
        self._risk_classifier = JavaBackendRiskClassifier()
        self._summary_builder = DiffSummaryBuilder(self._section_parser, self._risk_classifier)
        self._workspace_resolver = LocalWorkspaceResolver(diff_provider, self._section_parser, self._risk_classifier)
        self._profile_loader = ReviewProfileLoader()
        self._risk_scorer = RiskScorer(self._section_parser)
        self._context_planner = ContextPlanner()
        self._call_chain_resolver = CallChainResolver()
        self._master_agent = MasterReviewAgent(
            diff_provider=diff_provider,
            summary_builder=self._summary_builder,
            decision_policy=SlicingDecisionPolicy(),
            diff_slicer_tool=DiffSlicerTool(self._section_parser, self._risk_classifier, JavaMethodDiffSlicer()),
            worker_agent=WorkerReviewAgent(prompt_builder, llm_client),
        )

    def run(self, request: ReviewRequest) -> ReviewResult:
        workspace = self._workspace_resolver.resolve(request)
        return self.run_workspace(request, workspace)

    def run_workspace(self, request: ReviewRequest, workspace: ReviewWorkspace) -> ReviewResult:
        profile = self._profile_loader.load(workspace.worktree_path, workspace.repo_tree)
        initial_summary = self._summary_builder.build_from_changed_files(workspace.diff_text, workspace.changed_files)
        scored_summary = self._risk_scorer.score(workspace.diff_text, initial_summary, profile)
        planned_summary, contexts_by_path, context_strategy = self._context_planner.plan(workspace, scored_summary)
        contexts_by_path = self._call_chain_resolver.enrich(workspace, contexts_by_path)
        diff_text, report = self._master_agent.run_prepared(
            request=request,
            diff_text=workspace.diff_text,
            diff_summary=planned_summary,
            profile=profile,
            contexts_by_path=contexts_by_path,
            context_strategy=context_strategy,
        )
        review_content = self._report_writer.render(report)
        report_path = self._report_writer.write(review_content)
        comment_content = self._report_writer.render_comment(report, report_path)

        return ReviewResult(
            diff_text=diff_text,
            prompt="",
            review_content=review_content,
            report_path=report_path,
            slicing_decision=report.slicing_decision,
            shard_count=len(report.shard_results),
            shard_review_results=report.shard_results,
            comment_content=comment_content,
            report=report,
        )
