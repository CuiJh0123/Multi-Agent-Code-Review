from code_review.domain.call_chain_resolver import CallChainResolver
from code_review.domain.context_planner import ReviewDepth
from code_review.domain.models import FileReviewContext, ReviewWorkspace


def test_call_chain_resolver_adds_related_repository_context(tmp_path):
    service = tmp_path / "src/main/java/com/demo/order/OrderService.java"
    repository = tmp_path / "src/main/java/com/demo/order/OrderRepository.java"
    service.parent.mkdir(parents=True)
    service.write_text(
        "package com.demo.order;\n"
        "public class OrderService {\n"
        "  private OrderRepository orderRepository;\n"
        "  public void lockOrder() {}\n"
        "}\n",
        encoding="utf-8",
    )
    repository.write_text("package com.demo.order;\npublic class OrderRepository {}\n", encoding="utf-8")
    workspace = ReviewWorkspace(
        worktree_path=tmp_path,
        repo_tree=[
            "src/main/java/com/demo/order/OrderService.java",
            "src/main/java/com/demo/order/OrderRepository.java",
        ],
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_text="diff",
        changed_files=[],
    )
    contexts = {
        "src/main/java/com/demo/order/OrderService.java": FileReviewContext(
            file_path="src/main/java/com/demo/order/OrderService.java",
            depth=ReviewDepth.FULL_CONTEXT,
            reason="test",
            context_text=service.read_text(encoding="utf-8"),
        )
    }

    enriched = CallChainResolver().enrich(workspace, contexts)

    context = enriched["src/main/java/com/demo/order/OrderService.java"]
    assert any(path.endswith("OrderRepository.java") for path in context.related_files)
    assert "Related context" in context.context_text
