// The librevenge drawing sink that builds the intermediate model.
//
// libmspub drives an RVNGDrawingInterface; this is that interface. It
// builds the IR directly rather than going through an intermediate text
// dump, so nothing is lost to a serialisation format in between.
//
// The class is usable with no .pub file at all: every method is a plain
// virtual override taking a property list, so tests drive it with
// synthetic callback sequences and never need libmspub or a document.
#ifndef PUBIR_COLLECTOR_H
#define PUBIR_COLLECTOR_H

#include <librevenge/librevenge.h>

#include <chrono>
#include <map>
#include <string>
#include <vector>

#include "limits.h"
#include "model.h"

namespace pubir {

class IrCollector : public librevenge::RVNGDrawingInterface {
public:
  explicit IrCollector(const Limits &limits = Limits());
  ~IrCollector() override = default;

  // Source facts the callback stream cannot supply. Call before parsing.
  void setSource(const std::string &filename, const std::string &sha256, long long byteLength,
                 const std::string &containerType, const std::string &formatFamily);
  void setSupported(bool supported);

  // Finishes any structure libmspub left open (a truncated file can end
  // mid-page) and computes the derived counts. Safe to call twice.
  const Document &finish();
  const Document &document() const { return doc_; }

  bool truncated() const { return doc_.truncated; }

  // --- RVNGDrawingInterface -------------------------------------------
  void startDocument(const librevenge::RVNGPropertyList &propList) override;
  void endDocument() override;
  void setDocumentMetaData(const librevenge::RVNGPropertyList &propList) override;
  void defineEmbeddedFont(const librevenge::RVNGPropertyList &propList) override;
  void startPage(const librevenge::RVNGPropertyList &propList) override;
  void endPage() override;
  void startMasterPage(const librevenge::RVNGPropertyList &propList) override;
  void endMasterPage() override;
  void setStyle(const librevenge::RVNGPropertyList &propList) override;
  void startLayer(const librevenge::RVNGPropertyList &propList) override;
  void endLayer() override;
  void startEmbeddedGraphics(const librevenge::RVNGPropertyList &propList) override;
  void endEmbeddedGraphics() override;
  void openGroup(const librevenge::RVNGPropertyList &propList) override;
  void closeGroup() override;
  void drawRectangle(const librevenge::RVNGPropertyList &propList) override;
  void drawEllipse(const librevenge::RVNGPropertyList &propList) override;
  void drawPolygon(const librevenge::RVNGPropertyList &propList) override;
  void drawPolyline(const librevenge::RVNGPropertyList &propList) override;
  void drawPath(const librevenge::RVNGPropertyList &propList) override;
  void drawGraphicObject(const librevenge::RVNGPropertyList &propList) override;
  void drawConnector(const librevenge::RVNGPropertyList &propList) override;
  void startTextObject(const librevenge::RVNGPropertyList &propList) override;
  void endTextObject() override;
  void startTableObject(const librevenge::RVNGPropertyList &propList) override;
  void openTableRow(const librevenge::RVNGPropertyList &propList) override;
  void closeTableRow() override;
  void openTableCell(const librevenge::RVNGPropertyList &propList) override;
  void closeTableCell() override;
  void insertCoveredTableCell(const librevenge::RVNGPropertyList &propList) override;
  void endTableObject() override;
  void insertTab() override;
  void insertSpace() override;
  void insertText(const librevenge::RVNGString &text) override;
  void insertLineBreak() override;
  void insertField(const librevenge::RVNGPropertyList &propList) override;
  void openOrderedListLevel(const librevenge::RVNGPropertyList &propList) override;
  void openUnorderedListLevel(const librevenge::RVNGPropertyList &propList) override;
  void closeOrderedListLevel() override;
  void closeUnorderedListLevel() override;
  void openListElement(const librevenge::RVNGPropertyList &propList) override;
  void closeListElement() override;
  void defineParagraphStyle(const librevenge::RVNGPropertyList &propList) override;
  void openParagraph(const librevenge::RVNGPropertyList &propList) override;
  void closeParagraph() override;
  void defineCharacterStyle(const librevenge::RVNGPropertyList &propList) override;
  void openSpan(const librevenge::RVNGPropertyList &propList) override;
  void closeSpan() override;
  void openLink(const librevenge::RVNGPropertyList &propList) override;
  void closeLink() override;

private:
  // Records the callback and returns its event index, or -1 if a limit has
  // already halted collection. Every override calls this first, so the
  // callback counts stay honest even after content collection stops.
  long long enter(const char *name);
  bool halted() const { return halt_; }
  void halt(const std::string &code, const std::string &message);

  void diagnose(const char *severity, const std::string &code, const std::string &message,
                long long eventIndex = -1, const std::string &elementId = std::string());
  void limitation(const std::string &code, const std::string &message);

  Page &ensurePage(long long eventIndex, const char *because);
  void closeOpenPage(long long eventIndex);

  Element *newElement(const std::string &type, const char *callback, long long eventIndex,
                      const librevenge::RVNGPropertyList &props);
  Element *elementById(const std::string &id);
  void finishElement(Element *element, long long eventIndex);

  // Text plumbing. Paragraphs land in whichever container is on top:
  // a text object, or a table cell.
  std::vector<Paragraph> *textSink();
  Paragraph *currentParagraph();
  Run *currentRun();
  // Both return null when no container could be opened -- under a halt,
  // or once the element limit refuses another implicit frame. Callers
  // record a diagnostic rather than dereferencing.
  Run *ensureRun(long long eventIndex);
  Paragraph *ensureParagraph(long long eventIndex);
  void appendTextItem(TextItem item, long long eventIndex);
  void openParagraphInternal(const librevenge::RVNGPropertyList &props, long long eventIndex,
                             const std::string &listKind);
  void closeParagraphInternal();

  void drawShape(const char *callback, const std::string &shapeKind,
                 const librevenge::RVNGPropertyList &props, long long eventIndex);
  void readGeometry(Element &element, const librevenge::RVNGPropertyList &props);
  bool boundsFromProps(const librevenge::RVNGPropertyList &props, Bounds &out);
  Bounds boundsFromPoints(const std::vector<Point2> &points);
  void recordAssetUse(Element &element, const std::string &assetId);
  // Registers a payload, deduplicating by content hash. Returns the asset
  // id, or an empty string when a limit refused it.
  std::string registerAsset(const librevenge::RVNGBinaryData &data, const std::string &declaredMime,
                            long long eventIndex);
  void noteFont(const std::string &family, long long eventIndex);
  void startWrapper(const std::string &wrapperKind, const std::string &type, const char *callback,
                    const librevenge::RVNGPropertyList &props, long long eventIndex);
  void endWrapper(const std::string &wrapperKind, const char *callback, long long eventIndex);

  Limits limits_;
  Document doc_;
  bool halt_ = false;
  bool finished_ = false;
  std::chrono::steady_clock::time_point started_;

  long long eventIndex_ = 0;
  int nextElementSerial_ = 1;
  int nextPageSerial_ = 1;
  int nextMasterSerial_ = 1;
  int nextAssetSerial_ = 1;

  int openPage_ = -1;        // index into doc_.pages
  int nextZIndex_ = 0;
  std::vector<std::string> parentStack_;

  std::vector<SourceProperty> currentStyle_;
  long long currentStyleEvent_ = -1;
  // A bitmap fill is decoded once, when setStyle presents it, and reused
  // by every shape drawn under that style. Decoding per draw call would
  // re-base64-decode the same megabyte for each of a dozen placements.
  std::string currentFillAssetId_;

  // Text state.
  std::string textElementId_;
  std::vector<std::string> listKindStack_;
  bool paragraphOpen_ = false;
  bool spanOpen_ = false;
  std::string pendingLinkHref_;
  int paragraphSerial_ = 0;
  int runSerial_ = 0;
  long long textBytes_ = 0;

  // Table state.
  struct TableFrame {
    std::string elementId;
    int rowSerial = 0;
    bool rowOpen = false;
    bool cellOpen = false;
  };
  std::vector<TableFrame> tableStack_;

  long long totalAssetBytes_ = 0;
  long long tableCells_ = 0;
  std::map<std::string, std::string> assetByHash_; // sha256 -> asset id
};

// Flattens a property list into ordered key/value strings. Binary payloads
// are replaced with a marker: a base64 image has no business inside
// document.json, and inlining one would defeat the asset store.
std::vector<SourceProperty> flattenProperties(const librevenge::RVNGPropertyList &props);

} // namespace pubir

#endif
