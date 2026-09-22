#include "serialise.h"

namespace pubir {
namespace {

Json propertiesJson(const std::vector<SourceProperty> &props) {
  Json out = Json::object();
  for (const SourceProperty &p : props) out.set(p.key, Json::string(p.value));
  return out;
}

Json notesJson(const std::vector<Note> &notes) {
  Json out = Json::array();
  for (const Note &n : notes) {
    Json j = Json::object();
    j.set("code", Json::string(n.code));
    j.set("message", Json::string(n.message));
    out.push(std::move(j));
  }
  return out;
}

Json boundsJson(const Bounds &bounds) {
  if (!bounds.valid) return Json::null();
  Json out = Json::object();
  out.set("x", Json::number(bounds.x));
  out.set("y", Json::number(bounds.y));
  out.set("width", Json::number(bounds.width));
  out.set("height", Json::number(bounds.height));
  out.set("unit", Json::string("pt"));
  return out;
}

Json lengthJson(const Length &length) {
  if (!length.valid) return Json::null();
  Json out = Json::object();
  out.set("points", Json::number(length.points));
  out.set("sourceValue", Json::number(length.sourceValue));
  out.set("sourceUnit", Json::string(length.sourceUnit));
  return out;
}

Json pointsJson(const std::vector<Point2> &points) {
  Json out = Json::array();
  for (const Point2 &p : points) {
    Json j = Json::object();
    j.set("x", Json::number(p.x));
    j.set("y", Json::number(p.y));
    out.push(std::move(j));
  }
  return out;
}

Json pathJson(const std::vector<PathCommand> &path) {
  Json out = Json::array();
  for (const PathCommand &cmd : path) {
    Json j = Json::object();
    j.set("action", Json::string(cmd.action));
    j.set("properties", propertiesJson(cmd.properties));
    out.push(std::move(j));
  }
  return out;
}

Json textItemsJson(const std::vector<TextItem> &items) {
  Json out = Json::array();
  for (const TextItem &item : items) {
    Json j = Json::object();
    j.set("kind", Json::string(item.kind));
    if (item.kind == "text") j.set("value", Json::string(item.value));
    if (item.kind == "field") j.set("properties", propertiesJson(item.properties));
    out.push(std::move(j));
  }
  return out;
}

Json runJson(const Run &run) {
  Json j = Json::object();
  j.set("index", Json::integer(run.index));
  j.set("eventIndex", Json::integer(run.eventIndex));
  j.set("text", Json::string(run.text));
  j.set("items", textItemsJson(run.items));

  Json style = Json::object();
  style.set("fontFamily", run.fontFamily.empty() ? Json::null() : Json::string(run.fontFamily));
  style.set("fontSizePoints", run.hasFontSize ? Json::number(run.fontSizePoints) : Json::null());
  style.set("bold", Json::boolean(run.bold));
  style.set("italic", Json::boolean(run.italic));
  style.set("underline", run.underline.empty() ? Json::null() : Json::string(run.underline));
  style.set("color", run.color.empty() ? Json::null() : Json::string(run.color));
  style.set("language", run.language.empty() ? Json::null() : Json::string(run.language));
  style.set("country", run.country.empty() ? Json::null() : Json::string(run.country));
  j.set("style", std::move(style));

  j.set("linkHref", run.linkHref.empty() ? Json::null() : Json::string(run.linkHref));
  j.set("implicit", Json::boolean(run.implicit));
  j.set("sourceProperties", propertiesJson(run.style));
  return j;
}

Json paragraphJson(const Paragraph &paragraph) {
  Json j = Json::object();
  j.set("index", Json::integer(paragraph.index));
  j.set("eventIndex", Json::integer(paragraph.eventIndex));

  Json style = Json::object();
  style.set("alignment",
            paragraph.alignment.empty() ? Json::null() : Json::string(paragraph.alignment));
  style.set("lineHeight", paragraph.hasLineHeight ? Json::number(paragraph.lineHeight) : Json::null());
  j.set("style", std::move(style));

  j.set("listKind", paragraph.listKind.empty() ? Json::null() : Json::string(paragraph.listKind));
  j.set("listLevel", Json::integer(paragraph.listLevel));
  j.set("implicit", Json::boolean(paragraph.implicit));
  j.set("sourceProperties", propertiesJson(paragraph.style));

  Json runs = Json::array();
  for (const Run &run : paragraph.runs) runs.push(runJson(run));
  j.set("runs", std::move(runs));
  return j;
}

Json paragraphsJson(const std::vector<Paragraph> &paragraphs) {
  Json out = Json::array();
  for (const Paragraph &p : paragraphs) out.push(paragraphJson(p));
  return out;
}

Json tableJson(const TableData &table) {
  Json j = Json::object();
  Json columns = Json::array();
  for (const Length &width : table.columnWidths) {
    Json c = Json::object();
    c.set("width", lengthJson(width));
    columns.push(std::move(c));
  }
  j.set("columns", std::move(columns));

  Json rows = Json::array();
  for (const TableRow &row : table.rows) {
    Json r = Json::object();
    r.set("index", Json::integer(row.index));
    r.set("eventIndex", Json::integer(row.eventIndex));
    r.set("height", lengthJson(row.height));
    r.set("heightIsMinimum", Json::boolean(row.heightIsMinimum));
    r.set("isHeader", Json::boolean(row.isHeader));
    r.set("sourceProperties", propertiesJson(row.sourceProperties));

    Json cells = Json::array();
    for (const TableCell &cell : row.cells) {
      Json c = Json::object();
      c.set("row", Json::integer(cell.row));
      c.set("column", Json::integer(cell.column));
      c.set("rowSpan", Json::integer(cell.rowSpan));
      c.set("columnSpan", Json::integer(cell.columnSpan));
      c.set("covered", Json::boolean(cell.covered));
      c.set("eventIndex", Json::integer(cell.eventIndex));
      c.set("sourceProperties", propertiesJson(cell.sourceProperties));
      c.set("paragraphs", paragraphsJson(cell.paragraphs));
      cells.push(std::move(c));
    }
    r.set("cells", std::move(cells));
    rows.push(std::move(r));
  }
  j.set("rows", std::move(rows));
  return j;
}

Json elementJson(const Element &element) {
  Json j = Json::object();
  j.set("id", Json::string(element.id));
  j.set("type", Json::string(element.type));
  j.set("pageIndex", Json::integer(element.pageIndex));
  j.set("bounds", boundsJson(element.bounds));
  j.set("rotationDegrees", element.hasRotation ? Json::number(element.rotationDegrees) : Json::null());
  j.set("zIndex", Json::integer(element.zIndex));
  j.set("parentId", element.parentId.empty() ? Json::null() : Json::string(element.parentId));
  j.set("visible", Json::boolean(element.visible));

  Json source = Json::object();
  source.set("callback", Json::string(element.sourceCallback));
  source.set("eventIndex", Json::integer(element.eventIndex));
  source.set("endEventIndex", Json::integer(element.endEventIndex));
  source.set("styleEventIndex", Json::integer(element.styleEventIndex));
  source.set("properties", propertiesJson(element.sourceProperties));
  source.set("styleProperties", propertiesJson(element.styleProperties));
  j.set("source", std::move(source));

  Json compatibility = Json::object();
  compatibility.set("status", Json::string(compatibilityName(element.compatibility)));
  // Spelled out on every element so a consumer cannot mistake a parser
  // guess for a verified round trip through Google.
  compatibility.set("basis", Json::string("parser-candidate"));
  compatibility.set("evidence", Json::string(element.compatibilityEvidence));
  j.set("compatibility", std::move(compatibility));

  if (element.type == "text") j.set("paragraphs", paragraphsJson(element.paragraphs));

  if (element.type == "image") {
    Json image = Json::object();
    image.set("assetId", element.assetId.empty() ? Json::null() : Json::string(element.assetId));
    image.set("route", Json::string(element.imageRoute));
    image.set("shapeKind", element.shapeKind.empty() ? Json::null() : Json::string(element.shapeKind));
    image.set("polygonIsRectangular", Json::boolean(element.polygonIsRectangular));
    image.set("polygon", pointsJson(element.points));
    image.set("path", pathJson(element.path));
    j.set("image", std::move(image));
  }

  if (element.type == "shape" || element.type == "line" || element.type == "path") {
    Json geometry = Json::object();
    geometry.set("shapeKind", Json::string(element.shapeKind));
    geometry.set("polygonIsRectangular", Json::boolean(element.polygonIsRectangular));
    geometry.set("points", pointsJson(element.points));
    geometry.set("path", pathJson(element.path));
    j.set("geometry", std::move(geometry));
  }

  if (element.type == "group" || element.type == "wrapper") {
    Json container = Json::object();
    container.set("kind", Json::string(element.wrapperKind));
    // The distinction the renderer must not collapse: a wrapper is an
    // artefact of how the file is painted, a group is authored structure.
    container.set("isAuthoredGroup", Json::boolean(element.type == "group"));
    j.set("container", std::move(container));
  }

  if (element.type == "table") j.set("table", tableJson(element.table));

  j.set("warnings", notesJson(element.warnings));
  return j;
}

Json diagnosticsJson(const std::vector<Diagnostic> &diagnostics) {
  Json out = Json::array();
  for (const Diagnostic &d : diagnostics) {
    Json j = Json::object();
    j.set("severity", Json::string(d.severity));
    j.set("code", Json::string(d.code));
    j.set("message", Json::string(d.message));
    j.set("pageIndex", d.pageIndex < 0 ? Json::null() : Json::integer(d.pageIndex));
    j.set("eventIndex", d.eventIndex < 0 ? Json::null() : Json::integer(d.eventIndex));
    j.set("elementId", d.elementId.empty() ? Json::null() : Json::string(d.elementId));
    out.push(std::move(j));
  }
  return out;
}

Json sourceJson(const Document &doc) {
  Json j = Json::object();
  j.set("type", Json::string("publisher"));
  // Basename only. A full path would leak the directory the file was
  // processed in, which on a school's machine is often a person's name.
  j.set("filename", Json::string(doc.sourceFilename));
  j.set("sha256", Json::string(doc.sourceSha256));
  j.set("byteLength", Json::integer(doc.sourceByteLength));
  j.set("containerType", Json::string(doc.containerType));
  j.set("formatFamily", Json::string(doc.formatFamily));
  j.set("supportedByParser", Json::boolean(doc.supportedByParser));
  return j;
}

Json callbackCountsJson(const Document &doc) {
  Json out = Json::object();
  for (const auto &entry : doc.callbackCounts) out.set(entry.first, Json::integer(entry.second));
  return out;
}

Json generatorJson() {
  Json j = Json::object();
  j.set("name", Json::string(kGeneratorName));
  j.set("version", Json::string(kGeneratorVersion));
  return j;
}

} // namespace

Json documentJson(const Document &doc) {
  Json root = Json::object();
  root.set("schemaVersion", Json::string(kSchemaVersion));
  root.set("generator", generatorJson());
  root.set("source", sourceJson(doc));

  Json document = Json::object();
  document.set("title", doc.title.empty() ? Json::null() : Json::string(doc.title));
  document.set("pageCount", Json::integer(doc.counts.pages));
  document.set("masterPageCount", Json::integer(doc.counts.masterPages));
  document.set("metadata", propertiesJson(doc.metadata));
  root.set("document", std::move(document));

  Json units = Json::object();
  units.set("length", Json::string("pt"));
  root.set("units", std::move(units));

  Json fonts = Json::array();
  for (const FontUse &font : doc.fonts) {
    Json j = Json::object();
    j.set("family", Json::string(font.family));
    j.set("usageCount", Json::integer(font.usageCount));
    j.set("firstPageIndex", font.firstPageIndex < 0 ? Json::null() : Json::integer(font.firstPageIndex));
    j.set("firstEventIndex", Json::integer(font.firstEventIndex));
    j.set("embedded", Json::boolean(font.embedded));
    j.set("embeddedMime", font.embeddedMime.empty() ? Json::null() : Json::string(font.embeddedMime));
    j.set("embeddedByteLength",
          font.embeddedByteLength > 0 ? Json::integer(font.embeddedByteLength) : Json::null());
    fonts.push(std::move(j));
  }
  root.set("fonts", std::move(fonts));

  Json assets = Json::object();
  assets.set("count", Json::integer(doc.counts.assets));
  assets.set("placementCount", Json::integer(doc.counts.assetPlacements));
  assets.set("manifest", Json::string("assets.json"));
  assets.set("directory", Json::string("assets"));
  Json assetIds = Json::array();
  for (const Asset &asset : doc.assets) assetIds.push(Json::string(asset.id));
  assets.set("ids", std::move(assetIds));
  root.set("assets", std::move(assets));

  Json callbacks = Json::object();
  callbacks.set("total", Json::integer(doc.callbackTotal));
  callbacks.set("counts", callbackCountsJson(doc));
  root.set("callbacks", std::move(callbacks));

  Json pages = Json::array();
  for (const Page &page : doc.pages) {
    Json p = Json::object();
    p.set("id", Json::string(page.id));
    p.set("index", Json::integer(page.index));
    p.set("kind", Json::string(page.kind));
    p.set("width", page.width.valid ? Json::number(page.width.points) : Json::null());
    p.set("height", page.height.valid ? Json::number(page.height.points) : Json::null());
    p.set("unit", Json::string("pt"));

    Json sourceSize = Json::object();
    sourceSize.set("width", lengthJson(page.width));
    sourceSize.set("height", lengthJson(page.height));
    p.set("sourceSize", std::move(sourceSize));

    Json eventRange = Json::object();
    eventRange.set("start", Json::integer(page.startEventIndex));
    eventRange.set("end", Json::integer(page.endEventIndex));
    p.set("eventRange", std::move(eventRange));

    p.set("implicit", Json::boolean(page.implicit));
    p.set("sourceProperties", propertiesJson(page.sourceProperties));

    // Elements are flat and in paint order, with parentId carrying the
    // hierarchy. Nesting them would bury a wrapper's children and make
    // z-order harder to read, not easier.
    Json elements = Json::array();
    for (const std::string &id : page.elementIds) {
      for (const Element &element : doc.elements) {
        if (element.id == id) {
          elements.push(elementJson(element));
          break;
        }
      }
    }
    p.set("elements", std::move(elements));
    p.set("warnings", notesJson(page.warnings));
    pages.push(std::move(p));
  }
  root.set("pages", std::move(pages));

  root.set("warnings", diagnosticsJson(doc.diagnostics));
  root.set("limitations", notesJson(doc.limitations));

  Json truncation = Json::object();
  truncation.set("truncated", Json::boolean(doc.truncated));
  truncation.set("reason", doc.truncationReason.empty() ? Json::null()
                                                        : Json::string(doc.truncationReason));
  root.set("truncation", std::move(truncation));
  return root;
}

Json assetsJson(const Document &doc) {
  Json root = Json::object();
  root.set("schemaVersion", Json::string(kSchemaVersion));
  root.set("generator", generatorJson());
  root.set("source", sourceJson(doc));

  Json assets = Json::array();
  for (const Asset &asset : doc.assets) {
    Json j = Json::object();
    j.set("id", Json::string(asset.id));
    j.set("sha256", Json::string(asset.sha256));
    j.set("filename", Json::string(asset.filename));
    j.set("mimeType", Json::string(asset.mime));
    j.set("declaredMimeType",
          asset.declaredMime.empty() ? Json::null() : Json::string(asset.declaredMime));
    j.set("sniffedMimeType",
          asset.sniffedMime.empty() ? Json::null() : Json::string(asset.sniffedMime));
    j.set("byteLength", Json::integer(asset.byteLength));
    j.set("pixelWidth", asset.hasPixelDimensions ? Json::integer(asset.pixelWidth) : Json::null());
    j.set("pixelHeight", asset.hasPixelDimensions ? Json::integer(asset.pixelHeight) : Json::null());
    j.set("useCount", Json::integer(static_cast<long long>(asset.uses.size())));

    Json uses = Json::array();
    for (const AssetUse &use : asset.uses) {
      Json u = Json::object();
      u.set("pageIndex", Json::integer(use.pageIndex));
      u.set("elementId", Json::string(use.elementId));
      u.set("eventIndex", Json::integer(use.eventIndex));
      u.set("route", Json::string(use.route));
      u.set("bounds", boundsJson(use.bounds));
      u.set("polygonIsRectangular", Json::boolean(use.polygonIsRectangular));
      u.set("polygon", pointsJson(use.polygon));
      u.set("path", pathJson(use.path));
      uses.push(std::move(u));
    }
    j.set("uses", std::move(uses));
    j.set("warnings", notesJson(asset.warnings));
    assets.push(std::move(j));
  }
  root.set("assets", std::move(assets));
  return root;
}

Json reportJson(const Document &doc, const Limits &limits, const std::string &status,
                const std::string &failureCode, const std::string &failureMessage) {
  Json root = Json::object();
  root.set("schemaVersion", Json::string(kSchemaVersion));
  root.set("generator", generatorJson());
  root.set("status", Json::string(status));
  root.set("failureCode", failureCode.empty() ? Json::null() : Json::string(failureCode));
  root.set("failureMessage", failureMessage.empty() ? Json::null() : Json::string(failureMessage));
  root.set("source", sourceJson(doc));

  Json counts = Json::object();
  counts.set("pages", Json::integer(doc.counts.pages));
  counts.set("masterPages", Json::integer(doc.counts.masterPages));
  counts.set("elements", Json::integer(doc.counts.elements));
  counts.set("textElements", Json::integer(doc.counts.textElements));
  counts.set("imageElements", Json::integer(doc.counts.imageElements));
  counts.set("tableElements", Json::integer(doc.counts.tableElements));
  counts.set("shapeElements", Json::integer(doc.counts.shapeElements));
  counts.set("lineElements", Json::integer(doc.counts.lineElements));
  counts.set("pathElements", Json::integer(doc.counts.pathElements));
  counts.set("groupElements", Json::integer(doc.counts.groupElements));
  counts.set("wrapperElements", Json::integer(doc.counts.wrapperElements));
  counts.set("unknownElements", Json::integer(doc.counts.unknownElements));
  counts.set("paragraphs", Json::integer(doc.counts.paragraphs));
  counts.set("runs", Json::integer(doc.counts.runs));
  counts.set("textInsertions", Json::integer(doc.counts.textInsertions));
  counts.set("assets", Json::integer(doc.counts.assets));
  counts.set("assetPlacements", Json::integer(doc.counts.assetPlacements));
  counts.set("fonts", Json::integer(doc.counts.fonts));
  counts.set("callbacks", Json::integer(doc.callbackTotal));
  root.set("counts", std::move(counts));

  root.set("callbackCounts", callbackCountsJson(doc));

  Json compatibility = Json::object();
  long long tally[5] = {0, 0, 0, 0, 0};
  for (const Element &element : doc.elements) tally[static_cast<int>(element.compatibility)]++;
  compatibility.set("NATIVE", Json::integer(tally[0]));
  compatibility.set("SUBSTITUTED", Json::integer(tally[1]));
  compatibility.set("FLATTENED", Json::integer(tally[2]));
  compatibility.set("UNSUPPORTED", Json::integer(tally[3]));
  compatibility.set("IGNORED", Json::integer(tally[4]));
  compatibility.set("basis", Json::string("parser-candidate"));
  root.set("compatibility", std::move(compatibility));

  Json fonts = Json::array();
  for (const FontUse &font : doc.fonts) {
    Json j = Json::object();
    j.set("family", Json::string(font.family));
    j.set("usageCount", Json::integer(font.usageCount));
    j.set("embedded", Json::boolean(font.embedded));
    fonts.push(std::move(j));
  }
  root.set("fonts", std::move(fonts));

  Json limitsJson = Json::object();
  limitsJson.set("maxInputBytes", Json::integer(limits.maxInputBytes));
  limitsJson.set("maxCallbacks", Json::integer(limits.maxCallbacks));
  limitsJson.set("maxPages", Json::integer(limits.maxPages));
  limitsJson.set("maxElements", Json::integer(limits.maxElements));
  limitsJson.set("maxAssets", Json::integer(limits.maxAssets));
  limitsJson.set("maxAssetBytes", Json::integer(limits.maxAssetBytes));
  limitsJson.set("maxTotalAssetBytes", Json::integer(limits.maxTotalAssetBytes));
  limitsJson.set("maxTextBytes", Json::integer(limits.maxTextBytes));
  limitsJson.set("maxSeconds", Json::number(limits.maxSeconds));
  root.set("limits", std::move(limitsJson));

  Json truncation = Json::object();
  truncation.set("truncated", Json::boolean(doc.truncated));
  truncation.set("reason", doc.truncationReason.empty() ? Json::null()
                                                        : Json::string(doc.truncationReason));
  root.set("truncation", std::move(truncation));

  root.set("diagnostics", diagnosticsJson(doc.diagnostics));
  root.set("limitations", notesJson(doc.limitations));
  return root;
}

} // namespace pubir
