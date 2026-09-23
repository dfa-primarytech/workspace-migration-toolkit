#include "testing.h"

#include "fixtures.h"

#include <cmath>

using namespace pubir;
using namespace fixtures;

// Callback sequences shaped like the ones libmspub 0.1.4 actually emits.
//
// Checked against libmspub-0.1.4's own source (MSPUBCollector.cpp, Fill.cpp),
// not against a document: it never calls openGroup, startMasterPage, the
// list callbacks, openLink or insertField; it reports rotation only on text
// frames and folds every other rotation and flip into the outline; it uses
// startLayer both for authored groups and for one shape painted in several
// passes; and it calls drawGraphicObject only for BorderArt tiles. The tests
// elsewhere that drive those other callbacks still matter, because the IR is
// source-independent, but they do not describe a Publisher file.

namespace {

// Rotates a rectangle's corners counter-clockwise on the page (y down) about
// its centre, keeping libmspub's corner order: top-left, top-right,
// bottom-right, bottom-left.
RVNGPropertyList rotatedRectangle(double x, double y, double width, double height,
                                  double degrees) {
  const double pi = 3.14159265358979323846;
  const double t = degrees * pi / 180.0;
  const double cx = x + width / 2.0, cy = y + height / 2.0;
  const double xs[4] = {x, x + width, x + width, x};
  const double ys[4] = {y, y, y + height, y + height};
  librevenge::RVNGPropertyListVector points;
  for (int i = 0; i < 4; i++) {
    const double dx = xs[i] - cx, dy = ys[i] - cy;
    RVNGPropertyList point;
    point.insert("svg:x", cx + dx * std::cos(t) + dy * std::sin(t), librevenge::RVNG_INCH);
    point.insert("svg:y", cy - dx * std::sin(t) + dy * std::cos(t), librevenge::RVNG_INCH);
    points.append(point);
  }
  RVNGPropertyList props;
  props.insert("svg:points", points);
  return props;
}

RVNGPropertyList polygonFrom(const double *xs, const double *ys, int count) {
  librevenge::RVNGPropertyListVector points;
  for (int i = 0; i < count; i++) {
    RVNGPropertyList point;
    point.insert("svg:x", xs[i], librevenge::RVNG_INCH);
    point.insert("svg:y", ys[i], librevenge::RVNG_INCH);
    points.append(point);
  }
  RVNGPropertyList props;
  props.insert("svg:points", points);
  return props;
}

void startOnePage(IrCollector &collector) {
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 11.0));
}

const Document &finishOnePage(IrCollector &collector) {
  collector.endPage();
  collector.endDocument();
  return collector.finish();
}

} // namespace

// --- layers: groups and multi-pass shapes ------------------------------------

TEST(libmspub_group_layer_of_separately_placed_shapes_is_a_probable_group) {
  // paintShape for a shape with children: startLayer({}), each child, endLayer.
  IrCollector collector;
  startOnePage(collector);
  collector.startLayer(RVNGPropertyList());
  collector.setStyle(solidFill("#ff0000"));
  collector.drawRectangle(box(0.5, 0.5, 1.0, 1.0));
  collector.setStyle(solidFill("#0000ff"));
  collector.drawEllipse(box(4.0, 5.0, 1.0, 1.0));
  collector.endLayer();
  const Document &doc = finishOnePage(collector);

  const auto groups = elementsOfType(doc, "group");
  CHECK_EQ(groups.size(), std::size_t(1));
  CHECK_EQ(groups[0]->wrapperKind, std::string("layer"));
  CHECK(hasWarning(*groups[0], "probable-authored-group"));
  CHECK(!hasWarning(*groups[0], "wrapper-not-a-group"));
  CHECK_EQ(std::string(compatibilityName(groups[0]->compatibility)), std::string("NATIVE"));
  CHECK_EQ(doc.counts.groupElements, 1LL);
  CHECK_EQ(doc.counts.wrapperElements, 0LL);
  // The children keep pointing at it, so the grouping is recoverable.
  CHECK_EQ(doc.elements[1].parentId, groups[0]->id);
  CHECK_EQ(doc.elements[2].parentId, groups[0]->id);
}

TEST(libmspub_group_layer_containing_a_layer_is_a_probable_group) {
  // A group whose child has both a fill and text: that child opens its own
  // layer inside the group's. A single shape never nests a layer.
  IrCollector collector;
  startOnePage(collector);
  collector.startLayer(RVNGPropertyList());
  collector.startLayer(RVNGPropertyList());
  collector.setStyle(solidFill());
  collector.drawRectangle(box(1.0, 1.0, 2.0, 1.0));
  collector.startTextObject(box(1.05, 1.05, 1.9, 0.9));
  collector.endTextObject();
  collector.endLayer();
  collector.endLayer();
  const Document &doc = finishOnePage(collector);

  const auto groups = elementsOfType(doc, "group");
  const auto wrappers = elementsOfType(doc, "wrapper");
  CHECK_EQ(groups.size(), std::size_t(1));
  CHECK_EQ(wrappers.size(), std::size_t(1));
  CHECK(groups[0]->parentId.empty());
  CHECK_EQ(wrappers[0]->parentId, groups[0]->id);
}

TEST(libmspub_single_shape_painted_in_passes_stays_a_wrapper) {
  // makeLayer: a filled shape with an outline and text. Fill, then the
  // outline drawn half outside the box, then the text frame inset within it.
  IrCollector collector;
  startOnePage(collector);
  collector.startLayer(RVNGPropertyList());
  collector.setStyle(solidFill());
  collector.drawPolygon(rectanglePolygon(1.0, 1.0, 3.0, 2.0));
  collector.setStyle(RVNGPropertyList());
  collector.drawPolyline(rectanglePolygon(0.98, 0.98, 3.04, 2.04));
  collector.startTextObject(box(1.05, 1.05, 2.9, 1.9));
  collector.endTextObject();
  collector.endLayer();
  const Document &doc = finishOnePage(collector);

  const auto wrappers = elementsOfType(doc, "wrapper");
  CHECK_EQ(wrappers.size(), std::size_t(1));
  CHECK_EQ(elementsOfType(doc, "group").size(), std::size_t(0));
  CHECK(hasWarning(*wrappers[0], "wrapper-not-a-group"));
  CHECK(!hasWarning(*wrappers[0], "probable-authored-group"));
  CHECK_EQ(std::string(compatibilityName(wrappers[0]->compatibility)), std::string("IGNORED"));
}

TEST(libmspub_cropped_shape_layer_keeps_its_clip_path_and_stays_a_wrapper) {
  // A cropped picture: startLayer carries svg:clip-path. Even with children
  // placed apart, the clip marks it as one shape, never a group.
  IrCollector collector;
  startOnePage(collector);
  RVNGPropertyList clip;
  clip.insert("svg:clip-path", "M 1 1 L 3 1 L 3 2 L 1 2 Z");
  collector.startLayer(clip);
  collector.setStyle(bitmapFill(tinyPng(0x40)));
  collector.drawPolygon(rectanglePolygon(1.0, 1.0, 2.0, 1.0));
  collector.setStyle(solidFill());
  collector.drawRectangle(box(5.0, 7.0, 1.0, 1.0));
  collector.endLayer();
  const Document &doc = finishOnePage(collector);

  const auto wrappers = elementsOfType(doc, "wrapper");
  CHECK_EQ(wrappers.size(), std::size_t(1));
  CHECK(hasWarning(*wrappers[0], "layer-clip-path"));
  bool keptClip = false;
  for (const SourceProperty &prop : wrappers[0]->sourceProperties) {
    if (prop.key == "svg:clip-path") keptClip = true;
  }
  CHECK(keptClip);
}

// --- pictures: rotation, flips and fill rotation -----------------------------

TEST(libmspub_rotated_picture_is_a_rotated_image_not_a_mask) {
  // Rotation folded into the outline: a rotated rectangle, no librevenge:rotate.
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(bitmapFill(tinyPng(0x41)));
  collector.drawPolygon(rotatedRectangle(2.0, 2.0, 3.0, 2.0, 30.0));
  const Document &doc = finishOnePage(collector);

  const Element &image = doc.elements[0];
  CHECK_EQ(image.type, std::string("image"));
  CHECK(!image.polygonIsRectangular); // still means axis-aligned
  CHECK(image.hasRotation);
  CHECK_NEAR(image.rotationDegrees, 30.0, 1e-6);
  CHECK(hasWarning(image, "rotation-from-outline"));
  CHECK(!hasWarning(image, "bitmap-fill-not-rectangular"));
  CHECK_EQ(std::string(compatibilityName(image.compatibility)), std::string("NATIVE"));
}

TEST(libmspub_rotation_direction_and_range_are_recovered) {
  // Counter-clockwise, as librevenge:rotate is, and reported in [0, 360).
  const double angles[] = {15.0, 90.0, 135.0, 200.0, 315.0};
  for (double angle : angles) {
    IrCollector collector;
    startOnePage(collector);
    collector.setStyle(bitmapFill(tinyPng(0x42)));
    collector.drawPolygon(rotatedRectangle(2.0, 2.0, 3.0, 1.5, angle));
    const Document &doc = finishOnePage(collector);
    // 90 degrees lands axis-aligned again, where no angle can be recovered
    // from the outline alone, and a 180-degree turn is indistinguishable
    // from none; the others must come back as given.
    if (angle == 90.0) {
      CHECK(doc.elements[0].polygonIsRectangular);
      continue;
    }
    CHECK(doc.elements[0].hasRotation);
    CHECK_NEAR(doc.elements[0].rotationDegrees, angle, 1e-6);
  }
}

TEST(libmspub_a_reported_rotation_is_not_overwritten_by_the_outline) {
  IrCollector collector;
  startOnePage(collector);
  RVNGPropertyList props = rotatedRectangle(1.0, 1.0, 2.0, 1.0, 30.0);
  props.insert("librevenge:rotate", 45.0, librevenge::RVNG_GENERIC);
  collector.setStyle(solidFill());
  collector.drawPolygon(props);
  const Document &doc = finishOnePage(collector);

  CHECK_NEAR(doc.elements[0].rotationDegrees, 45.0, 1e-9);
}

TEST(libmspub_flipped_picture_is_reported_as_mirrored) {
  // A flip folded into the outline reverses its winding.
  const double xs[4] = {1.0, 1.0, 3.0, 3.0}; // top-left, bottom-left, bottom-right, top-right
  const double ys[4] = {1.0, 2.0, 2.0, 1.0};
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(bitmapFill(tinyPng(0x43)));
  collector.drawPolygon(polygonFrom(xs, ys, 4));
  const Document &doc = finishOnePage(collector);

  const Element &image = doc.elements[0];
  CHECK(image.polygonIsRectangular);
  CHECK(hasWarning(image, "outline-mirrored"));
  CHECK(!image.hasRotation);
  CHECK_EQ(std::string(compatibilityName(image.compatibility)), std::string("NATIVE"));
}

TEST(libmspub_unflipped_picture_is_not_reported_as_mirrored) {
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(bitmapFill(tinyPng(0x44)));
  collector.drawPolygon(rectanglePolygon(1.0, 1.0, 2.0, 1.0));
  const Document &doc = finishOnePage(collector);

  CHECK(!hasWarning(doc.elements[0], "outline-mirrored"));
  CHECK(!hasWarning(doc.elements[0], "rotation-from-outline"));
}

TEST(libmspub_a_skewed_outline_is_still_treated_as_a_mask) {
  // A parallelogram without right angles is not a rotated rectangle.
  const double xs[4] = {1.0, 3.0, 3.5, 1.5};
  const double ys[4] = {1.0, 1.0, 2.0, 2.0};
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(bitmapFill(tinyPng(0x45)));
  collector.drawPolygon(polygonFrom(xs, ys, 4));
  const Document &doc = finishOnePage(collector);

  const Element &image = doc.elements[0];
  CHECK(!image.hasRotation);
  CHECK(hasWarning(image, "bitmap-fill-not-rectangular"));
  CHECK_EQ(std::string(compatibilityName(image.compatibility)), std::string("FLATTENED"));
}

TEST(libmspub_a_rotated_bitmap_fill_is_reported) {
  // ImgFill::getProperties puts the fill's own rotation on the style, as a string.
  RVNGPropertyList fill = bitmapFill(tinyPng(0x46));
  fill.insert("librevenge:rotate", "90");
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(fill);
  collector.drawPolygon(rectanglePolygon(1.0, 1.0, 2.0, 1.0));
  const Document &doc = finishOnePage(collector);

  CHECK(hasWarning(doc.elements[0], "fill-rotated"));
}

TEST(libmspub_a_picture_drawn_as_a_rectangle_is_not_treated_as_a_mask) {
  // drawRectangle has a box, not points; it is rectangular by definition.
  IrCollector collector;
  startOnePage(collector);
  collector.setStyle(bitmapFill(tinyPng(0x47)));
  collector.drawRectangle(box(1.0, 1.0, 2.0, 1.0));
  const Document &doc = finishOnePage(collector);

  CHECK_EQ(doc.elements[0].type, std::string("image"));
  CHECK_EQ(std::string(compatibilityName(doc.elements[0].compatibility)), std::string("NATIVE"));
}

// --- border art ----------------------------------------------------------------

TEST(libmspub_border_art_tiles_are_flagged_and_their_shape_stays_a_wrapper) {
  // hasBorderArt forces a layer; each tile is a writeImage -> drawGraphicObject
  // placed along the frame's inside edge.
  const std::string tile = tinyPng(0x48);
  IrCollector collector;
  startOnePage(collector);
  collector.startLayer(RVNGPropertyList());
  collector.setStyle(solidFill("#ffffff"));
  collector.drawRectangle(box(1.0, 1.0, 4.0, 3.0));
  collector.drawGraphicObject(graphicObject(tile, "image/png", 1.0, 1.0, 0.25, 0.25));
  collector.drawGraphicObject(graphicObject(tile, "image/png", 4.75, 1.0, 0.25, 0.25));
  collector.drawGraphicObject(graphicObject(tile, "image/png", 4.75, 3.75, 0.25, 0.25));
  collector.drawGraphicObject(graphicObject(tile, "image/png", 1.0, 3.75, 0.25, 0.25));
  collector.endLayer();
  const Document &doc = finishOnePage(collector);

  const auto images = elementsOfType(doc, "image");
  CHECK_EQ(images.size(), std::size_t(4));
  for (const Element *image : images) CHECK(hasWarning(*image, "probable-border-art"));
  // One tile, four placements.
  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK_EQ(doc.assets[0].uses.size(), std::size_t(4));
  CHECK_EQ(elementsOfType(doc, "wrapper").size(), std::size_t(1));
}

// --- embedded fonts ------------------------------------------------------------

TEST(libmspub_embedded_font_is_measured_in_bytes_not_base64_characters) {
  // libmspub defines every embedded font right after startDocument, before
  // any page, as an EOT payload (application/vnd.ms-fontobject).
  const std::string payload(100, '\x2a');
  RVNGPropertyList font;
  font.insert("librevenge:name", "SassoonPrimaryInfant");
  font.insert("librevenge:mime-type", "application/vnd.ms-fontobject");
  font.insert("office:binary-data", binary(payload));
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.defineEmbeddedFont(font);
  collector.startPage(page(8.0, 11.0));
  collector.startTextObject(box(1, 1, 4, 1));
  collector.openParagraph(RVNGPropertyList());
  collector.openSpan(span("SassoonPrimaryInfant", 14));
  collector.insertText("a");
  collector.closeSpan();
  collector.openSpan(span("SassoonPrimaryInfant", 14, true));
  collector.insertText("b");
  collector.closeSpan();
  collector.closeParagraph();
  collector.endTextObject();
  const Document &doc = finishOnePage(collector);

  CHECK_EQ(doc.fonts.size(), std::size_t(1));
  const FontUse &used = doc.fonts[0];
  CHECK(used.embedded);
  CHECK_EQ(used.embeddedMime, std::string("application/vnd.ms-fontobject"));
  CHECK_EQ(used.embeddedByteLength, 100LL); // base64 of 100 bytes is 136 characters
  // Two runs use it; defining it is not a use.
  CHECK_EQ(used.usageCount, 2LL);
  CHECK_EQ(used.firstPageIndex, 0);
}

TEST(libmspub_embedded_font_never_used_reports_no_usage) {
  RVNGPropertyList font;
  font.insert("librevenge:name", "Unused Face");
  font.insert("librevenge:mime-type", "application/vnd.ms-fontobject");
  font.insert("office:binary-data", binary(std::string(2, 'x')));
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.defineEmbeddedFont(font);
  collector.startPage(page(8.0, 11.0));
  const Document &doc = finishOnePage(collector);

  CHECK_EQ(doc.fonts.size(), std::size_t(1));
  CHECK_EQ(doc.fonts[0].usageCount, 0LL);
  CHECK_EQ(doc.fonts[0].embeddedByteLength, 2LL); // "eHg=": one padding character
}
