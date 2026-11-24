"""What has changed in the converter, in words staff can check their problem against.

Shown on the public /whats-new page. Newest first. Write each entry for the
person who had the problem, not for a developer: say what they would have seen
and what is different now. No client names, ticket numbers or file names.

Every change that alters what someone sees or what files can be converted adds
an entry here in the same pull request (see AGENTS.md).
"""

from __future__ import annotations

from datetime import date
from html import escape

NEW, FIXED, BETTER = "New", "Fixed", "Better"
KINDS = (NEW, FIXED, BETTER)

# (day, [(kind, applies to, what changed)]) -- newest day first.
RELEASES: list[tuple[date, list[tuple[str, str, str]]]] = [
    (
        date(2026, 11, 23),
        [
            (
                FIXED,
                "Publisher",
                "Badges and labels with a logo: names and dates are no longer hidden "
                "behind the logo. Text that had been pushed clear of a picture with "
                "spaces now stays clear of it in Google Slides.",
            ),
            (
                NEW,
                "Rich Text (.rtf)",
                "Rich Text Format files can now be converted to Google Docs.",
            ),
            (
                FIXED,
                "Word",
                "Documents with equations that were written in Google Docs failed to "
                "convert at all. They now convert, with their equations.",
            ),
            (
                NEW,
                "Word (.doc)",
                "Older Word files (.doc) can now be converted to Google Docs. Google "
                "converts them as they are, so check text boxes, pictures and tables.",
            ),
            (
                NEW,
                "Word, PowerPoint, Excel",
                "Password-protected files are now accepted. The page asks for the "
                "password, uses it once to open the file and never keeps it.",
            ),
            (
                FIXED,
                "Publisher",
                "Numbered lists now count 1, 2, 3 instead of showing 1 on every line.",
            ),
            (
                FIXED,
                "Publisher",
                "Big heading text (WordArt) now fits on one line and no longer runs over "
                "the box beside it.",
            ),
            (
                FIXED,
                "Publisher",
                "Text is kept clear of pictures instead of printing over them, and a "
                "heading that started above the top of the page is brought back onto it.",
            ),
            (
                FIXED,
                "Word",
                "Flowcharts keep their boxes in reading order and side by side, with "
                "the arrows between them instead of floating over them.",
            ),
        ],
    ),
    (
        date(2026, 10, 21),
        [
            (
                NEW,
                "PowerPoint",
                "Slides with animations are played and saved as a short video beside the "
                "converted deck, and placed on the slide. Nobody needs PowerPoint to "
                "record anything.",
            ),
            (
                NEW,
                "PowerPoint",
                "Videos and sounds that were in the deck are put back after conversion "
                "instead of being lost.",
            ),
        ],
    ),
    (
        date(2026, 10, 6),
        [
            (
                FIXED,
                "Publisher",
                "Clipart in older Windows picture formats (WMF) is now drawn instead of "
                "leaving a gap in booklets.",
            ),
            (
                FIXED,
                "Publisher",
                "Forms made from one page-sized text box keep their width, order, "
                "outline and footer panel.",
            ),
            (
                FIXED,
                "Publisher",
                "Empty table cells are no longer a different text size from the rest "
                "of their table.",
            ),
        ],
    ),
    (
        date(2026, 10, 1),
        [
            (
                NEW,
                "Excel",
                "Workbooks with macros can be converted. Recorded macros become Google "
                "Apps Script and the workbook's buttons are linked to them.",
            ),
            (
                BETTER,
                "Excel",
                "Converted Sheets use the UK locale and your own time zone.",
            ),
            (
                BETTER,
                "Word",
                "The report gives the document's real page count and says where to look "
                "if something moved.",
            ),
            (
                BETTER,
                "Publisher",
                "A font the converter does not have is said to be shown in Arial rather "
                'than "replaced".',
            ),
        ],
    ),
]


def render() -> str:
    """The page, as HTML. Every piece of text is escaped."""
    sections = []
    for day, changes in RELEASES:
        rows = "".join(
            f'<li><span class="kind {kind.lower()}">{escape(kind)}</span> '
            f"<strong>{escape(applies)}</strong> &ndash; {escape(text)}</li>"
            for kind, applies, text in changes
        )
        label = f"{day.day} {day.strftime('%B %Y')}"
        sections.append(
            f'<h2><time datetime="{day.isoformat()}">{escape(label)}</time></h2><ul class="notes">{rows}</ul>'
        )
    return (
        '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>What&#8217;s new &ndash; Workspace Migration Toolkit</title>"
        '<link rel="stylesheet" href="/static/brand.css">'
        '<link rel="stylesheet" href="/static/style.css"></head>\n'
        '<body><main class="policy">'
        '<img id="brand-logo" src="/static/primarytech-logo.svg" alt="PrimaryTech">'
        '<p class="eyebrow">Workspace Migration Toolkit</p><h1>What&#8217;s new</h1>'
        "<p>What we have added and fixed, newest first. If a file gave you trouble "
        "before, find its type here and try it again once it is listed. Still not "
        "right? Tell your school&#8217;s IT support, who can pass it on.</p>"
        + "".join(sections)
        + '<p><a href="/">Back to the converter</a></p></main></body></html>'
    )
