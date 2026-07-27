from typing import Dict, List

from code_review.domain.diff_sections import FileDiffSection, FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.java_method_diff_slicer import JavaMethodDiffSlicer
from code_review.domain.models import ChangedFile, FileReviewContext, ReviewProfile, ReviewShard


class DiffSlicerTool:
    """Deterministic tool that slices git diff into review shards."""

    ROLE_PRIORITY: Dict[str, int] = {
        "data_access": 1,
        "service": 2,
        "async": 3,
        "api": 4,
        "config": 5,
        "db_script": 6,
        "test": 7,
        "other": 8,
    }

    def __init__(
        self,
        section_parser: FileDiffSectionParser,
        risk_classifier: JavaBackendRiskClassifier,
        method_slicer: JavaMethodDiffSlicer = None,
    ) -> None:
        self._section_parser = section_parser
        self._risk_classifier = risk_classifier
        self._method_slicer = method_slicer or JavaMethodDiffSlicer()

    def slice(
        self,
        diff_text: str,
        max_chars_per_shard: int,
        changed_files_by_path: Dict[str, ChangedFile] = None,
        contexts_by_path: Dict[str, FileReviewContext] = None,
        profile: ReviewProfile = None,
    ) -> List[ReviewShard]:
        changed_files_by_path = changed_files_by_path or {}
        contexts_by_path = contexts_by_path or {}
        sections = self._section_parser.parse(diff_text)
        classified = [(section, changed_files_by_path.get(section.display_path) or self._to_changed_file(section)) for section in sections]
        classified.sort(key=lambda item: (self._risk_priority(item[1]), self.ROLE_PRIORITY.get(item[1].role, 99), item[1].display_path))

        pending: List[ReviewShard] = []
        current_sections: List[FileDiffSection] = []
        current_files: List[ChangedFile] = []
        current_len = 0
        current_role = ""

        for section, changed_file in classified:
            if len(section.diff_text) > max_chars_per_shard:
                if current_sections:
                    pending.append(self._build_pending_shard(current_sections, current_files, contexts_by_path, profile))
                    current_sections = []
                    current_files = []
                    current_len = 0
                    current_role = ""
                pending.extend(self._split_oversized_section(section, changed_file, max_chars_per_shard, contexts_by_path, profile))
                continue

            would_exceed = current_sections and current_len + len(section.diff_text) > max_chars_per_shard
            role_changed = current_sections and current_role != changed_file.role
            if would_exceed or role_changed:
                pending.append(self._build_pending_shard(current_sections, current_files, contexts_by_path, profile))
                current_sections = []
                current_files = []
                current_len = 0
                current_role = ""

            current_sections.append(section)
            current_files.append(changed_file)
            current_len += len(section.diff_text)
            current_role = changed_file.role

        if current_sections:
            pending.append(self._build_pending_shard(current_sections, current_files, contexts_by_path, profile))

        return self._renumber(pending)

    def create_single_shard(
        self,
        diff_text: str,
        changed_files_by_path: Dict[str, ChangedFile] = None,
        contexts_by_path: Dict[str, FileReviewContext] = None,
        profile: ReviewProfile = None,
    ) -> ReviewShard:
        changed_files_by_path = changed_files_by_path or {}
        contexts_by_path = contexts_by_path or {}
        sections = self._section_parser.parse(diff_text)
        files = [changed_files_by_path.get(section.display_path) or self._to_changed_file(section) for section in sections]
        return self._build_shard(
            shard_id="shard-1",
            index=1,
            total=1,
            role=self._dominant_role(files),
            files=files,
            diff_text=diff_text,
            method_names=[],
            contexts_by_path=contexts_by_path,
            profile=profile,
        )

    def _to_changed_file(self, section: FileDiffSection) -> ChangedFile:
        role, is_high_risk, risk_tags = self._risk_classifier.classify(section.display_path)
        return ChangedFile(
            old_path=section.old_path,
            new_path=section.new_path,
            role=role,
            is_high_risk=is_high_risk,
            risk_tags=risk_tags,
        )

    def _build_pending_shard(
        self,
        sections: List[FileDiffSection],
        files: List[ChangedFile],
        contexts_by_path: Dict[str, FileReviewContext],
        profile: ReviewProfile = None,
    ) -> ReviewShard:
        return self._build_shard(
            shard_id="pending",
            index=0,
            total=0,
            role=self._dominant_role(files),
            files=files,
            diff_text="".join(section.diff_text for section in sections),
            method_names=[],
            contexts_by_path=contexts_by_path,
            profile=profile,
        )

    def _split_oversized_section(
        self,
        section: FileDiffSection,
        changed_file: ChangedFile,
        max_chars_per_shard: int,
        contexts_by_path: Dict[str, FileReviewContext],
        profile: ReviewProfile = None,
    ) -> List[ReviewShard]:
        method_shards = self._split_java_section_by_method(section, changed_file, max_chars_per_shard, contexts_by_path, profile)
        if method_shards:
            return method_shards

        lines = section.diff_text.splitlines(keepends=True)
        header: List[str] = []
        body_start = 0
        for index, line in enumerate(lines):
            if line.startswith("@@ "):
                body_start = index
                break
            header.append(line)
        else:
            body_start = min(len(lines), len(header))

        header_text = "".join(header)
        available = max(max_chars_per_shard - len(header_text), max_chars_per_shard // 2)
        body_lines = lines[body_start:]
        shards: List[ReviewShard] = []
        current: List[str] = []
        current_len = 0

        for line in body_lines:
            if current and current_len + len(line) > available:
                shards.append(
                    self._build_shard(
                        shard_id="pending",
                        index=0,
                        total=0,
                        role=changed_file.role,
                        files=[changed_file],
                        diff_text=header_text + "".join(current),
                        method_names=[],
                        contexts_by_path=contexts_by_path,
                        profile=profile,
                    )
                )
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line)

        if current or not shards:
            shards.append(
                self._build_shard(
                    shard_id="pending",
                    index=0,
                    total=0,
                    role=changed_file.role,
                    files=[changed_file],
                    diff_text=header_text + "".join(current),
                    method_names=[],
                    contexts_by_path=contexts_by_path,
                    profile=profile,
                )
            )

        return shards

    def _split_java_section_by_method(
        self,
        section: FileDiffSection,
        changed_file: ChangedFile,
        max_chars_per_shard: int,
        contexts_by_path: Dict[str, FileReviewContext],
        profile: ReviewProfile = None,
    ) -> List[ReviewShard]:
        method_sections = self._method_slicer.slice_by_method(section)
        if not method_sections:
            if section.display_path.endswith(".java"):
                return [
                    self._build_shard(
                        shard_id="pending",
                        index=0,
                        total=0,
                        role=changed_file.role,
                        files=[changed_file],
                        diff_text=section.diff_text,
                        method_names=[],
                        contexts_by_path=contexts_by_path,
                        profile=profile,
                    )
                ]
            return []

        shards: List[ReviewShard] = []
        current_texts: List[str] = []
        current_methods: List[str] = []
        current_len = 0

        for method_section in method_sections:
            if current_texts and current_len + len(method_section.diff_text) > max_chars_per_shard:
                shards.append(self._build_text_shard(current_texts, changed_file, current_methods, contexts_by_path, profile))
                current_texts = []
                current_methods = []
                current_len = 0

            if len(method_section.diff_text) > max_chars_per_shard:
                if current_texts:
                    shards.append(self._build_text_shard(current_texts, changed_file, current_methods, contexts_by_path, profile))
                    current_texts = []
                    current_methods = []
                    current_len = 0
                shards.append(self._build_text_shard([method_section.diff_text], changed_file, [method_section.method_name], contexts_by_path, profile))
                continue

            current_texts.append(method_section.diff_text)
            current_methods.append(method_section.method_name)
            current_len += len(method_section.diff_text)

        if current_texts:
            shards.append(self._build_text_shard(current_texts, changed_file, current_methods, contexts_by_path, profile))

        return shards

    def _build_text_shard(
        self,
        diff_texts: List[str],
        changed_file: ChangedFile,
        method_names: List[str],
        contexts_by_path: Dict[str, FileReviewContext],
        profile: ReviewProfile = None,
    ) -> ReviewShard:
        return self._build_shard(
            shard_id="pending",
            index=0,
            total=0,
            role=changed_file.role,
            files=[changed_file],
            diff_text="\n".join(diff_texts),
            method_names=method_names,
            contexts_by_path=contexts_by_path,
            profile=profile,
        )

    def _build_shard(
        self,
        shard_id: str,
        index: int,
        total: int,
        role: str,
        files: List[ChangedFile],
        diff_text: str,
        method_names: List[str],
        contexts_by_path: Dict[str, FileReviewContext],
        profile: ReviewProfile = None,
    ) -> ReviewShard:
        return ReviewShard(
            shard_id=shard_id,
            index=index,
            total=total,
            role=role,
            files=files,
            diff_text=diff_text,
            risk_tags=self._merge_risk_tags(files),
            method_names=method_names,
            risk_score=max((file.risk_score for file in files), default=0),
            risk_level=self._dominant_risk_level(files),
            risk_reasons=self._merge_risk_reasons(files),
            context_depth=self._dominant_context_depth(files),
            context_reason=self._merge_context_reasons(files),
            context_text=self._merge_context_text(files, contexts_by_path),
            profile_rules=(profile.rules if profile else []),
        )

    def _renumber(self, shards: List[ReviewShard]) -> List[ReviewShard]:
        total = len(shards)
        return [
            ReviewShard(
                shard_id=f"shard-{index}",
                index=index,
                total=total,
                role=shard.role,
                files=shard.files,
                diff_text=shard.diff_text,
                risk_tags=shard.risk_tags,
                method_names=shard.method_names,
                risk_score=shard.risk_score,
                risk_level=shard.risk_level,
                risk_reasons=shard.risk_reasons,
                context_depth=shard.context_depth,
                context_reason=shard.context_reason,
                context_text=shard.context_text,
                profile_rules=shard.profile_rules,
            )
            for index, shard in enumerate(shards, start=1)
        ]

    def _dominant_role(self, files: List[ChangedFile]) -> str:
        if not files:
            return "other"
        return sorted(files, key=lambda file: self.ROLE_PRIORITY.get(file.role, 99))[0].role

    def _merge_risk_tags(self, files: List[ChangedFile]) -> List[str]:
        tags = []
        for file in files:
            for tag in file.risk_tags:
                if tag not in tags:
                    tags.append(tag)
        return tags

    def _merge_risk_reasons(self, files: List[ChangedFile]) -> List[str]:
        return list(dict.fromkeys(reason for file in files for reason in file.risk_reasons))[:12]

    def _dominant_risk_level(self, files: List[ChangedFile]) -> str:
        rank = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
        return max((file.risk_level for file in files), key=lambda level: rank.get(level, 0), default="P3")

    def _dominant_context_depth(self, files: List[ChangedFile]) -> str:
        rank = {"full_context": 3, "diff_only": 2, "summary_only": 1}
        return max((file.context_depth for file in files), key=lambda depth: rank.get(depth, 0), default="diff_only")

    def _merge_context_reasons(self, files: List[ChangedFile]) -> str:
        reasons = [file.context_reason for file in files if file.context_reason]
        return "; ".join(dict.fromkeys(reasons))

    def _merge_context_text(self, files: List[ChangedFile], contexts_by_path: Dict[str, FileReviewContext]) -> str:
        chunks = []
        for file in files:
            context = contexts_by_path.get(file.display_path)
            if context and context.context_text:
                chunks.append(f"[Context for {file.display_path}]\n{context.context_text}")
        return "\n\n".join(chunks)

    def _risk_priority(self, file: ChangedFile) -> tuple:
        rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return (rank.get(file.risk_level, 3), -file.risk_score)
