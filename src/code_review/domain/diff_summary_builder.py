from typing import List

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ChangedFile, DiffSummary


class DiffSummaryBuilder:
    def __init__(
        self,
        section_parser: FileDiffSectionParser,
        risk_classifier: JavaBackendRiskClassifier,
    ) -> None:
        self._section_parser = section_parser
        self._risk_classifier = risk_classifier

    def build(self, diff_text: str) -> DiffSummary:
        changed_files: List[ChangedFile] = []
        for section in self._section_parser.parse(diff_text):
            role, is_high_risk, risk_tags = self._risk_classifier.classify(section.display_path)
            changed_files.append(
                ChangedFile(
                    old_path=section.old_path,
                    new_path=section.new_path,
                    role=role,
                    is_high_risk=is_high_risk,
                    risk_tags=risk_tags,
                )
            )

        return DiffSummary(
            char_count=len(diff_text),
            file_count=len(changed_files),
            high_risk_file_count=sum(1 for file in changed_files if file.is_high_risk),
            changed_files=changed_files,
        )

    def build_from_changed_files(self, diff_text: str, changed_files: List[ChangedFile]) -> DiffSummary:
        return DiffSummary(
            char_count=len(diff_text),
            file_count=len(changed_files),
            high_risk_file_count=sum(1 for file in changed_files if file.is_high_risk),
            changed_files=changed_files,
        )
