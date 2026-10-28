import re
from collections import Counter

from .models import Batch, Translation

# Avoid mistaking natural prose such as "100% of" or "50%off" for printf.
# Ambiguous space-flag/word-adjacent formats can use explicit protected_tokens.
PRINTF_TOKEN = r"%(?:\d+\$)?[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlLzjt]*[diuoxXfFeEgGaAcsp](?![A-Za-z])"

TOKEN = re.compile(
    r"\{\\[^{}\r\n]*\}|"
    r"\$\{[A-Za-z_][\w.:-]*\}|\{\{[A-Za-z_][\w.:-]*\}\}|"
    r"\{[A-Za-z_0-9][\w.:-]*\}|"
    + PRINTF_TOKEN + r"|%%|"
    r"</?[A-Za-z][^<>\r\n]*>|\\[CVNPI]\[\d+\]|\\[Nnrt]"
)
TAG = re.compile(r"</?[A-Za-z][^<>\r\n]*>|\{\\[^{}\r\n]*\}")
PRINTF = re.compile(r"%(?!\d+\$)" + PRINTF_TOKEN[1:])


def validate(batch: Batch, translations: list[Translation]) -> dict:
    issues = []

    def issue(segment_id, code, severity="error"):
        issues.append({"id": segment_id, "code": code, "severity": severity})

    source_ids = [segment.id for segment in batch.segments]
    target_ids = [segment.id for segment in translations]
    if len(set(target_ids)) != len(target_ids):
        issue(None, "duplicate_ids")
    for segment_id in set(source_ids) - set(target_ids):
        issue(segment_id, "missing_id")
    for segment_id in set(target_ids) - set(source_ids):
        issue(segment_id, "unexpected_id")
    targets = {segment.id: segment.text for segment in translations}
    for segment in batch.segments:
        if segment.id not in targets:
            continue
        translated = targets[segment.id]
        if segment.text.strip() and not translated.strip():
            issue(segment.id, "empty_translation")
        if Counter(TOKEN.findall(segment.text)) != Counter(TOKEN.findall(translated)):
            issue(segment.id, "protected_token_mismatch")
        if TAG.findall(segment.text) != TAG.findall(translated):
            issue(segment.id, "tag_order_mismatch")
        if PRINTF.findall(segment.text) != PRINTF.findall(translated):
            issue(segment.id, "printf_order_mismatch")
        if any(segment.text.count(token) != translated.count(token) for token in segment.protected_tokens):
            issue(segment.id, "explicit_token_mismatch")
        if batch.preserve_line_breaks and re.findall(r"\r\n|\r|\n", segment.text) != re.findall(r"\r\n|\r|\n", translated):
            issue(segment.id, "line_break_mismatch")
        for term in batch.glossary:
            if term.source in segment.text and term.target not in translated:
                issue(segment.id, "required_glossary_term_missing" if term.required else "preferred_glossary_term_missing", "error" if term.required else "warning")
        if translated == segment.text and re.search(r"[A-Za-z\u3040-\u30ff]", segment.text):
            issue(segment.id, "unchanged_source", "warning")
    return {"valid": not any(item["severity"] == "error" for item in issues), "issues": issues}
