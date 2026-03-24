"""Output parsing: inline comment extraction, severity capping."""

import re

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def cap_by_severity(body: str, max_comments: int) -> str:
    """If the review has more findings than max_comments, keep the highest severity."""
    if max_comments <= 0:
        return body

    finding_pattern = re.compile(r'^(###\s+\[(?:CRITICAL|HIGH|MEDIUM|LOW)\].*?)(?=\n###\s+\[|\Z)',
                                 re.MULTILINE | re.DOTALL)
    findings = finding_pattern.findall(body)

    if len(findings) <= max_comments:
        return body

    scored = []
    for finding in findings:
        sev_match = re.match(r'###\s+\[(CRITICAL|HIGH|MEDIUM|LOW)\]', finding)
        sev = _SEVERITY_ORDER.get(sev_match.group(1), 99) if sev_match else 99
        scored.append((sev, finding))

    scored.sort(key=lambda x: x[0])
    kept = scored[:max_comments]
    dropped = len(scored) - max_comments

    first_finding_pos = body.find(findings[0]) if findings else len(body)
    preamble = body[:first_finding_pos]
    result = preamble + "\n\n".join(f for _, f in kept)
    if dropped > 0:
        result += f"\n\n*(Dropped {dropped} lower-severity finding(s) due to comment cap)*"

    return result


def parse_inline_comments(body: str, diff: str) -> list[dict]:
    """Extract inline comments from review output using ### [file:line] pattern.

    Returns list of dicts with 'path', 'line', 'body' for each finding.
    Only returns comments where the file:line appears in the PR diff.
    """
    diff_lines: set[tuple[str, int]] = set()
    current_file = None
    current_line = 0
    for diff_line in diff.splitlines():
        if diff_line.startswith("+++ b/"):
            current_file = diff_line[6:]
        elif diff_line.startswith("@@ "):
            match = re.search(r'\+(\d+)', diff_line)
            if match:
                current_line = int(match.group(1))
        elif current_file:
            if diff_line.startswith("+") or diff_line.startswith(" "):
                diff_lines.add((current_file, current_line))
                current_line += 1
            elif diff_line.startswith("-"):
                pass

    pattern = re.compile(r'^###\s+(?:\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]\s+)?\[([^:\]]+):(\d+)\]', re.MULTILINE)
    findings = list(pattern.finditer(body))

    if not findings:
        return []

    comments = []
    for i, match in enumerate(findings):
        file_path = match.group(1)
        line_num = int(match.group(2))

        start = match.end()
        end = findings[i + 1].start() if i + 1 < len(findings) else len(body)
        comment_body = body[start:end].strip()

        if (file_path, line_num) in diff_lines:
            comments.append({"path": file_path, "line": line_num, "body": comment_body})
        else:
            posted = False
            for offset in range(1, 4):
                for candidate in (line_num + offset, line_num - offset):
                    if (file_path, candidate) in diff_lines:
                        comments.append({"path": file_path, "line": candidate, "body": comment_body})
                        posted = True
                        break
                if posted:
                    break

    return comments
