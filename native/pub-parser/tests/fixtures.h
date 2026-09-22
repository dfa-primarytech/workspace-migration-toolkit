// Synthetic callback fixtures.
//
// These build librevenge property lists by hand and feed them straight to
// the collector, which is the same thing libmspub does. That means the
// adapter is fully testable with no .pub file, no libmspub link and
// nothing sensitive in the repository -- and it lets a test construct
// callback sequences a real file would rarely produce, such as a span
// opened outside any paragraph.
#ifndef PUBIR_TEST_FIXTURES_H
#define PUBIR_TEST_FIXTURES_H

#include <librevenge/librevenge.h>

#include <string>
#include <vector>

#include "collector.h"

namespace fixtures {

using librevenge::RVNGPropertyList;

inline RVNGPropertyList page(double widthInches, double heightInches) {
  RVNGPropertyList props;
  props.insert("svg:width", widthInches, librevenge::RVNG_INCH);
  props.insert("svg:height", heightInches, librevenge::RVNG_INCH);
  return props;
}

inline RVNGPropertyList box(double x, double y, double width, double height) {
  RVNGPropertyList props;
  props.insert("svg:x", x, librevenge::RVNG_INCH);
  props.insert("svg:y", y, librevenge::RVNG_INCH);
  props.insert("svg:width", width, librevenge::RVNG_INCH);
  props.insert("svg:height", height, librevenge::RVNG_INCH);
  return props;
}

inline RVNGPropertyList span(const char *font, double sizePoints, bool bold = false,
                             bool italic = false) {
  RVNGPropertyList props;
  props.insert("style:font-name", font);
  props.insert("fo:font-size", sizePoints, librevenge::RVNG_POINT);
  if (bold) props.insert("fo:font-weight", "bold");
  if (italic) props.insert("fo:font-style", "italic");
  return props;
}

// An axis-aligned rectangle expressed the way libmspub emits a picture
// frame: four corner points, in inches.
inline RVNGPropertyList rectanglePolygon(double x, double y, double width, double height) {
  librevenge::RVNGPropertyListVector points;
  const double xs[4] = {x, x + width, x + width, x};
  const double ys[4] = {y, y, y + height, y + height};
  for (int i = 0; i < 4; i++) {
    RVNGPropertyList point;
    point.insert("svg:x", xs[i], librevenge::RVNG_INCH);
    point.insert("svg:y", ys[i], librevenge::RVNG_INCH);
    points.append(point);
  }
  RVNGPropertyList props;
  props.insert("svg:points", points);
  return props;
}

inline RVNGPropertyList trianglePolygon() {
  librevenge::RVNGPropertyListVector points;
  const double xs[3] = {0.0, 1.0, 0.5};
  const double ys[3] = {0.0, 0.0, 1.0};
  for (int i = 0; i < 3; i++) {
    RVNGPropertyList point;
    point.insert("svg:x", xs[i], librevenge::RVNG_INCH);
    point.insert("svg:y", ys[i], librevenge::RVNG_INCH);
    points.append(point);
  }
  RVNGPropertyList props;
  props.insert("svg:points", points);
  return props;
}

// A 1x1 8-bit RGB PNG. Real bytes, so the sniffer has something true to
// read; small enough to sit inline.
inline std::string tinyPng(unsigned char red) {
  static const unsigned char prefix[] = {
      0x89, 'P',  'N',  'G',  0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 'I',  'H',
      'D',  'R',  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02, 0x00, 0x00,
      0x00, 0x90, 0x77, 0x53, 0xde, 0x00, 0x00, 0x00, 0x0c, 'I',  'D',  'A',  'T',  0x08,
      0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0x00, 0x00, 0x03, 0x01, 0x01, 0x00};
  std::string data(reinterpret_cast<const char *>(prefix), sizeof(prefix));
  // The payload byte differs per colour so two fixtures hash differently.
  data.push_back(static_cast<char>(red));
  static const unsigned char suffix[] = {0x18, 0xdd, 0x8d, 0xb4, 0x00, 0x00, 0x00,
                                         0x00, 'I',  'E',  'N',  'D',  0xae, 0x42,
                                         0x60, 0x82};
  data.append(reinterpret_cast<const char *>(suffix), sizeof(suffix));
  return data;
}

// A minimal JPEG: SOI, a baseline SOF0 declaring 40x30, then EOI.
inline std::string tinyJpeg() {
  static const unsigned char bytes[] = {0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 'J',  'F',  'I',
                                        'F',  0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01,
                                        0x00, 0x00, 0xff, 0xc0, 0x00, 0x11, 0x08, 0x00, 0x1e,
                                        0x00, 0x28, 0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01,
                                        0x03, 0x11, 0x01, 0xff, 0xd9};
  return std::string(reinterpret_cast<const char *>(bytes), sizeof(bytes));
}

inline librevenge::RVNGBinaryData binary(const std::string &payload) {
  return librevenge::RVNGBinaryData(reinterpret_cast<const unsigned char *>(payload.data()),
                                    static_cast<unsigned long>(payload.size()));
}

// setStyle payload for the bitmap-fill route.
inline RVNGPropertyList bitmapFill(const std::string &payload, const char *mime = "image/png") {
  RVNGPropertyList props;
  props.insert("draw:fill", "bitmap");
  props.insert("librevenge:mime-type", mime);
  props.insert("draw:fill-image", binary(payload));
  return props;
}

inline RVNGPropertyList solidFill(const char *colour = "#ff0000") {
  RVNGPropertyList props;
  props.insert("draw:fill", "solid");
  props.insert("draw:fill-color", colour);
  return props;
}

inline RVNGPropertyList graphicObject(const std::string &payload, const char *mime,
                                      double x, double y, double width, double height) {
  RVNGPropertyList props = box(x, y, width, height);
  props.insert("librevenge:mime-type", mime);
  props.insert("office:binary-data", binary(payload));
  return props;
}

// Finds an element by id in a finished document.
inline const pubir::Element *elementById(const pubir::Document &doc, const std::string &id) {
  for (const pubir::Element &element : doc.elements) {
    if (element.id == id) return &element;
  }
  return nullptr;
}

inline std::vector<const pubir::Element *> elementsOfType(const pubir::Document &doc,
                                                          const std::string &type) {
  std::vector<const pubir::Element *> out;
  for (const pubir::Element &element : doc.elements) {
    if (element.type == type) out.push_back(&element);
  }
  return out;
}

inline bool hasDiagnostic(const pubir::Document &doc, const std::string &code) {
  for (const pubir::Diagnostic &d : doc.diagnostics) {
    if (d.code == code) return true;
  }
  return false;
}

inline bool hasWarning(const pubir::Element &element, const std::string &code) {
  for (const pubir::Note &note : element.warnings) {
    if (note.code == code) return true;
  }
  return false;
}

} // namespace fixtures

#endif
