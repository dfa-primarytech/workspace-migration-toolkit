#include "testing.h"

#include "fixtures.h"

using namespace pubir;
using namespace fixtures;

TEST(limits_element_cap_halts_collection_but_keeps_counting) {
  Limits limits;
  limits.maxElements = 3;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  for (int i = 0; i < 10; i++) collector.drawRectangle(box(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.elements.size(), std::size_t(3));
  CHECK(doc.truncated);
  CHECK_EQ(doc.truncationReason, std::string("limit-elements"));
  // A report that says "stopped at 3" is only useful next to the true
  // callback total, so counting continues past the halt.
  CHECK_EQ(doc.callbackCounts.at("drawRectangle"), 10LL);
}

TEST(limits_callback_cap_halts_collection) {
  Limits limits;
  limits.maxCallbacks = 5;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  for (int i = 0; i < 20; i++) collector.drawRectangle(box(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(doc.truncated);
  CHECK_EQ(doc.truncationReason, std::string("limit-callbacks"));
  CHECK_EQ(doc.callbackTotal, 24LL);
}

TEST(limits_page_cap_halts_collection) {
  Limits limits;
  limits.maxPages = 2;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  for (int i = 0; i < 5; i++) {
    collector.startPage(page(8.0, 6.0));
    collector.endPage();
  }
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.pages, 2LL);
  CHECK(doc.truncated);
  CHECK_EQ(doc.truncationReason, std::string("limit-pages"));
}

TEST(limits_asset_count_cap_refuses_further_payloads) {
  Limits limits;
  limits.maxAssets = 1;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x11), "image/png", 1, 1, 1, 1));
  collector.drawGraphicObject(graphicObject(tinyPng(0x22), "image/png", 2, 2, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK(hasDiagnostic(doc, "limit-asset-count"));
  // The second image is still an element, flagged rather than vanished.
  CHECK_EQ(doc.elements.size(), std::size_t(2));
  CHECK(hasWarning(doc.elements[1], "asset-not-extracted"));
  // A refused asset is not a truncated parse: the rest of the document
  // was still collected in full.
  CHECK(!doc.truncated);
}

TEST(limits_oversized_asset_is_refused_before_decoding) {
  Limits limits;
  limits.maxAssetBytes = 8;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x33), "image/png", 1, 1, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(0));
  CHECK(hasDiagnostic(doc, "limit-asset-size"));
  CHECK_EQ(std::string(compatibilityName(doc.elements[0].compatibility)), std::string("UNSUPPORTED"));
}

TEST(limits_text_cap_halts_collection) {
  Limits limits;
  limits.maxTextBytes = 16;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startTextObject(box(1, 1, 4, 2));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("Calibri", 12.0));
  for (int i = 0; i < 20; i++) {
    collector.insertText(librevenge::RVNGString("0123456789"));
  }
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(doc.truncated);
  CHECK_EQ(doc.truncationReason, std::string("limit-text"));
  CHECK_EQ(doc.callbackCounts.at("insertText"), 20LL);
}

TEST(limits_point_cap_keeps_the_element_and_drops_only_the_points) {
  Limits limits;
  limits.maxPointsPerShape = 2;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawPolygon(rectanglePolygon(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.elements.size(), std::size_t(1));
  CHECK(doc.elements[0].points.empty());
  CHECK(hasWarning(doc.elements[0], "limit-points"));
  CHECK(!doc.truncated);
}

TEST(limits_nesting_depth_halts_collection) {
  Limits limits;
  limits.maxElementDepth = 4;
  IrCollector collector(limits);
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  for (int i = 0; i < 30; i++) collector.openGroup(RVNGPropertyList());
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(doc.truncated);
  CHECK_EQ(doc.truncationReason, std::string("limit-depth"));
}

TEST(limits_malformed_sequences_never_crash_the_collector) {
  // Callbacks in an order libmspub would not produce: everything closed
  // that was never opened, content before any page, a document that never
  // ends. The collector must survive and say what it saw.
  IrCollector collector;
  collector.closeSpan();
  collector.closeParagraph();
  collector.closeTableCell();
  collector.closeTableRow();
  collector.endTableObject();
  collector.endTextObject();
  collector.endLayer();
  collector.closeGroup();
  collector.endPage();
  collector.endMasterPage();
  collector.insertText(librevenge::RVNGString("stray"));
  collector.insertSpace();
  collector.closeOrderedListLevel();
  collector.closeUnorderedListLevel();
  collector.startTextObject(box(0, 0, 1, 1));
  const Document &doc = collector.finish();

  CHECK(doc.callbackTotal > 0);
  CHECK(hasDiagnostic(doc, "unbalanced-close"));
  // The stray text still reached an implicit page and an implicit frame
  // rather than being discarded.
  CHECK(doc.pages.size() >= std::size_t(1));
  CHECK(hasDiagnostic(doc, "page-not-closed"));
}

TEST(limits_finish_is_idempotent) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &first = collector.finish();
  const long long elements = first.counts.elements;
  const Document &second = collector.finish();
  CHECK_EQ(second.counts.elements, elements);
}

TEST(limits_unsupported_callbacks_still_reach_the_report) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.defineParagraphStyle(RVNGPropertyList());
  collector.defineCharacterStyle(RVNGPropertyList());
  RVNGPropertyList font;
  font.insert("librevenge:name", "SassoonPrimaryInfant");
  font.insert("librevenge:mime-type", "application/x-font-ttf");
  collector.defineEmbeddedFont(font);
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(hasDiagnostic(doc, "paragraph-style-defined"));
  CHECK(hasDiagnostic(doc, "character-style-defined"));
  CHECK_EQ(doc.fonts.size(), std::size_t(1));
  CHECK(doc.fonts[0].embedded);
  CHECK_EQ(doc.fonts[0].family, std::string("SassoonPrimaryInfant"));
  bool recorded = false;
  for (const Note &note : doc.limitations) {
    if (note.code == "embedded-fonts-not-extracted") recorded = true;
  }
  CHECK(recorded);
}
