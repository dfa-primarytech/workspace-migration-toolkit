#include "testing.h"

#include "fixtures.h"
#include "serialise.h"

using namespace pubir;
using namespace fixtures;

namespace {

// The shortest sequence libmspub emits for a one-page document.
void oneEmptyPage(IrCollector &collector) {
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(5.8268, 8.2677));
  collector.endPage();
  collector.endDocument();
}

} // namespace

TEST(collector_records_page_geometry_in_points) {
  IrCollector collector;
  oneEmptyPage(collector);
  const Document &doc = collector.finish();

  CHECK_EQ(doc.pages.size(), std::size_t(1));
  CHECK_EQ(doc.counts.pages, 1LL);
  CHECK(doc.pages[0].width.valid);
  CHECK_NEAR(doc.pages[0].width.points, 419.53, 0.5);
  CHECK_NEAR(doc.pages[0].height.points, 595.27, 0.5);
  CHECK_EQ(doc.pages[0].width.sourceUnit, std::string("in"));
  CHECK_EQ(doc.pages[0].id, std::string("page_0001"));
  CHECK_EQ(doc.pages[0].index, 0);
}

TEST(collector_ids_are_stable_and_sequential) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawRectangle(box(1, 1, 2, 2));
  collector.drawEllipse(box(2, 2, 1, 1));
  collector.startPage(page(8.0, 6.0));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.elements.size(), std::size_t(3));
  CHECK_EQ(doc.elements[0].id, std::string("el_000001"));
  CHECK_EQ(doc.elements[1].id, std::string("el_000002"));
  CHECK_EQ(doc.elements[2].id, std::string("el_000003"));
  CHECK_EQ(doc.pages[1].id, std::string("page_0002"));
  // z-order restarts per page: it is a paint order within a page, not a
  // document-wide rank.
  CHECK_EQ(doc.elements[0].zIndex, 0);
  CHECK_EQ(doc.elements[1].zIndex, 1);
  CHECK_EQ(doc.elements[2].zIndex, 0);
  CHECK_EQ(doc.elements[2].pageIndex, 1);
}

TEST(collector_preserves_callback_order_and_counts) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.drawEllipse(box(0, 0, 1, 1));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.callbackCounts.at("drawRectangle"), 2LL);
  CHECK_EQ(doc.callbackCounts.at("drawEllipse"), 1LL);
  CHECK_EQ(doc.callbackTotal, 7LL);
  // Event indices are strictly increasing, which is what makes a
  // diagnostic locatable in the original stream.
  CHECK(doc.elements[0].eventIndex < doc.elements[1].eventIndex);
  CHECK(doc.elements[1].eventIndex < doc.elements[2].eventIndex);
  CHECK(doc.pages[0].startEventIndex < doc.elements[0].eventIndex);
  CHECK(doc.pages[0].endEventIndex > doc.elements[2].eventIndex);
}

TEST(collector_distinguishes_wrappers_from_authored_groups) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startLayer(RVNGPropertyList());
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endLayer();
  collector.openGroup(RVNGPropertyList());
  collector.drawEllipse(box(0, 0, 1, 1));
  collector.closeGroup();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const auto wrappers = elementsOfType(doc, "wrapper");
  const auto groups = elementsOfType(doc, "group");
  CHECK_EQ(wrappers.size(), std::size_t(1));
  CHECK_EQ(groups.size(), std::size_t(1));
  CHECK_EQ(wrappers[0]->wrapperKind, std::string("layer"));
  // The point of the distinction: a layer is not evidence that the author
  // grouped anything, so it must not be classified as a group.
  CHECK_EQ(std::string(compatibilityName(wrappers[0]->compatibility)), std::string("IGNORED"));
  CHECK(hasWarning(*wrappers[0], "wrapper-not-a-group"));
  CHECK_EQ(std::string(compatibilityName(groups[0]->compatibility)), std::string("NATIVE"));
}

TEST(collector_records_parent_references) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.openGroup(RVNGPropertyList());
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.closeGroup();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const auto groups = elementsOfType(doc, "group");
  const auto shapes = elementsOfType(doc, "shape");
  CHECK_EQ(shapes[0]->parentId, groups[0]->id);
  CHECK(groups[0]->parentId.empty());
}

TEST(collector_keeps_content_that_arrives_outside_a_page) {
  // A truncated file can emit a draw call before any startPage. Dropping
  // it would lose real content and leave no trace that it existed.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.elements.size(), std::size_t(1));
  CHECK_EQ(doc.pages.size(), std::size_t(1));
  CHECK(doc.pages[0].implicit);
  CHECK(hasDiagnostic(doc, "implicit-page"));
}

TEST(collector_reports_unbalanced_closes) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.endLayer();
  collector.closeGroup();
  collector.endPage();
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(hasDiagnostic(doc, "unbalanced-close"));
  // The callbacks are still counted even though they produced nothing.
  CHECK_EQ(doc.callbackCounts.at("endPage"), 2LL);
}

TEST(collector_reports_mismatched_container_nesting) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.startLayer(RVNGPropertyList());
  collector.closeGroup(); // closes a layer with the wrong callback
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(hasDiagnostic(doc, "unbalanced-nesting"));
}

TEST(collector_records_master_pages_separately) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startMasterPage(page(8.0, 6.0));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.endMasterPage();
  collector.startPage(page(8.0, 6.0));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.pages, 1LL);
  CHECK_EQ(doc.counts.masterPages, 1LL);
  CHECK_EQ(doc.pages[0].kind, std::string("master"));
  CHECK_EQ(doc.pages[0].id, std::string("master_0001"));
  CHECK_EQ(doc.pages[1].id, std::string("page_0001"));
}

TEST(collector_records_rotation_and_style_provenance) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.setStyle(solidFill("#00ff00"));
  RVNGPropertyList rotated = box(1, 1, 2, 2);
  rotated.insert("librevenge:rotate", 45.0, librevenge::RVNG_GENERIC);
  collector.drawRectangle(rotated);
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK(doc.elements[0].hasRotation);
  CHECK_NEAR(doc.elements[0].rotationDegrees, 45.0, 1e-9);
  bool sawFill = false;
  for (const SourceProperty &prop : doc.elements[0].styleProperties) {
    if (prop.key == "draw:fill-color" && prop.value == "#00ff00") sawFill = true;
  }
  CHECK(sawFill);
  CHECK(doc.elements[0].styleEventIndex >= 0);
}

TEST(collector_classifies_shape_kinds) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawRectangle(box(0, 0, 1, 1));
  collector.drawPolyline(box(0, 0, 1, 1));
  collector.drawConnector(box(0, 0, 1, 1));
  collector.drawPath(box(0, 0, 1, 1));
  collector.drawPolygon(trianglePolygon());
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.shapeElements, 2LL); // rectangle and triangle polygon
  CHECK_EQ(doc.counts.lineElements, 2LL);  // polyline and connector
  CHECK_EQ(doc.counts.pathElements, 1LL);
}

TEST(collector_output_is_deterministic_across_runs) {
  // Two identical callback sequences must serialise to identical bytes,
  // or nothing downstream can diff one conversion against another.
  auto build = []() {
    IrCollector collector;
    collector.startDocument(RVNGPropertyList());
    collector.startPage(page(5.8268, 8.2677));
    collector.setStyle(bitmapFill(tinyPng(0x11)));
    collector.drawPolygon(rectanglePolygon(1, 1, 2, 2));
    collector.startTextObject(box(0.5, 0.5, 4, 1));
    collector.openParagraph(RVNGPropertyList());
    collector.openSpan(span("Calibri", 12.0));
    collector.insertText(librevenge::RVNGString("Newsletter"));
    collector.closeSpan();
    collector.closeParagraph();
    collector.endTextObject();
    collector.endPage();
    collector.endDocument();
    return documentJson(collector.finish()).dump(2);
  };
  CHECK_EQ(build(), build());
}
