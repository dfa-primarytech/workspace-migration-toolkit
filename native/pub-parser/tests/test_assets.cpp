#include "testing.h"

#include "fixtures.h"
#include "image_info.h"
#include "sha256.h"

using namespace pubir;
using namespace fixtures;

TEST(sha256_matches_known_vectors) {
  CHECK_EQ(Sha256::of(std::string("")),
           std::string("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
  CHECK_EQ(Sha256::of(std::string("abc")),
           std::string("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
  // Spans a block boundary, which is where a padding bug would show.
  CHECK_EQ(Sha256::of(std::string(
               "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")),
           std::string("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"));
}

TEST(image_sniffs_png_dimensions) {
  const std::string png = tinyPng(0x01);
  const ImageInfo info = sniffImage(reinterpret_cast<const unsigned char *>(png.data()), png.size());
  CHECK_EQ(info.sniffedMime, std::string("image/png"));
  CHECK(info.hasDimensions);
  CHECK_EQ(info.pixelWidth, 1LL);
  CHECK_EQ(info.pixelHeight, 1LL);
}

TEST(image_sniffs_jpeg_dimensions_from_the_frame_header) {
  const std::string jpeg = tinyJpeg();
  const ImageInfo info =
      sniffImage(reinterpret_cast<const unsigned char *>(jpeg.data()), jpeg.size());
  CHECK_EQ(info.sniffedMime, std::string("image/jpeg"));
  CHECK(info.hasDimensions);
  CHECK_EQ(info.pixelWidth, 40LL);
  CHECK_EQ(info.pixelHeight, 30LL);
}

TEST(image_truncated_payload_does_not_read_past_the_end) {
  const std::string png = tinyPng(0x01).substr(0, 12);
  const ImageInfo info = sniffImage(reinterpret_cast<const unsigned char *>(png.data()), png.size());
  CHECK_EQ(info.sniffedMime, std::string("image/png"));
  CHECK(!info.hasDimensions);
}

TEST(image_unknown_payload_reports_nothing) {
  const std::string junk = "not an image at all";
  const ImageInfo info =
      sniffImage(reinterpret_cast<const unsigned char *>(junk.data()), junk.size());
  CHECK(info.sniffedMime.empty());
  CHECK(!info.hasDimensions);
}

TEST(image_extensions_are_safe_for_unknown_types) {
  CHECK_EQ(extensionForMime("image/png"), std::string("png"));
  CHECK_EQ(extensionForMime("image/jpeg"), std::string("jpg"));
  CHECK_EQ(extensionForMime("IMAGE/JPEG; charset=binary"), std::string("jpg"));
  CHECK_EQ(extensionForMime("application/x-anything"), std::string("bin"));
  // Nothing from the document may become a path component.
  CHECK_EQ(extensionForMime("../../etc/passwd"), std::string("bin"));
}

TEST(assets_arrive_through_the_draw_graphic_object_route) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x01), "image/png", 1, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK_EQ(doc.counts.imageElements, 1LL);
  CHECK_EQ(doc.elements[0].imageRoute, std::string("drawGraphicObject"));
  CHECK_EQ(doc.elements[0].assetId, doc.assets[0].id);
  CHECK_EQ(doc.assets[0].mime, std::string("image/png"));
  CHECK_EQ(doc.assets[0].filename, std::string("assets/") + doc.assets[0].sha256 + ".png");
  CHECK(doc.assets[0].hasPixelDimensions);
}

TEST(assets_arrive_through_the_bitmap_filled_polygon_route) {
  // The route that matters most in practice: the known Publisher sample
  // emits every visible image as a bitmap-filled polygon and never calls
  // drawGraphicObject. A parser watching only that callback would report
  // a document with no pictures in it.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.setStyle(bitmapFill(tinyPng(0x02)));
  collector.drawPolygon(rectanglePolygon(1, 1, 2, 1.5));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK_EQ(doc.counts.imageElements, 1LL);
  CHECK_EQ(doc.counts.shapeElements, 0LL);
  const Element &image = doc.elements[0];
  CHECK_EQ(image.type, std::string("image"));
  CHECK_EQ(image.imageRoute, std::string("bitmapFillShape"));
  CHECK(image.polygonIsRectangular);
  // The original outline is retained, not replaced by the bounding box.
  CHECK_EQ(image.points.size(), std::size_t(4));
  CHECK(image.bounds.valid);
  CHECK_NEAR(image.bounds.x, 72.0, 1e-6);
  CHECK_NEAR(image.bounds.width, 144.0, 1e-6);
  CHECK_NEAR(image.bounds.height, 108.0, 1e-6);
}

TEST(assets_bitmap_fill_in_a_non_rectangular_outline_is_flagged) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.setStyle(bitmapFill(tinyPng(0x03)));
  collector.drawPolygon(trianglePolygon());
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  const Element &image = doc.elements[0];
  CHECK_EQ(image.type, std::string("image"));
  CHECK(!image.polygonIsRectangular);
  CHECK(hasWarning(image, "bitmap-fill-not-rectangular"));
  CHECK_EQ(std::string(compatibilityName(image.compatibility)), std::string("FLATTENED"));
}

TEST(assets_with_identical_payloads_are_deduplicated) {
  // A school newsletter repeats its crest on every page. One asset, two
  // recorded uses.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x04), "image/png", 1, 1, 2, 2));
  collector.endPage();
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x04), "image/png", 3, 3, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(1));
  CHECK_EQ(doc.counts.assetPlacements, 2LL);
  CHECK_EQ(doc.assets[0].uses.size(), std::size_t(2));
  CHECK_EQ(doc.assets[0].uses[0].pageIndex, 0);
  CHECK_EQ(doc.assets[0].uses[1].pageIndex, 1);
  CHECK(doc.assets[0].uses[1].bounds.valid);
}

TEST(assets_with_different_payloads_stay_separate) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x05), "image/png", 1, 1, 2, 2));
  collector.drawGraphicObject(graphicObject(tinyJpeg(), "image/jpeg", 3, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(2));
  CHECK(doc.assets[0].sha256 != doc.assets[1].sha256);
  CHECK_EQ(doc.assets[1].mime, std::string("image/jpeg"));
}

TEST(assets_prefer_the_payload_signature_over_the_declared_type) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  // Declared JPEG, actually PNG.
  collector.drawGraphicObject(graphicObject(tinyPng(0x06), "image/jpeg", 1, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets[0].mime, std::string("image/png"));
  CHECK_EQ(doc.assets[0].declaredMime, std::string("image/jpeg"));
  bool flagged = false;
  for (const Note &note : doc.assets[0].warnings) {
    if (note.code == "mime-mismatch") flagged = true;
  }
  CHECK(flagged);
}

TEST(assets_report_unknown_placement_semantics) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject(tinyPng(0x07), "image/png", 1, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  bool flagged = false;
  for (const Note &note : doc.assets[0].warnings) {
    if (note.code == "placement-semantics-unknown") flagged = true;
  }
  CHECK(flagged);
}

TEST(assets_graphic_object_without_a_payload_becomes_unknown_not_nothing) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(box(1, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.assets.size(), std::size_t(0));
  CHECK_EQ(doc.elements.size(), std::size_t(1));
  CHECK_EQ(doc.elements[0].type, std::string("unknown"));
  CHECK_EQ(doc.counts.unknownElements, 1LL);
  CHECK(hasWarning(doc.elements[0], "graphic-without-payload"));
}

TEST(assets_a_new_style_clears_a_previous_bitmap_fill) {
  // Otherwise every shape after one picture would be misread as a picture.
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.setStyle(bitmapFill(tinyPng(0x08)));
  collector.drawPolygon(rectanglePolygon(0, 0, 1, 1));
  collector.setStyle(solidFill());
  collector.drawPolygon(rectanglePolygon(2, 2, 1, 1));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(doc.counts.imageElements, 1LL);
  CHECK_EQ(doc.counts.shapeElements, 1LL);
  CHECK_EQ(doc.counts.assetPlacements, 1LL);
}

TEST(assets_metafiles_are_candidates_for_flattening_not_native) {
  IrCollector collector;
  collector.startDocument(RVNGPropertyList());
  collector.startPage(page(8.0, 6.0));
  collector.drawGraphicObject(graphicObject("\xd7\xcd\xc6\x9a rest of a wmf", "image/x-wmf",
                                            1, 1, 2, 2));
  collector.endPage();
  collector.endDocument();
  const Document &doc = collector.finish();

  CHECK_EQ(std::string(compatibilityName(doc.elements[0].compatibility)), std::string("FLATTENED"));
  CHECK(!doc.assets[0].hasPixelDimensions);
}
