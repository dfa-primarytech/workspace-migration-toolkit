#include "testing.h"

#include "fixtures.h"

using namespace pubir;
using namespace fixtures;

namespace {

const Element &firstText(const Document &doc) {
  static Element empty;
  const auto texts = elementsOfType(doc, "text");
  return texts.empty() ? empty : *texts[0];
}

} // namespace

TEST(text_paragraphs_and_runs_are_reconstructed) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  RVNGPropertyList centred;
  centred.insert("fo:text-align", "center");
  collector.openParagraph(centred);
  collector.openSpan(span("SassoonPrimaryInfant", 18.0, true));
  collector.insertText(librevenge::RVNGString("Welcome"));
  collector.closeSpan();
  collector.openSpan(span("Calibri", 12.0, false, true));
  collector.insertText(librevenge::RVNGString(" to our school"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Element &text = firstText(doc);
  CHECK_EQ(text.paragraphs.size(), std::size_t(1));
  CHECK_EQ(text.paragraphs[0].alignment, std::string("center"));
  CHECK_EQ(text.paragraphs[0].runs.size(), std::size_t(2));

  const Run &first = text.paragraphs[0].runs[0];
  CHECK_EQ(first.text, std::string("Welcome"));
  CHECK_EQ(first.fontFamily, std::string("SassoonPrimaryInfant"));
  CHECK(first.hasFontSize);
  CHECK_NEAR(first.fontSizePoints, 18.0, 1e-9);
  CHECK(first.bold);
  CHECK(!first.italic);

  const Run &second = text.paragraphs[0].runs[1];
  CHECK(second.italic);
  CHECK(!second.bold);
  CHECK_EQ(second.fontFamily, std::string("Calibri"));
}

TEST(text_keeps_explicit_spaces_tabs_and_line_breaks_as_items) {
  // The convenience `text` string flattens these, but the distinction
  // between a typed space and an explicit one is real formatting and has
  // to survive in `items`.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("a"));
  collector.insertSpace();
  collector.insertTab();
  collector.insertLineBreak();
  collector.insertText(librevenge::RVNGString("b"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Run &run = firstText(doc).paragraphs[0].runs[0];
  CHECK_EQ(run.items.size(), std::size_t(5));
  CHECK_EQ(run.items[1].kind, std::string("space"));
  CHECK_EQ(run.items[2].kind, std::string("tab"));
  CHECK_EQ(run.items[3].kind, std::string("lineBreak"));
  CHECK_EQ(run.text, std::string("a \t\nb"));
  CHECK_EQ(doc.counts.textInsertions, 2LL);
}

// Not reachable from a .pub: libmspub 0.1.4 never emits this callback (see
// test_libmspub_shapes.cpp). Kept because the IR is source-independent.
TEST(text_fields_are_recorded_without_inventing_their_value) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("Page "));
  RVNGPropertyList field;
  field.insert("librevenge:field-type", "text:page-number");
  collector.insertField(field);
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Run &run = firstText(doc).paragraphs[0].runs[0];
  CHECK_EQ(run.items.size(), std::size_t(2));
  CHECK_EQ(run.items[1].kind, std::string("field"));
  // The field contributes nothing to the flattened text: what a page
  // number renders as depends on context the parser does not have.
  CHECK_EQ(run.text, std::string("Page "));
  bool sawType = false;
  for (const SourceProperty &prop : run.items[1].properties) {
    if (prop.key == "librevenge:field-type" && prop.value == "text:page-number") sawType = true;
  }
  CHECK(sawType);
}

TEST(text_records_colour_language_and_country) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  RVNGPropertyList style = span("Calibri", 11.0);
  style.insert("fo:color", "#1f3864");
  style.insert("fo:language", "en");
  style.insert("fo:country", "GB");
  style.insert("style:text-underline-type", "single");
  collector.openSpan(style);
  collector.insertText(librevenge::RVNGString("Term dates"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Run &run = firstText(doc).paragraphs[0].runs[0];
  CHECK_EQ(run.color, std::string("#1f3864"));
  CHECK_EQ(run.language, std::string("en"));
  CHECK_EQ(run.country, std::string("GB"));
  CHECK_EQ(run.underline, std::string("single"));
}

TEST(text_arriving_with_no_open_span_is_kept_and_flagged) {
  // Malformed, but the text is real. Losing it would be worse than
  // recording that the structure was odd.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.insertText(librevenge::RVNGString("orphan"));
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Element &text = firstText(doc);
  CHECK_EQ(text.paragraphs.size(), std::size_t(1));
  CHECK(text.paragraphs[0].implicit);
  CHECK(text.paragraphs[0].runs[0].implicit);
  CHECK_EQ(text.paragraphs[0].runs[0].text, std::string("orphan"));
  CHECK(hasDiagnostic(doc, "implicit-paragraph"));
  CHECK(hasDiagnostic(doc, "implicit-span"));
}

TEST(text_is_never_flattened_into_an_image) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  // A bitmap fill is in force when the text frame opens; the frame must
  // still come out as editable text, not as a picture of text.
  collector.setStyle(bitmapFill(tinyPng(0x22)));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("still editable"));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.textElements, 1LL);
  CHECK_EQ(firstText(doc).paragraphs[0].runs[0].text, std::string("still editable"));
  CHECK_EQ(std::string(compatibilityName(firstText(doc).compatibility)), std::string("NATIVE"));
}

TEST(text_empty_frames_are_kept_and_flagged) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.textElements, 1LL);
  CHECK(hasWarning(firstText(doc), "empty-text-frame"));
}

// Not reachable from a .pub: libmspub 0.1.4 never emits this callback (see
// test_libmspub_shapes.cpp). Kept because the IR is source-independent.
TEST(text_list_levels_are_recorded_on_paragraphs) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openUnorderedListLevel(RVNGPropertyList());
  collector.openListElement(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("item"));
  collector.closeSpan();
  collector.closeListElement();
  collector.closeUnorderedListLevel();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Paragraph &paragraph = firstText(doc).paragraphs[0];
  CHECK_EQ(paragraph.listKind, std::string("unordered"));
  CHECK_EQ(paragraph.listLevel, 1);
}

// Not reachable from a .pub: libmspub 0.1.4 never emits this callback (see
// test_libmspub_shapes.cpp). Kept because the IR is source-independent.
TEST(text_link_targets_attach_to_runs) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  RVNGPropertyList link;
  link.insert("xlink:href", "https://example.school/newsletter");
  collector.openLink(link);
  collector.openSpan(span("Calibri", 12.0));
  collector.insertText(librevenge::RVNGString("newsletter"));
  collector.closeSpan();
  collector.closeLink();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(firstText(doc).paragraphs[0].runs[0].linkHref,
           std::string("https://example.school/newsletter"));
}

TEST(text_font_inventory_counts_usage) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  collector.closeSpan();
  collector.openSpan(span("Calibri", 14.0));
  collector.closeSpan();
  collector.openSpan(span("SassoonPrimaryType", 20.0));
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.fonts.size(), std::size_t(2));
  CHECK_EQ(doc.fonts[0].family, std::string("Calibri"));
  CHECK_EQ(doc.fonts[0].usageCount, 2LL);
  CHECK_EQ(doc.fonts[1].family, std::string("SassoonPrimaryType"));
  CHECK_EQ(doc.counts.fonts, 2LL);
}
