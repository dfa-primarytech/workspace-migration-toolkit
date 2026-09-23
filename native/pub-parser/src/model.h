// The versioned intermediate representation.
//
// Source-independent by design: nothing here names Publisher except the
// `source` block and the `sourceCallback` provenance fields. A PPTX or
// DOCX front end should be able to fill the same structures.
//
// Two rules shape everything below.
//
//  1. Nothing is silently dropped. Every callback either becomes an
//     element, attaches to one, or produces a diagnostic carrying its
//     page and event index.
//  2. Every recovered value keeps its provenance. Geometry is normalised
//     to points, but the raw librevenge properties ride along in
//     `sourceProperties` so a later renderer can revisit a decision this
//     parser got wrong without re-parsing the .pub.
#ifndef PUBIR_MODEL_H
#define PUBIR_MODEL_H

#include <map>
#include <string>
#include <vector>

#include "units.h"

namespace pubir {

// Schema version of document.json / assets.json / report.json. Bump the
// minor for additive fields, the major for anything a consumer must change
// to read.
constexpr const char *kSchemaVersion = "1.0.0";
constexpr const char *kGeneratorName = "publisher-parser";
constexpr const char *kGeneratorVersion = "0.1.0";

// Shared compatibility vocabulary. At parser stage these are *candidates*
// backed by what the callback stream showed, not verified statements about
// how Google will render the object. The IR says so explicitly via
// Element::compatibilityBasis.
enum class Compatibility { Native, Substituted, Flattened, Unsupported, Ignored };
const char *compatibilityName(Compatibility c);

struct Note {
  std::string code;
  std::string message;
};

struct Diagnostic {
  std::string severity; // "info", "warning", "error"
  std::string code;
  std::string message;
  int pageIndex = -1;       // -1 when document level
  long long eventIndex = -1; // -1 when not tied to a callback
  std::string elementId;
};

struct Bounds {
  bool valid = false;
  double x = 0.0;
  double y = 0.0;
  double width = 0.0;
  double height = 0.0;
};

struct Point2 {
  double x = 0.0;
  double y = 0.0;
};

struct SourceProperty {
  std::string key;
  std::string value;
};

// One entry of an svg:d path, kept verbatim. The renderer decides what a
// cubic or an arc becomes; the parser only records that it was there.
struct PathCommand {
  std::string action; // M, L, C, Q, A, Z
  std::vector<SourceProperty> properties;
};

// A single piece of inline content inside a run. Spaces, tabs and line
// breaks arrive as their own callbacks and are kept as their own items:
// collapsing them into the text string would lose the distinction between
// a typed space and an explicit one.
struct TextItem {
  std::string kind; // "text", "space", "tab", "lineBreak", "field"
  std::string value; // populated for kind == "text"
  std::vector<SourceProperty> properties; // populated for kind == "field"
};

struct Run {
  int index = 0;
  long long eventIndex = -1;
  std::vector<SourceProperty> style;
  std::string fontFamily;
  bool hasFontSize = false;
  double fontSizePoints = 0.0;
  bool bold = false;
  bool italic = false;
  std::string underline; // librevenge's style:text-underline-type, verbatim
  std::string color;
  std::string language;
  std::string country;
  std::string linkHref;
  std::vector<TextItem> items;
  // Convenience flattening of `items`. Fields contribute nothing: their
  // displayed value depends on rendering context the parser cannot know,
  // and inventing one would put fiction into the text layer.
  std::string text;
  bool implicit = false; // created because content arrived with no open span
};

struct Paragraph {
  int index = 0;
  long long eventIndex = -1;
  std::vector<SourceProperty> style;
  std::string alignment;
  bool hasLineHeight = false;
  double lineHeight = 0.0;
  std::string listKind; // "", "ordered", "unordered"
  int listLevel = 0;
  std::vector<Run> runs;
  bool implicit = false;
};

struct TableCell {
  int row = 0;
  int column = 0;
  int rowSpan = 1;
  int columnSpan = 1;
  bool covered = false;
  long long eventIndex = -1;
  std::vector<SourceProperty> sourceProperties;
  std::vector<Paragraph> paragraphs;
};

struct TableRow {
  int index = 0;
  long long eventIndex = -1;
  Length height;
  bool heightIsMinimum = false;
  bool isHeader = false;
  std::vector<SourceProperty> sourceProperties;
  std::vector<TableCell> cells;
};

struct TableData {
  std::vector<Length> columnWidths;
  std::vector<TableRow> rows;
};

struct Element {
  std::string id;
  // "text", "image", "table", "shape", "line", "path", "group",
  // "wrapper", "unknown"
  std::string type;
  int pageIndex = 0;
  Bounds bounds;
  bool hasRotation = false;
  double rotationDegrees = 0.0;
  int zIndex = 0;
  std::string parentId;
  bool visible = true;
  std::string sourceCallback;
  long long eventIndex = -1;
  long long endEventIndex = -1;
  std::vector<SourceProperty> sourceProperties;
  // The setStyle payload in force when this element was drawn.
  std::vector<SourceProperty> styleProperties;
  long long styleEventIndex = -1;
  Compatibility compatibility = Compatibility::Unsupported;
  std::string compatibilityEvidence;
  std::vector<Note> warnings;

  // type == "text"
  std::vector<Paragraph> paragraphs;

  // type == "image"
  std::string assetId;
  // "drawGraphicObject" or "bitmapFillShape". The second route matters:
  // Publisher files routinely paint every visible picture as a polygon
  // with a bitmap fill and never call drawGraphicObject at all.
  std::string imageRoute;

  // type == "shape" / "line" / "path", and geometry retained for images
  // that arrived by the bitmap-fill route.
  std::string shapeKind; // rectangle, ellipse, polygon, polyline, connector, path
  bool hasGeometry = false;
  bool polygonIsRectangular = false;
  // Internal to classification; not serialised. libmspub folds a shape's
  // rotation and flips into its outline instead of reporting them, so a
  // rotated picture arrives as a rotated rectangle and a flipped one as a
  // rectangle wound the other way. See readGeometry.
  bool outlineIsRotatedRectangle = false;
  bool outlineIsMirrored = false;
  std::vector<Point2> points;
  std::vector<PathCommand> path;

  // type == "group" / "wrapper"
  // startLayer is a rendering construct, not evidence of a Publisher group
  // the user made, so the two are recorded under different types.
  std::string wrapperKind; // "layer", "embeddedGraphics", "group"

  // type == "table"
  TableData table;
};

struct Page {
  std::string id;
  int index = 0;
  std::string kind = "page"; // "page" or "master"
  Length width;
  Length height;
  std::vector<SourceProperty> sourceProperties;
  std::vector<std::string> elementIds; // paint order
  long long startEventIndex = -1;
  long long endEventIndex = -1;
  std::vector<Note> warnings;
  bool implicit = false;
};

struct AssetUse {
  int pageIndex = 0;
  std::string elementId;
  long long eventIndex = -1;
  std::string route;
  Bounds bounds;
  bool polygonIsRectangular = false;
  std::vector<Point2> polygon;
  std::vector<PathCommand> path;
};

struct Asset {
  std::string id;
  std::string sha256;
  std::string filename; // relative to the output directory
  std::string declaredMime;
  std::string sniffedMime;
  std::string mime; // what the parser settled on
  long long byteLength = 0;
  bool hasPixelDimensions = false;
  long long pixelWidth = 0;
  long long pixelHeight = 0;
  std::vector<AssetUse> uses;
  std::vector<Note> warnings;
  std::string data; // payload; written out by the bundle writer
};

struct FontUse {
  std::string family;
  long long usageCount = 0;
  int firstPageIndex = -1;
  long long firstEventIndex = -1;
  bool embedded = false;
  std::string embeddedMime;
  long long embeddedByteLength = 0;
};

struct Counts {
  long long pages = 0;
  long long masterPages = 0;
  long long elements = 0;
  long long textElements = 0;
  long long imageElements = 0;
  long long tableElements = 0;
  long long shapeElements = 0;
  long long lineElements = 0;
  long long pathElements = 0;
  long long groupElements = 0;
  long long wrapperElements = 0;
  long long unknownElements = 0;
  long long paragraphs = 0;
  long long runs = 0;
  long long textInsertions = 0;
  long long assets = 0;
  long long assetPlacements = 0;
  long long fonts = 0;
};

struct Document {
  std::string sourceFilename;
  std::string sourceSha256;
  long long sourceByteLength = 0;
  std::string containerType = "unknown";
  std::string formatFamily = "unknown";
  bool supportedByParser = false;

  std::vector<SourceProperty> metadata;
  std::string title;

  std::vector<Page> pages;       // masters included, distinguished by `kind`
  std::vector<Element> elements; // flat, in emission order
  std::vector<Asset> assets;
  std::vector<FontUse> fonts;

  std::map<std::string, long long> callbackCounts; // ordered for determinism
  long long callbackTotal = 0;

  std::vector<Diagnostic> diagnostics;
  std::vector<Note> limitations;
  Counts counts;

  bool truncated = false;
  std::string truncationReason;
};

} // namespace pubir

#endif
