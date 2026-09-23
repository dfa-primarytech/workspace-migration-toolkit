#include "collector.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "image_info.h"
#include "sha256.h"

namespace pubir {
namespace {

std::string propString(const librevenge::RVNGPropertyList &props, const char *name) {
  const librevenge::RVNGProperty *p = props[name];
  if (p == nullptr) return std::string();
  const librevenge::RVNGString s = p->getStr();
  return s.cstr() == nullptr ? std::string() : std::string(s.cstr());
}

// Bytes a base64 string decodes to, without decoding it. Whitespace is
// skipped and trailing '=' padding subtracted; any other character counts,
// so a malformed string is measured, not rejected.
long long base64DecodedLength(const char *text) {
  if (text == nullptr) return 0;
  long long symbols = 0;
  long long padding = 0;
  for (const char *c = text; *c != '\0'; ++c) {
    if (*c == ' ' || *c == '\n' || *c == '\r' || *c == '\t') continue;
    if (*c == '=') {
      padding++;
    } else {
      symbols += 1 + padding; // '=' before the end was not padding after all
      padding = 0;
    }
  }
  return (symbols + padding) / 4 * 3 - std::min(padding, 2LL);
}

int propInt(const librevenge::RVNGPropertyList &props, const char *name, int fallback) {
  const librevenge::RVNGProperty *p = props[name];
  return p == nullptr ? fallback : p->getInt();
}

bool propBool(const librevenge::RVNGPropertyList &props, const char *name, bool fallback) {
  const librevenge::RVNGProperty *p = props[name];
  if (p == nullptr) return fallback;
  const std::string s = propString(props, name);
  if (s == "true" || s == "1") return true;
  if (s == "false" || s == "0") return false;
  return p->getInt() != 0;
}

std::string serial(const char *prefix, int n, int width) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%s%0*d", prefix, width, n);
  return std::string(buf);
}

// librevenge spells weight and style as CSS-ish keywords rather than
// booleans, and libmspub only ever emits the "on" spellings.
bool isBoldValue(const std::string &v) { return v == "bold" || v == "700" || v == "800" || v == "900"; }
bool isItalicValue(const std::string &v) { return v == "italic" || v == "oblique"; }

} // namespace

const char *compatibilityName(Compatibility c) {
  switch (c) {
  case Compatibility::Native: return "NATIVE";
  case Compatibility::Substituted: return "SUBSTITUTED";
  case Compatibility::Flattened: return "FLATTENED";
  case Compatibility::Unsupported: return "UNSUPPORTED";
  case Compatibility::Ignored: return "IGNORED";
  }
  return "UNSUPPORTED";
}

std::vector<SourceProperty> flattenProperties(const librevenge::RVNGPropertyList &props) {
  std::vector<SourceProperty> out;
  librevenge::RVNGPropertyList::Iter it(props);
  for (it.rewind(); it.next();) {
    const char *key = it.key();
    if (key == nullptr) continue;
    const std::string name(key);

    if (it.child() != nullptr) {
      // Nested vectors (points, path commands, column definitions) are
      // read by the geometry code into typed fields. Record that one was
      // present so the provenance list is not quietly shorter than the
      // callback.
      out.push_back({name, "<propertyListVector>"});
      continue;
    }

    // Binary payloads go to the asset store, never into the JSON. A
    // base64 bitmap inside document.json would bloat it past the point of
    // being reviewable and duplicate what assets/ already holds.
    if (name == "office:binary-data" || name == "draw:fill-image") {
      out.push_back({name, "<binary>"});
      continue;
    }

    const librevenge::RVNGProperty *prop = it();
    if (prop == nullptr) continue;
    const librevenge::RVNGString value = prop->getStr();
    out.push_back({name, value.cstr() == nullptr ? std::string() : std::string(value.cstr())});
  }
  return out;
}

IrCollector::IrCollector(const Limits &limits)
    : limits_(limits), started_(std::chrono::steady_clock::now()) {}

void IrCollector::setSource(const std::string &filename, const std::string &sha256,
                            long long byteLength, const std::string &containerType,
                            const std::string &formatFamily) {
  doc_.sourceFilename = filename;
  doc_.sourceSha256 = sha256;
  doc_.sourceByteLength = byteLength;
  doc_.containerType = containerType;
  doc_.formatFamily = formatFamily;
}

void IrCollector::setSupported(bool supported) { doc_.supportedByParser = supported; }

void IrCollector::diagnose(const char *severity, const std::string &code, const std::string &message,
                           long long eventIndex, const std::string &elementId) {
  if (static_cast<long long>(doc_.diagnostics.size()) >= limits_.maxDiagnostics) return;
  Diagnostic d;
  d.severity = severity;
  d.code = code;
  d.message = message;
  d.pageIndex = openPage_ >= 0 ? doc_.pages[static_cast<std::size_t>(openPage_)].index : -1;
  d.eventIndex = eventIndex;
  d.elementId = elementId;
  doc_.diagnostics.push_back(std::move(d));
}

void IrCollector::limitation(const std::string &code, const std::string &message) {
  for (const Note &n : doc_.limitations) {
    if (n.code == code) return;
  }
  doc_.limitations.push_back({code, message});
}

void IrCollector::halt(const std::string &code, const std::string &message) {
  if (halt_) return;
  halt_ = true;
  doc_.truncated = true;
  doc_.truncationReason = code;
  diagnose("error", code, message, eventIndex_);
}

long long IrCollector::enter(const char *name) {
  // Counted even after a halt: a report that says "stopped at 200000
  // elements" is only useful next to the true callback total.
  doc_.callbackTotal++;
  doc_.callbackCounts[name]++;
  const long long index = eventIndex_++;

  if (halt_) return -1;

  if (doc_.callbackTotal > limits_.maxCallbacks) {
    halt("limit-callbacks", "callback limit reached; remaining callbacks are counted but not collected");
    return -1;
  }
  // Checking the clock on every callback would dominate a cheap one, so
  // sample it.
  if ((doc_.callbackTotal & 0x3ff) == 0) {
    const double elapsed =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
    if (elapsed > limits_.maxSeconds) {
      halt("limit-time", "parse time budget exhausted; remaining callbacks are counted but not collected");
      return -1;
    }
  }
  return index;
}

// --- pages -----------------------------------------------------------------

Page &IrCollector::ensurePage(long long eventIndex, const char *because) {
  if (openPage_ >= 0) return doc_.pages[static_cast<std::size_t>(openPage_)];

  Page page;
  page.index = nextPageSerial_ - 1;
  page.id = serial("page_", nextPageSerial_++, 4);
  page.kind = "page";
  page.implicit = true;
  page.startEventIndex = eventIndex;
  page.warnings.push_back(
      {"implicit-page", std::string("content arrived outside any page (") + because +
                            "); an implicit page was opened so the content is not lost"});
  doc_.pages.push_back(std::move(page));
  openPage_ = static_cast<int>(doc_.pages.size()) - 1;
  nextZIndex_ = 0;
  diagnose("warning", "implicit-page",
           std::string("content outside a page was attached to an implicit page (") + because + ")",
           eventIndex);
  return doc_.pages[static_cast<std::size_t>(openPage_)];
}

void IrCollector::closeOpenPage(long long eventIndex) {
  if (openPage_ < 0) return;
  doc_.pages[static_cast<std::size_t>(openPage_)].endEventIndex = eventIndex;
  openPage_ = -1;
  parentStack_.clear();
  textElementId_.clear();
  tableStack_.clear();
  paragraphOpen_ = false;
  spanOpen_ = false;
}

// --- elements --------------------------------------------------------------

Element *IrCollector::elementById(const std::string &id) {
  if (id.empty()) return nullptr;
  for (auto it = doc_.elements.rbegin(); it != doc_.elements.rend(); ++it) {
    if (it->id == id) return &(*it);
  }
  return nullptr;
}

Element *IrCollector::newElement(const std::string &type, const char *callback, long long eventIndex,
                                 const librevenge::RVNGPropertyList &props) {
  if (halt_) return nullptr;
  if (static_cast<long long>(doc_.elements.size()) >= limits_.maxElements) {
    halt("limit-elements", "element limit reached; remaining content is counted but not collected");
    return nullptr;
  }
  if (static_cast<long long>(parentStack_.size()) > limits_.maxElementDepth) {
    halt("limit-depth", "nesting depth limit reached; remaining content is counted but not collected");
    return nullptr;
  }

  Page &page = ensurePage(eventIndex, callback);

  Element element;
  element.id = serial("el_", nextElementSerial_++, 6);
  element.type = type;
  element.pageIndex = page.index;
  element.zIndex = nextZIndex_++;
  element.sourceCallback = callback;
  element.eventIndex = eventIndex;
  element.endEventIndex = eventIndex;
  element.sourceProperties = flattenProperties(props);
  element.styleProperties = currentStyle_;
  element.styleEventIndex = currentStyleEvent_;
  if (!parentStack_.empty()) element.parentId = parentStack_.back();

  boundsFromProps(props, element.bounds);

  const librevenge::RVNGProperty *rotate = props["librevenge:rotate"];
  if (rotate != nullptr) {
    element.hasRotation = true;
    element.rotationDegrees = rotate->getDouble();
  }

  page.elementIds.push_back(element.id);
  doc_.elements.push_back(std::move(element));
  return &doc_.elements.back();
}

void IrCollector::finishElement(Element *element, long long eventIndex) {
  if (element != nullptr && eventIndex >= 0) element->endEventIndex = eventIndex;
}

bool IrCollector::boundsFromProps(const librevenge::RVNGPropertyList &props, Bounds &out) {
  const Length x = lengthProp(props, "svg:x");
  const Length y = lengthProp(props, "svg:y");
  const Length w = lengthProp(props, "svg:width");
  const Length h = lengthProp(props, "svg:height");
  if (x.valid && y.valid && w.valid && h.valid) {
    out.valid = true;
    out.x = x.points;
    out.y = y.points;
    out.width = w.points;
    out.height = h.points;
    return true;
  }
  // Lines and connectors carry endpoints instead of a box.
  const Length x1 = lengthProp(props, "svg:x1");
  const Length y1 = lengthProp(props, "svg:y1");
  const Length x2 = lengthProp(props, "svg:x2");
  const Length y2 = lengthProp(props, "svg:y2");
  if (x1.valid && y1.valid && x2.valid && y2.valid) {
    out.valid = true;
    out.x = std::min(x1.points, x2.points);
    out.y = std::min(y1.points, y2.points);
    out.width = std::fabs(x2.points - x1.points);
    out.height = std::fabs(y2.points - y1.points);
    return true;
  }
  return false;
}

Bounds IrCollector::boundsFromPoints(const std::vector<Point2> &points) {
  Bounds b;
  if (points.empty()) return b;
  double minX = points[0].x, maxX = points[0].x;
  double minY = points[0].y, maxY = points[0].y;
  for (const Point2 &p : points) {
    minX = std::min(minX, p.x);
    maxX = std::max(maxX, p.x);
    minY = std::min(minY, p.y);
    maxY = std::max(maxY, p.y);
  }
  b.valid = true;
  b.x = minX;
  b.y = minY;
  b.width = maxX - minX;
  b.height = maxY - minY;
  return b;
}

// --- geometry --------------------------------------------------------------

void IrCollector::readGeometry(Element &element, const librevenge::RVNGPropertyList &props) {
  const librevenge::RVNGPropertyListVector *points = props.child("svg:points");
  if (points != nullptr) {
    const unsigned long count = points->count();
    if (static_cast<long long>(count) > limits_.maxPointsPerShape) {
      element.warnings.push_back({"limit-points", "point count exceeded the per-shape limit; "
                                                  "the point list was not collected"});
      limitation("limit-points", "at least one shape had more points than the parser collects");
    } else {
      for (unsigned long i = 0; i < count; i++) {
        const librevenge::RVNGPropertyList &entry = (*points)[i];
        const Length px = lengthProp(entry, "svg:x");
        const Length py = lengthProp(entry, "svg:y");
        if (!px.valid || !py.valid) {
          element.warnings.push_back({"point-not-a-length",
                                      "a polygon point was not expressed as a length and was skipped"});
          continue;
        }
        element.points.push_back({px.points, py.points});
      }
      element.hasGeometry = !element.points.empty();
    }
  }

  const librevenge::RVNGPropertyListVector *path = props.child("svg:d");
  if (path != nullptr) {
    const unsigned long count = path->count();
    if (static_cast<long long>(count) > limits_.maxPathCommands) {
      element.warnings.push_back({"limit-path", "path command count exceeded the limit; "
                                                "the path was not collected"});
      limitation("limit-path", "at least one path had more commands than the parser collects");
    } else {
      for (unsigned long i = 0; i < count; i++) {
        const librevenge::RVNGPropertyList &entry = (*path)[i];
        PathCommand cmd;
        cmd.action = propString(entry, "librevenge:path-action");
        // Kept verbatim, including the control points and arc flags: which
        // of these a Slides shape can express is the renderer's problem,
        // and discarding them here would make that decision unrecoverable.
        cmd.properties = flattenProperties(entry);
        element.path.push_back(std::move(cmd));
      }
      element.hasGeometry = element.hasGeometry || !element.path.empty();
    }
  }

  if (!element.bounds.valid && !element.points.empty()) {
    element.bounds = boundsFromPoints(element.points);
  }

  // A rectangle drawn as a polygon is the shape Publisher uses to carry a
  // picture, so whether the outline is an axis-aligned box is evidence the
  // renderer needs, not a cosmetic detail.
  if (element.points.size() == 4 || element.points.size() == 5) {
    std::vector<Point2> pts = element.points;
    if (pts.size() == 5) {
      const double dx = std::fabs(pts[4].x - pts[0].x);
      const double dy = std::fabs(pts[4].y - pts[0].y);
      if (dx < 0.01 && dy < 0.01) pts.pop_back(); // explicit closing point
    }
    if (pts.size() == 4) {
      const double eps = 0.01; // a hundredth of a point
      const bool pairA = std::fabs(pts[0].y - pts[1].y) < eps && std::fabs(pts[1].x - pts[2].x) < eps &&
                         std::fabs(pts[2].y - pts[3].y) < eps && std::fabs(pts[3].x - pts[0].x) < eps;
      const bool pairB = std::fabs(pts[0].x - pts[1].x) < eps && std::fabs(pts[1].y - pts[2].y) < eps &&
                         std::fabs(pts[2].x - pts[3].x) < eps && std::fabs(pts[3].y - pts[0].y) < eps;
      element.polygonIsRectangular = pairA || pairB;
      readRectangleOrientation(element, pts);
    }
  }
}

// libmspub 0.1.4 reports rotation (librevenge:rotate) for text frames only.
// For every other shape it folds rotation and flips into the outline's
// coordinates, so a rotated picture arrives as a rotated rectangle -- which
// without this would be read as a non-rectangular outline acting as a mask.
void IrCollector::readRectangleOrientation(Element &element, const std::vector<Point2> &pts) {
  const double ax = pts[1].x - pts[0].x, ay = pts[1].y - pts[0].y;
  const double bx = pts[2].x - pts[1].x, by = pts[2].y - pts[1].y;
  const double cx = pts[3].x - pts[2].x, cy = pts[3].y - pts[2].y;
  const double dx = pts[0].x - pts[3].x, dy = pts[0].y - pts[3].y;
  const double lengthA = std::hypot(ax, ay);
  const double lengthB = std::hypot(bx, by);
  if (lengthA <= 0.0 || lengthB <= 0.0) return;

  const double eps = 0.01; // a hundredth of a point, as for axis alignment
  const bool parallelogram = std::fabs(ax + cx) < eps && std::fabs(ay + cy) < eps &&
                             std::fabs(bx + dx) < eps && std::fabs(by + dy) < eps;
  const bool rightAngle = std::fabs(ax * bx + ay * by) / (lengthA * lengthB) < 1e-4;
  if (!parallelogram || !rightAngle) return;

  // Winding. libmspub's rectangle outline runs top-left, top-right,
  // bottom-right, bottom-left, which is clockwise on a page whose y axis
  // points down. Wound the other way, the shape was flipped once.
  double twiceArea = 0.0;
  for (std::size_t i = 0; i < pts.size(); i++) {
    const Point2 &p = pts[i];
    const Point2 &q = pts[(i + 1) % pts.size()];
    twiceArea += p.x * q.y - q.x * p.y;
  }
  if (twiceArea < 0.0) {
    element.outlineIsMirrored = true;
    element.warnings.push_back(
        {"outline-mirrored",
         "the rectangular outline is wound opposite to an unflipped one, which usually means the "
         "shape was flipped; libmspub does not report flips, and a bitmap fill is not mirrored "
         "with its outline"});
  }

  if (element.polygonIsRectangular) return;
  element.outlineIsRotatedRectangle = true;
  if (!element.hasRotation) {
    // Counter-clockwise on the page, in degrees, matching librevenge:rotate.
    constexpr double kPi = 3.14159265358979323846;
    double degrees = std::atan2(-ay, ax) * 180.0 / kPi;
    if (degrees < 0.0) degrees += 360.0;
    element.hasRotation = true;
    element.rotationDegrees = degrees;
  }
  element.warnings.push_back(
      {"rotation-from-outline",
       "the rotation was recovered from a rotated rectangular outline, not reported by the "
       "import filter; bounds are the outline's axis-aligned extent and the points are the "
       "rotated frame"});
}

// --- assets ----------------------------------------------------------------

std::string IrCollector::registerAsset(const librevenge::RVNGBinaryData &data,
                                       const std::string &declaredMime, long long eventIndex) {
  const unsigned long size = data.size();
  if (size == 0) {
    diagnose("warning", "empty-asset", "an image payload was empty and produced no asset", eventIndex);
    return std::string();
  }
  if (static_cast<long long>(size) > limits_.maxAssetBytes) {
    diagnose("error", "limit-asset-size",
             "an image payload exceeded the per-asset size limit and was not extracted", eventIndex);
    limitation("limit-asset-size", "at least one image exceeded the per-asset size limit");
    return std::string();
  }

  const unsigned char *buffer = data.getDataBuffer();
  if (buffer == nullptr) return std::string();
  const std::string hash = Sha256::of(buffer, static_cast<std::size_t>(size));

  // Deduplicate by content. A Publisher newsletter reuses the same school
  // crest on every page; writing it four times would quadruple the bundle
  // and lose the fact that it is one picture.
  auto existing = assetByHash_.find(hash);
  if (existing != assetByHash_.end()) return existing->second;

  if (static_cast<long long>(doc_.assets.size()) >= limits_.maxAssets) {
    diagnose("error", "limit-asset-count",
             "asset count limit reached; further images were not extracted", eventIndex);
    limitation("limit-asset-count", "the asset count limit was reached");
    return std::string();
  }
  if (totalAssetBytes_ + static_cast<long long>(size) > limits_.maxTotalAssetBytes) {
    diagnose("error", "limit-asset-total",
             "total asset size limit reached; further images were not extracted", eventIndex);
    limitation("limit-asset-total", "the total asset size limit was reached");
    return std::string();
  }

  Asset asset;
  asset.id = serial("asset_", nextAssetSerial_++, 4);
  asset.sha256 = hash;
  asset.declaredMime = normaliseMime(declaredMime);
  asset.byteLength = static_cast<long long>(size);
  asset.data.assign(reinterpret_cast<const char *>(buffer), static_cast<std::size_t>(size));

  const ImageInfo info = sniffImage(buffer, static_cast<std::size_t>(size));
  asset.sniffedMime = info.sniffedMime;
  asset.hasPixelDimensions = info.hasDimensions;
  asset.pixelWidth = info.pixelWidth;
  asset.pixelHeight = info.pixelHeight;

  // The payload's own magic bytes beat the container's claim: the file was
  // written by an application that is being retired, and a wrong extension
  // would break the renderer downstream rather than here.
  if (!info.sniffedMime.empty()) {
    asset.mime = info.sniffedMime;
    if (!asset.declaredMime.empty() && asset.declaredMime != info.sniffedMime) {
      asset.warnings.push_back({"mime-mismatch", "the declared MIME type did not match the payload; "
                                                 "the sniffed type was used"});
    }
  } else if (!asset.declaredMime.empty()) {
    asset.mime = asset.declaredMime;
    asset.warnings.push_back({"mime-unverified", "the payload matched no known image signature; "
                                                 "the declared MIME type was kept unverified"});
  } else {
    asset.mime = "application/octet-stream";
    asset.warnings.push_back({"mime-unknown", "no MIME type was declared and the payload matched no "
                                              "known image signature"});
  }

  if (!asset.hasPixelDimensions) {
    asset.warnings.push_back({"dimensions-unknown",
                              "pixel dimensions are not readable from this format's header without "
                              "decoding, which the parser does not do"});
  }
  // These are properties of the *placement*, not the payload, and Publisher
  // expresses them in ways this parser does not yet recover. Saying so per
  // asset keeps a renderer from assuming the picture is unmodified.
  asset.warnings.push_back({"placement-semantics-unknown",
                            "crop, mask, transparency and recolouring semantics are not recovered; "
                            "the payload is the stored original, not the rendered appearance"});

  // Filename is generated from the content hash: nothing from the document
  // reaches the filesystem, so a hostile .pub cannot choose a path.
  asset.filename = "assets/" + hash + "." + extensionForMime(asset.mime);

  totalAssetBytes_ += asset.byteLength;
  assetByHash_[hash] = asset.id;
  doc_.assets.push_back(std::move(asset));
  return doc_.assets.back().id;
}

void IrCollector::recordAssetUse(Element &element, const std::string &assetId) {
  for (Asset &asset : doc_.assets) {
    if (asset.id != assetId) continue;
    AssetUse use;
    use.pageIndex = element.pageIndex;
    use.elementId = element.id;
    use.eventIndex = element.eventIndex;
    use.route = element.imageRoute;
    use.bounds = element.bounds;
    use.polygonIsRectangular = element.polygonIsRectangular;
    use.polygon = element.points;
    use.path = element.path;
    asset.uses.push_back(std::move(use));
    return;
  }
}

void IrCollector::noteFont(const std::string &family, long long eventIndex) {
  if (family.empty()) return;
  for (FontUse &font : doc_.fonts) {
    if (font.family == family) {
      if (font.usageCount == 0) {
        // Defined (embedded) before its first use: record where that use is.
        font.firstPageIndex =
            openPage_ >= 0 ? doc_.pages[static_cast<std::size_t>(openPage_)].index : -1;
        font.firstEventIndex = eventIndex;
      }
      font.usageCount++;
      return;
    }
  }
  FontUse font;
  font.family = family;
  font.usageCount = 1;
  font.firstPageIndex = openPage_ >= 0 ? doc_.pages[static_cast<std::size_t>(openPage_)].index : -1;
  font.firstEventIndex = eventIndex;
  doc_.fonts.push_back(std::move(font));
}

// --- text ------------------------------------------------------------------

std::vector<Paragraph> *IrCollector::textSink() {
  // A table cell wins over the enclosing text object: librevenge nests
  // text inside cells, and the innermost open container owns the content.
  if (!tableStack_.empty() && tableStack_.back().cellOpen) {
    Element *table = elementById(tableStack_.back().elementId);
    if (table != nullptr && !table->table.rows.empty()) {
      TableRow &row = table->table.rows.back();
      if (!row.cells.empty()) return &row.cells.back().paragraphs;
    }
    return nullptr;
  }
  Element *text = elementById(textElementId_);
  return text == nullptr ? nullptr : &text->paragraphs;
}

Paragraph *IrCollector::currentParagraph() {
  std::vector<Paragraph> *sink = textSink();
  if (sink == nullptr || sink->empty()) return nullptr;
  return &sink->back();
}

Run *IrCollector::currentRun() {
  Paragraph *paragraph = currentParagraph();
  if (paragraph == nullptr || paragraph->runs.empty()) return nullptr;
  return &paragraph->runs.back();
}

Paragraph *IrCollector::ensureParagraph(long long eventIndex) {
  std::vector<Paragraph> *sink = textSink();
  if (sink != nullptr && !sink->empty() && paragraphOpen_) return &sink->back();

  if (sink == nullptr) {
    // Text with no frame at all. A truncated or malformed stream does this,
    // and the words are still real, so give them somewhere to live rather
    // than dropping them on the floor.
    librevenge::RVNGPropertyList empty;
    Element *frame = newElement("text", "insertText", eventIndex, empty);
    if (frame == nullptr) return nullptr; // halted or at the element limit
    frame->compatibility = Compatibility::Native;
    frame->compatibilityEvidence = "an implicit text frame holding text that arrived with no frame";
    frame->warnings.push_back({"implicit-text-frame",
                               "text arrived outside any text object or table cell; this frame was "
                               "created so the text is not lost, and it has no source geometry"});
    textElementId_ = frame->id;
    diagnose("warning", "implicit-text-frame",
             "text arrived with no open text object; an implicit text frame was created", eventIndex);
    sink = textSink();
    if (sink == nullptr) return nullptr;
  }

  // Content before openParagraph is malformed, but the text is real and
  // losing it would be worse than recording that the structure was odd.
  librevenge::RVNGPropertyList empty;
  openParagraphInternal(empty, eventIndex, std::string());
  sink = textSink();
  if (sink == nullptr || sink->empty()) return nullptr;
  sink->back().implicit = true;
  diagnose("warning", "implicit-paragraph",
           "text arrived with no open paragraph; an implicit paragraph was created", eventIndex);
  return &sink->back();
}

Run *IrCollector::ensureRun(long long eventIndex) {
  Paragraph *paragraph = ensureParagraph(eventIndex);
  if (paragraph == nullptr) return nullptr;
  if (spanOpen_ && !paragraph->runs.empty()) return &paragraph->runs.back();

  Run run;
  run.index = runSerial_++;
  run.eventIndex = eventIndex;
  run.implicit = true;
  run.linkHref = pendingLinkHref_;
  paragraph->runs.push_back(std::move(run));
  spanOpen_ = true;
  doc_.counts.runs++;
  diagnose("warning", "implicit-span",
           "text arrived with no open span; an implicit run was created", eventIndex);
  return &paragraph->runs.back();
}

void IrCollector::appendTextItem(TextItem item, long long eventIndex) {
  if (halt_) return;
  textBytes_ += static_cast<long long>(item.value.size()) + 1;
  if (textBytes_ > limits_.maxTextBytes) {
    halt("limit-text", "text size limit reached; remaining content is counted but not collected");
    return;
  }

  Run *run = ensureRun(eventIndex);
  if (run == nullptr) {
    diagnose("error", "text-not-collected",
             "text could not be attached to any frame because collection had already stopped",
             eventIndex);
    return;
  }
  if (item.kind == "text") {
    run->text += item.value;
  } else if (item.kind == "space") {
    run->text += ' ';
  } else if (item.kind == "tab") {
    run->text += '\t';
  } else if (item.kind == "lineBreak") {
    run->text += '\n';
  }
  // A field contributes nothing to `text`: its displayed value depends on
  // rendering context this parser does not have, and inventing one would
  // put fiction into the text layer. The field itself survives in `items`.
  run->items.push_back(std::move(item));
}

void IrCollector::openParagraphInternal(const librevenge::RVNGPropertyList &props,
                                        long long eventIndex, const std::string &listKind) {
  std::vector<Paragraph> *sink = textSink();
  if (sink == nullptr) {
    diagnose("warning", "paragraph-without-container",
             "a paragraph arrived with no open text object or table cell and was dropped from the "
             "text tree; the callback is still counted",
             eventIndex);
    return;
  }
  if (static_cast<long long>(sink->size()) >= limits_.maxParagraphsPerContainer) {
    halt("limit-paragraphs", "paragraph limit reached; remaining content is counted but not collected");
    return;
  }

  Paragraph paragraph;
  paragraph.index = paragraphSerial_++;
  paragraph.eventIndex = eventIndex;
  paragraph.style = flattenProperties(props);
  paragraph.alignment = propString(props, "fo:text-align");
  const librevenge::RVNGProperty *lineHeight = props["fo:line-height"];
  if (lineHeight != nullptr) {
    paragraph.hasLineHeight = true;
    paragraph.lineHeight = lineHeight->getDouble();
  }
  paragraph.listKind = listKind.empty() && !listKindStack_.empty() ? listKindStack_.back() : listKind;
  paragraph.listLevel = static_cast<int>(listKindStack_.size());

  sink->push_back(std::move(paragraph));
  paragraphOpen_ = true;
  spanOpen_ = false;
  doc_.counts.paragraphs++;
}

void IrCollector::closeParagraphInternal() {
  paragraphOpen_ = false;
  spanOpen_ = false;
}

// --- shapes ----------------------------------------------------------------

void IrCollector::drawShape(const char *callback, const std::string &shapeKind,
                            const librevenge::RVNGPropertyList &props, long long eventIndex) {
  // Route 2. Publisher paints pictures as a shape with a bitmap fill far
  // more often than it calls drawGraphicObject; on the sample that drove
  // this design, *every* visible image came through here. A parser that
  // only watched drawGraphicObject would report a document with no images.
  const bool bitmapFill = !currentFillAssetId_.empty();

  std::string type;
  if (bitmapFill) {
    type = "image";
  } else if (shapeKind == "polyline" || shapeKind == "connector") {
    type = "line";
  } else if (shapeKind == "path") {
    type = "path";
  } else {
    type = "shape";
  }

  Element *element = newElement(type, callback, eventIndex, props);
  if (element == nullptr) return;
  element->shapeKind = shapeKind;
  readGeometry(*element, props);

  // A rotated rectangle is still a rectangular placement; only the angle
  // differs. See readRectangleOrientation.
  // drawRectangle carries a box rather than points, so it never sets
  // polygonIsRectangular -- but it is rectangular by definition.
  const bool rectangularPlacement = shapeKind == "rectangle" || element->polygonIsRectangular ||
                                    element->outlineIsRotatedRectangle;

  if (bitmapFill) {
    element->imageRoute = "bitmapFillShape";
    element->assetId = currentFillAssetId_;
    for (const SourceProperty &prop : currentStyle_) {
      if (prop.key != "librevenge:rotate") continue;
      element->warnings.push_back(
          {"fill-rotated", "the bitmap fill declares its own rotation (" + prop.value +
                               ") inside the outline; it is kept in the style properties "
                               "and not applied"});
      break;
    }
    if (!rectangularPlacement && shapeKind == "polygon") {
      element->warnings.push_back({"bitmap-fill-not-rectangular",
                                   "a bitmap fill was painted into a non-rectangular outline; the "
                                   "outline is retained because it may be acting as a mask"});
    }
    recordAssetUse(*element, element->assetId);
    doc_.counts.assetPlacements++;
  }

  // Parser-stage candidates. See Element::compatibilityEvidence -- none of
  // these has been checked against an actual Google import.
  if (bitmapFill) {
    element->compatibility = Compatibility::Native;
    element->compatibilityEvidence =
        element->outlineIsRotatedRectangle
            ? "a raster payload in a rotated rectangular placement maps to a rotated Slides image"
            : "a raster payload with a rectangular placement maps to a Slides image";
    if (!rectangularPlacement) {
      element->compatibility = Compatibility::Flattened;
      element->compatibilityEvidence =
          "a bitmap fill in a non-rectangular outline has no direct Slides equivalent";
    }
  } else if (shapeKind == "rectangle" || shapeKind == "ellipse") {
    element->compatibility = Compatibility::Native;
    element->compatibilityEvidence = "a basic shape with a direct Slides equivalent";
  } else if (type == "line") {
    element->compatibility = Compatibility::Native;
    element->compatibilityEvidence = "a line or connector maps to a Slides line";
  } else if (shapeKind == "polygon") {
    element->compatibility = Compatibility::Substituted;
    element->compatibilityEvidence =
        "an arbitrary polygon has no exact Slides shape and would need the closest match";
  } else {
    element->compatibility = Compatibility::Flattened;
    element->compatibilityEvidence =
        "an arbitrary path cannot be expressed as an editable Slides shape";
  }
  finishElement(element, eventIndex);
}

void IrCollector::startWrapper(const std::string &wrapperKind, const std::string &type,
                               const char *callback, const librevenge::RVNGPropertyList &props,
                               long long eventIndex) {
  Element *element = newElement(type, callback, eventIndex, props);
  if (element == nullptr) {
    // Still push a placeholder so the matching close pops the right depth.
    parentStack_.push_back(std::string());
    return;
  }
  element->wrapperKind = wrapperKind;
  if (type == "wrapper") {
    element->compatibility = Compatibility::Ignored;
    element->compatibilityEvidence =
        "a rendering wrapper emitted by the import filter, not evidence of a group the author made";
    element->warnings.push_back(
        {"wrapper-not-a-group", "startLayer/startEmbeddedGraphics is a rendering construct; do not "
                                "treat it as a Publisher group without stronger evidence"});
  } else {
    element->compatibility = Compatibility::Native;
    element->compatibilityEvidence = "an explicit group maps to a Slides group";
  }
  parentStack_.push_back(element->id);
}

void IrCollector::endWrapper(const std::string &wrapperKind, const char *callback,
                             long long eventIndex) {
  if (parentStack_.empty()) {
    diagnose("warning", "unbalanced-close",
             std::string(callback) + " arrived with no matching open; it was ignored", eventIndex);
    return;
  }
  const std::string id = parentStack_.back();
  parentStack_.pop_back();
  Element *element = elementById(id);
  if (element == nullptr) return;
  if (element->wrapperKind != wrapperKind) {
    element->warnings.push_back({"unbalanced-nesting",
                                 "this container was closed by a callback of a different kind"});
    diagnose("warning", "unbalanced-nesting",
             std::string(callback) + " closed a container opened as " + element->wrapperKind,
             eventIndex, element->id);
  }
  if (element->wrapperKind == "layer") classifyLayer(*element);
  finishElement(element, eventIndex);
}

// libmspub 0.1.4 never calls openGroup. It uses startLayer for two things:
//
//  - an authored group: a shape with children opens a layer with no
//    properties, paints each child, then closes it (paintShape, isGroup);
//  - one shape painted in several passes: border art, or any two of stroke,
//    fill and text, are wrapped in a layer -- carrying svg:clip-path when
//    the shape is cropped.
//
// Both empty kinds look identical when they open, so the decision is made
// at close from what the layer contains. A multi-pass layer holds pieces of
// one shape, all within or just around its box, and never a nested layer.
// A group holds separately placed shapes, and any multi-pass child opens a
// layer of its own. The rule is deliberately conservative: a group whose
// largest child happens to contain the others stays a wrapper, which loses
// the grouping but no content.
void IrCollector::classifyLayer(Element &layer) {
  if (!layer.sourceProperties.empty()) {
    layer.warnings.push_back(
        {"layer-clip-path",
         "this layer carries a clip path, which libmspub emits for a cropped shape; the path is "
         "kept in sourceProperties and is not applied"});
    return;
  }

  bool nestedLayer = false;
  std::vector<Bounds> boxes;
  for (const Element &child : doc_.elements) {
    if (child.parentId != layer.id) continue;
    if (child.wrapperKind == "layer") nestedLayer = true;
    if (child.bounds.valid) boxes.push_back(child.bounds);
  }

  bool scattered = false;
  if (boxes.size() >= 2) {
    std::size_t largest = 0;
    for (std::size_t i = 1; i < boxes.size(); i++) {
      if (boxes[i].width * boxes[i].height > boxes[largest].width * boxes[largest].height) {
        largest = i;
      }
    }
    const Bounds &frame = boxes[largest];
    // Allows for an outline drawn outside the shape and for the inset
    // libmspub gives a text frame inside its border.
    const double tolerance = std::max(3.0, 0.05 * std::max(frame.width, frame.height));
    for (const Bounds &b : boxes) {
      if (b.x < frame.x - tolerance || b.y < frame.y - tolerance ||
          b.x + b.width > frame.x + frame.width + tolerance ||
          b.y + b.height > frame.y + frame.height + tolerance) {
        scattered = true;
        break;
      }
    }
  }
  if (!nestedLayer && !scattered) return;

  layer.type = "group";
  layer.compatibility = Compatibility::Native;
  layer.compatibilityEvidence = "a probable authored group maps to a Slides group";
  layer.warnings.erase(std::remove_if(layer.warnings.begin(), layer.warnings.end(),
                                      [](const Note &note) {
                                        return note.code == "wrapper-not-a-group";
                                      }),
                       layer.warnings.end());
  layer.warnings.push_back(
      {"probable-authored-group",
       nestedLayer
           ? "inferred from a layer that contains another layer: libmspub opens a layer inside a "
             "group for each multi-pass child, and never inside a single shape"
           : "inferred from a layer whose children are placed separately rather than around one "
             "shape; libmspub emits authored groups as layers and never calls openGroup"});
}

// --- RVNGDrawingInterface --------------------------------------------------

void IrCollector::startDocument(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startDocument");
  (void)event;
  (void)props;
  started_ = std::chrono::steady_clock::now();
}

void IrCollector::endDocument() {
  const long long event = enter("endDocument");
  closeOpenPage(event);
}

void IrCollector::setDocumentMetaData(const librevenge::RVNGPropertyList &props) {
  enter("setDocumentMetaData");
  doc_.metadata = flattenProperties(props);
  doc_.title = propString(props, "dc:title");
}

void IrCollector::defineEmbeddedFont(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("defineEmbeddedFont");
  const std::string name = propString(props, "librevenge:name");
  // A definition is not a use: usageCount counts runs set in the font, so a
  // font embedded but never used must report zero. libmspub defines embedded
  // fonts before any page, so the entry normally does not exist yet.
  FontUse *font = nullptr;
  for (FontUse &existing : doc_.fonts) {
    if (existing.family == name) font = &existing;
  }
  if (font == nullptr && !name.empty()) {
    FontUse added;
    added.family = name;
    added.firstPageIndex = -1;
    added.firstEventIndex = event;
    doc_.fonts.push_back(std::move(added));
    font = &doc_.fonts.back();
  }
  if (font != nullptr) {
    font->embedded = true;
    font->embeddedMime = normaliseMime(propString(props, "librevenge:mime-type"));
    const librevenge::RVNGProperty *data = props["office:binary-data"];
    if (data != nullptr) {
      // Size only. The font binary is not extracted: redistributing an
      // embedded typeface is a licensing decision, not a parser's. The
      // property reads back as base64 text, so the byte length is derived
      // from it rather than taken as the text's length -- which would
      // over-report by a third -- and without decoding the font into memory.
      font->embeddedByteLength = base64DecodedLength(data->getStr().cstr());
    }
  }
  limitation("embedded-fonts-not-extracted",
             "embedded font payloads are recorded but not extracted; redistributing a bundled "
             "typeface is a licensing decision for the renderer, not the parser");
}

void IrCollector::startPage(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startPage");
  if (halt_) return;
  if (openPage_ >= 0) {
    diagnose("warning", "nested-page", "startPage arrived while a page was open; the open page was "
                                       "closed first", event);
    closeOpenPage(event);
  }
  if (static_cast<long long>(doc_.pages.size()) >= limits_.maxPages) {
    halt("limit-pages", "page limit reached; remaining content is counted but not collected");
    return;
  }

  Page page;
  page.index = nextPageSerial_ - 1;
  page.id = serial("page_", nextPageSerial_++, 4);
  page.kind = "page";
  page.startEventIndex = event;
  page.sourceProperties = flattenProperties(props);
  page.width = lengthProp(props, "svg:width");
  page.height = lengthProp(props, "svg:height");
  if (!page.width.valid || !page.height.valid) {
    page.warnings.push_back({"page-size-unknown",
                             "the page did not declare a width and height as lengths"});
  }
  doc_.pages.push_back(std::move(page));
  openPage_ = static_cast<int>(doc_.pages.size()) - 1;
  nextZIndex_ = 0;
  parentStack_.clear();
}

void IrCollector::endPage() {
  const long long event = enter("endPage");
  if (openPage_ < 0) {
    diagnose("warning", "unbalanced-close", "endPage arrived with no open page", event);
    return;
  }
  closeOpenPage(event);
}

void IrCollector::startMasterPage(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startMasterPage");
  if (halt_) return;
  if (openPage_ >= 0) closeOpenPage(event);
  if (static_cast<long long>(doc_.pages.size()) >= limits_.maxPages) {
    halt("limit-pages", "page limit reached; remaining content is counted but not collected");
    return;
  }

  Page page;
  page.index = nextMasterSerial_ - 1;
  page.id = serial("master_", nextMasterSerial_++, 4);
  page.kind = "master";
  page.startEventIndex = event;
  page.sourceProperties = flattenProperties(props);
  page.width = lengthProp(props, "svg:width");
  page.height = lengthProp(props, "svg:height");
  doc_.pages.push_back(std::move(page));
  openPage_ = static_cast<int>(doc_.pages.size()) - 1;
  nextZIndex_ = 0;
  parentStack_.clear();
}

void IrCollector::endMasterPage() {
  const long long event = enter("endMasterPage");
  if (openPage_ < 0) {
    diagnose("warning", "unbalanced-close", "endMasterPage arrived with no open page", event);
    return;
  }
  closeOpenPage(event);
}

void IrCollector::setStyle(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("setStyle");
  if (halt_) return;
  currentStyle_ = flattenProperties(props);
  currentStyleEvent_ = event;
  currentFillAssetId_.clear();

  if (propString(props, "draw:fill") != "bitmap") return;
  const librevenge::RVNGProperty *image = props["draw:fill-image"];
  if (image == nullptr) {
    diagnose("warning", "bitmap-fill-without-image",
             "a bitmap fill style carried no image payload", event);
    return;
  }
  const librevenge::RVNGString base64 = image->getStr();
  // Bound the decode by the encoded length, before allocating: base64 is
  // 4 bytes in for every 3 out, so this refuses an oversized payload
  // without ever materialising it.
  if (static_cast<long long>(base64.size()) / 4 * 3 > limits_.maxAssetBytes) {
    diagnose("error", "limit-asset-size",
             "a bitmap fill payload exceeded the per-asset size limit and was not extracted", event);
    limitation("limit-asset-size", "at least one image exceeded the per-asset size limit");
    return;
  }
  const librevenge::RVNGBinaryData data(base64);
  currentFillAssetId_ = registerAsset(data, propString(props, "librevenge:mime-type"), event);
}

void IrCollector::startLayer(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startLayer");
  if (halt_) return;
  startWrapper("layer", "wrapper", "startLayer", props, event);
}

void IrCollector::endLayer() {
  const long long event = enter("endLayer");
  if (halt_) return;
  endWrapper("layer", "endLayer", event);
}

void IrCollector::startEmbeddedGraphics(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startEmbeddedGraphics");
  if (halt_) return;
  startWrapper("embeddedGraphics", "wrapper", "startEmbeddedGraphics", props, event);
}

void IrCollector::endEmbeddedGraphics() {
  const long long event = enter("endEmbeddedGraphics");
  if (halt_) return;
  endWrapper("embeddedGraphics", "endEmbeddedGraphics", event);
}

void IrCollector::openGroup(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openGroup");
  if (halt_) return;
  startWrapper("group", "group", "openGroup", props, event);
}

void IrCollector::closeGroup() {
  const long long event = enter("closeGroup");
  if (halt_) return;
  endWrapper("group", "closeGroup", event);
}

void IrCollector::drawRectangle(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawRectangle");
  if (halt_) return;
  drawShape("drawRectangle", "rectangle", props, event);
}

void IrCollector::drawEllipse(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawEllipse");
  if (halt_) return;
  drawShape("drawEllipse", "ellipse", props, event);
}

void IrCollector::drawPolygon(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawPolygon");
  if (halt_) return;
  drawShape("drawPolygon", "polygon", props, event);
}

void IrCollector::drawPolyline(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawPolyline");
  if (halt_) return;
  drawShape("drawPolyline", "polyline", props, event);
}

void IrCollector::drawPath(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawPath");
  if (halt_) return;
  drawShape("drawPath", "path", props, event);
}

void IrCollector::drawConnector(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawConnector");
  if (halt_) return;
  drawShape("drawConnector", "connector", props, event);
}

void IrCollector::drawGraphicObject(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("drawGraphicObject");
  if (halt_) return;

  Element *element = newElement("image", "drawGraphicObject", event, props);
  if (element == nullptr) return;
  element->imageRoute = "drawGraphicObject";
  readGeometry(*element, props);
  // Content pictures arrive as bitmap fills. libmspub 0.1.4 calls
  // drawGraphicObject only from its BorderArt code, once per tile, so a
  // decorative border becomes dozens of small images.
  element->warnings.push_back(
      {"probable-border-art",
       "libmspub 0.1.4 emits drawGraphicObject only for BorderArt tiles, so this image is "
       "probably one tile of a decorative border rather than a content picture"});

  const std::string mime = propString(props, "librevenge:mime-type");
  const librevenge::RVNGProperty *payload = props["office:binary-data"];
  if (payload == nullptr) {
    element->type = "unknown";
    element->compatibility = Compatibility::Unsupported;
    element->compatibilityEvidence = "a graphic object arrived with no payload to extract";
    element->warnings.push_back({"graphic-without-payload",
                                 "drawGraphicObject carried no office:binary-data"});
    finishElement(element, event);
    return;
  }

  const librevenge::RVNGString base64 = payload->getStr();
  if (static_cast<long long>(base64.size()) / 4 * 3 > limits_.maxAssetBytes) {
    diagnose("error", "limit-asset-size",
             "a graphic payload exceeded the per-asset size limit and was not extracted", event);
    limitation("limit-asset-size", "at least one image exceeded the per-asset size limit");
    element->compatibility = Compatibility::Unsupported;
    element->compatibilityEvidence = "the payload exceeded the per-asset size limit";
    finishElement(element, event);
    return;
  }

  const librevenge::RVNGBinaryData data(base64);
  element->assetId = registerAsset(data, mime, event);
  if (element->assetId.empty()) {
    element->compatibility = Compatibility::Unsupported;
    element->compatibilityEvidence = "the payload could not be extracted";
    element->warnings.push_back({"asset-not-extracted",
                                 "the payload produced no asset; see the report diagnostics"});
    finishElement(element, event);
    return;
  }

  recordAssetUse(*element, element->assetId);
  doc_.counts.assetPlacements++;

  const std::string settled = normaliseMime(mime);
  if (isMetafileMime(settled)) {
    element->compatibility = Compatibility::Flattened;
    element->compatibilityEvidence =
        "a metafile has no Slides equivalent and would need rasterising first";
  } else {
    element->compatibility = Compatibility::Native;
    element->compatibilityEvidence = "a raster payload maps to a Slides image";
  }
  finishElement(element, event);
}

void IrCollector::startTextObject(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startTextObject");
  if (halt_) return;
  Element *element = newElement("text", "startTextObject", event, props);
  if (element == nullptr) return;
  element->compatibility = Compatibility::Native;
  element->compatibilityEvidence = "a text frame maps to an editable Slides text box";
  textElementId_ = element->id;
  paragraphSerial_ = 0;
  runSerial_ = 0;
  paragraphOpen_ = false;
  spanOpen_ = false;
}

void IrCollector::endTextObject() {
  const long long event = enter("endTextObject");
  if (halt_) return;
  Element *element = elementById(textElementId_);
  if (element == nullptr) {
    diagnose("warning", "unbalanced-close", "endTextObject arrived with no open text object", event);
    return;
  }
  // An empty frame is worth keeping: Publisher uses them as layout
  // placeholders, and a renderer that silently drops them shifts the page.
  if (element->paragraphs.empty()) {
    element->warnings.push_back({"empty-text-frame", "the text frame produced no paragraphs"});
  }
  finishElement(element, event);
  textElementId_.clear();
  paragraphOpen_ = false;
  spanOpen_ = false;
}

void IrCollector::startTableObject(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("startTableObject");
  if (halt_) return;
  Element *element = newElement("table", "startTableObject", event, props);
  if (element == nullptr) return;
  element->compatibility = Compatibility::Native;
  element->compatibilityEvidence = "a table maps to a Slides table";

  const librevenge::RVNGPropertyListVector *columns = props.child("librevenge:table-columns");
  if (columns != nullptr) {
    for (unsigned long i = 0; i < columns->count(); i++) {
      element->table.columnWidths.push_back(lengthProp((*columns)[i], "style:column-width"));
    }
  }
  if (element->table.columnWidths.empty()) {
    element->warnings.push_back({"table-columns-unknown",
                                 "the table declared no column widths; column geometry must be "
                                 "inferred from the cells"});
  }

  TableFrame frame;
  frame.elementId = element->id;
  tableStack_.push_back(frame);
  paragraphSerial_ = 0;
  runSerial_ = 0;
}

void IrCollector::openTableRow(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openTableRow");
  if (halt_) return;
  if (tableStack_.empty()) {
    diagnose("warning", "row-without-table", "openTableRow arrived with no open table", event);
    return;
  }
  Element *table = elementById(tableStack_.back().elementId);
  if (table == nullptr) return;

  TableRow row;
  row.index = tableStack_.back().rowSerial++;
  row.eventIndex = event;
  row.sourceProperties = flattenProperties(props);
  row.isHeader = propBool(props, "librevenge:is-header-row", false);
  row.height = lengthProp(props, "style:row-height");
  if (!row.height.valid) {
    row.height = lengthProp(props, "style:min-row-height");
    row.heightIsMinimum = row.height.valid;
  }
  table->table.rows.push_back(std::move(row));
  tableStack_.back().rowOpen = true;
}

void IrCollector::closeTableRow() {
  const long long event = enter("closeTableRow");
  if (halt_) return;
  if (tableStack_.empty()) {
    diagnose("warning", "unbalanced-close", "closeTableRow arrived with no open table", event);
    return;
  }
  tableStack_.back().rowOpen = false;
  tableStack_.back().cellOpen = false;
}

void IrCollector::openTableCell(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openTableCell");
  if (halt_) return;
  if (tableStack_.empty() || !tableStack_.back().rowOpen) {
    diagnose("warning", "cell-without-row", "openTableCell arrived with no open table row", event);
    return;
  }
  if (tableCells_ >= limits_.maxTableCells) {
    halt("limit-table-cells", "table cell limit reached; remaining content is counted but not collected");
    return;
  }
  Element *table = elementById(tableStack_.back().elementId);
  if (table == nullptr || table->table.rows.empty()) return;

  TableCell cell;
  cell.eventIndex = event;
  cell.row = propInt(props, "librevenge:row", table->table.rows.back().index);
  cell.column = propInt(props, "librevenge:column",
                        static_cast<int>(table->table.rows.back().cells.size()));
  cell.rowSpan = propInt(props, "table:number-rows-spanned", 1);
  cell.columnSpan = propInt(props, "table:number-columns-spanned", 1);
  cell.sourceProperties = flattenProperties(props);
  table->table.rows.back().cells.push_back(std::move(cell));
  tableCells_++;
  tableStack_.back().cellOpen = true;
  paragraphOpen_ = false;
  spanOpen_ = false;
}

void IrCollector::closeTableCell() {
  const long long event = enter("closeTableCell");
  if (halt_) return;
  if (tableStack_.empty()) {
    diagnose("warning", "unbalanced-close", "closeTableCell arrived with no open table", event);
    return;
  }
  tableStack_.back().cellOpen = false;
  paragraphOpen_ = false;
  spanOpen_ = false;
}

void IrCollector::insertCoveredTableCell(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("insertCoveredTableCell");
  if (halt_) return;
  if (tableStack_.empty() || !tableStack_.back().rowOpen) {
    diagnose("warning", "cell-without-row",
             "insertCoveredTableCell arrived with no open table row", event);
    return;
  }
  Element *table = elementById(tableStack_.back().elementId);
  if (table == nullptr || table->table.rows.empty()) return;

  // A covered cell is the shadow of a span. It holds no content, but
  // dropping it would make the grid coordinates in the row inconsistent
  // with the column count.
  TableCell cell;
  cell.eventIndex = event;
  cell.covered = true;
  cell.row = propInt(props, "librevenge:row", table->table.rows.back().index);
  cell.column = propInt(props, "librevenge:column",
                        static_cast<int>(table->table.rows.back().cells.size()));
  cell.sourceProperties = flattenProperties(props);
  table->table.rows.back().cells.push_back(std::move(cell));
  tableCells_++;
}

void IrCollector::endTableObject() {
  const long long event = enter("endTableObject");
  if (halt_) return;
  if (tableStack_.empty()) {
    diagnose("warning", "unbalanced-close", "endTableObject arrived with no open table", event);
    return;
  }
  Element *table = elementById(tableStack_.back().elementId);
  if (table != nullptr) {
    // Observed on PUB-001: libmspub declared a column width but no row
    // height at all. A renderer sizing rows from nothing would silently
    // reflow the table, so say once that the heights were never supplied
    // rather than leaving a null to be read as zero.
    std::size_t missing = 0;
    for (const TableRow &row : table->table.rows) {
      if (!row.height.valid) missing++;
    }
    if (missing > 0) {
      table->warnings.push_back(
          {"table-row-heights-unknown",
           "the source declared no height for " + std::to_string(missing) + " of " +
               std::to_string(table->table.rows.size()) +
               " rows; row geometry must be inferred from the content"});
    }
  }
  finishElement(table, event);
  tableStack_.pop_back();
  paragraphOpen_ = false;
  spanOpen_ = false;
}

void IrCollector::insertTab() {
  const long long event = enter("insertTab");
  if (halt_) return;
  TextItem item;
  item.kind = "tab";
  appendTextItem(std::move(item), event);
}

void IrCollector::insertSpace() {
  const long long event = enter("insertSpace");
  if (halt_) return;
  TextItem item;
  item.kind = "space";
  appendTextItem(std::move(item), event);
}

void IrCollector::insertText(const librevenge::RVNGString &text) {
  const long long event = enter("insertText");
  if (halt_) return;
  doc_.counts.textInsertions++;
  TextItem item;
  item.kind = "text";
  if (text.cstr() != nullptr) item.value.assign(text.cstr(), text.size());
  appendTextItem(std::move(item), event);
}

void IrCollector::insertLineBreak() {
  const long long event = enter("insertLineBreak");
  if (halt_) return;
  TextItem item;
  item.kind = "lineBreak";
  appendTextItem(std::move(item), event);
}

void IrCollector::insertField(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("insertField");
  if (halt_) return;
  TextItem item;
  item.kind = "field";
  item.properties = flattenProperties(props);
  appendTextItem(std::move(item), event);
  limitation("fields-not-evaluated",
             "field values such as page numbers are recorded as fields, not as their displayed "
             "text; the parser does not evaluate them");
}

void IrCollector::openOrderedListLevel(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openOrderedListLevel");
  (void)props;
  (void)event;
  if (halt_) return;
  listKindStack_.push_back("ordered");
}

void IrCollector::openUnorderedListLevel(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openUnorderedListLevel");
  (void)props;
  (void)event;
  if (halt_) return;
  listKindStack_.push_back("unordered");
}

void IrCollector::closeOrderedListLevel() {
  const long long event = enter("closeOrderedListLevel");
  if (halt_) return;
  if (listKindStack_.empty()) {
    diagnose("warning", "unbalanced-close", "closeOrderedListLevel with no open list level", event);
    return;
  }
  listKindStack_.pop_back();
}

void IrCollector::closeUnorderedListLevel() {
  const long long event = enter("closeUnorderedListLevel");
  if (halt_) return;
  if (listKindStack_.empty()) {
    diagnose("warning", "unbalanced-close", "closeUnorderedListLevel with no open list level", event);
    return;
  }
  listKindStack_.pop_back();
}

void IrCollector::openListElement(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openListElement");
  if (halt_) return;
  // A list element is a paragraph that knows it is in a list.
  openParagraphInternal(props, event, listKindStack_.empty() ? std::string("unordered")
                                                             : listKindStack_.back());
}

void IrCollector::closeListElement() {
  enter("closeListElement");
  if (halt_) return;
  closeParagraphInternal();
}

void IrCollector::defineParagraphStyle(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("defineParagraphStyle");
  if (halt_) return;
  // Named styles are not applied to anything by this parser: libmspub
  // resolves styles before emitting spans, so the definitions are
  // provenance rather than data. They are recorded so a reviewer can see
  // the callback happened.
  diagnose("info", "paragraph-style-defined",
           "a named paragraph style was defined; the parser records resolved run properties "
           "rather than applying named styles",
           event);
  (void)props;
}

void IrCollector::openParagraph(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openParagraph");
  if (halt_) return;
  openParagraphInternal(props, event, std::string());
}

void IrCollector::closeParagraph() {
  enter("closeParagraph");
  if (halt_) return;
  closeParagraphInternal();
}

void IrCollector::defineCharacterStyle(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("defineCharacterStyle");
  if (halt_) return;
  diagnose("info", "character-style-defined",
           "a named character style was defined; the parser records resolved run properties "
           "rather than applying named styles",
           event);
  (void)props;
}

void IrCollector::openSpan(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openSpan");
  if (halt_) return;

  Paragraph *paragraph = ensureParagraph(event);
  if (paragraph == nullptr) {
    diagnose("error", "span-not-collected",
             "a span could not be attached to any paragraph because collection had already stopped",
             event);
    return;
  }
  Run run;
  run.index = runSerial_++;
  run.eventIndex = event;
  run.style = flattenProperties(props);
  run.fontFamily = propString(props, "style:font-name");
  const librevenge::RVNGProperty *size = props["fo:font-size"];
  if (size != nullptr) {
    const Length length = toPoints(size);
    run.hasFontSize = true;
    // A font size given as a percentage is relative to something this
    // parser does not track, so keep the number and let the renderer
    // decide; a length converts straight to points.
    run.fontSizePoints = length.valid ? length.points : size->getDouble();
  }
  run.bold = isBoldValue(propString(props, "fo:font-weight"));
  run.italic = isItalicValue(propString(props, "fo:font-style"));
  run.underline = propString(props, "style:text-underline-type");
  if (run.underline.empty()) run.underline = propString(props, "style:text-underline-style");
  run.color = propString(props, "fo:color");
  run.language = propString(props, "fo:language");
  run.country = propString(props, "fo:country");
  run.linkHref = pendingLinkHref_;

  noteFont(run.fontFamily, event);
  paragraph->runs.push_back(std::move(run));
  spanOpen_ = true;
  doc_.counts.runs++;
}

void IrCollector::closeSpan() {
  enter("closeSpan");
  if (halt_) return;
  spanOpen_ = false;
}

void IrCollector::openLink(const librevenge::RVNGPropertyList &props) {
  const long long event = enter("openLink");
  if (halt_) return;
  pendingLinkHref_ = propString(props, "xlink:href");
  Run *run = currentRun();
  if (run != nullptr && spanOpen_) run->linkHref = pendingLinkHref_;
  (void)event;
}

void IrCollector::closeLink() {
  enter("closeLink");
  if (halt_) return;
  pendingLinkHref_.clear();
}

// --- finish ----------------------------------------------------------------

const Document &IrCollector::finish() {
  if (finished_) return doc_;
  finished_ = true;

  if (openPage_ >= 0) {
    doc_.pages[static_cast<std::size_t>(openPage_)].warnings.push_back(
        {"page-not-closed", "the callback stream ended with this page still open"});
    diagnose("warning", "page-not-closed", "the callback stream ended with a page still open",
             eventIndex_);
    closeOpenPage(eventIndex_);
  }
  if (!parentStack_.empty()) {
    diagnose("warning", "container-not-closed",
             "the callback stream ended with " + std::to_string(parentStack_.size()) +
                 " container(s) still open",
             eventIndex_);
    parentStack_.clear();
  }
  if (!tableStack_.empty()) {
    diagnose("warning", "table-not-closed", "the callback stream ended with a table still open",
             eventIndex_);
    tableStack_.clear();
  }

  Counts &counts = doc_.counts;
  for (const Page &page : doc_.pages) {
    if (page.kind == "master") counts.masterPages++;
    else counts.pages++;
  }
  for (const Element &element : doc_.elements) {
    counts.elements++;
    if (element.type == "text") counts.textElements++;
    else if (element.type == "image") counts.imageElements++;
    else if (element.type == "table") counts.tableElements++;
    else if (element.type == "shape") counts.shapeElements++;
    else if (element.type == "line") counts.lineElements++;
    else if (element.type == "path") counts.pathElements++;
    else if (element.type == "group") counts.groupElements++;
    else if (element.type == "wrapper") counts.wrapperElements++;
    else counts.unknownElements++;
  }
  counts.assets = static_cast<long long>(doc_.assets.size());
  counts.fonts = static_cast<long long>(doc_.fonts.size());

  if (!doc_.assets.empty()) {
    limitation("asset-placement-semantics",
               "crop, mask, transparency and recolouring are not recovered for any asset; stored "
               "payloads are originals, not rendered appearances");
  }
  limitation("compatibility-is-a-candidate",
             "compatibility statuses are parser-stage candidates inferred from the callback "
             "stream; no Google rendering has been verified");
  return doc_;
}

} // namespace pubir
